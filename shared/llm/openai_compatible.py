"""OpenAI-compatible adapter: one implementation for all OpenAI-wire endpoints.

Works with Groq, OpenRouter, vLLM, Ollama, Azure OpenAI, LiteLLM, and any
other provider that speaks the ``/v1/chat/completions`` wire protocol.

Uses the OpenAI Python SDK for HTTP transport with a custom ``base_url``.
Health checks use stdlib ``urllib`` (lightweight, no SDK overhead).

The adapter reads its config from a frozen :class:`LLMProviderConfig`
(see :mod:`shared.llm.config`).  Swapping providers requires only changing
the config — no code changes.
"""

from __future__ import annotations

import logging
import time
import urllib.error
import urllib.request
from typing import Any

from pydantic import BaseModel

from shared.llm.config import LLMProviderConfig
from shared.llm.errors import CredentialMissingError, ProviderError, ProviderUnavailableError
from shared.llm.provider import validate_structured_output
from shared.llm.types import InvestigationPrompt, ModelMetadata, ProviderCallLog, ProviderHealth

logger = logging.getLogger(__name__)

_HEALTH_TIMEOUT_S = 5.0
_HEALTH_PATH = "/models"


class OpenAICompatibleProvider:
    """LLMProvider backed by any OpenAI-compatible chat completions endpoint.

    This is the single adapter for all providers that speak the OpenAI wire
    protocol.  To add a new provider, set config — no subclass needed.

    Implements the :class:`~shared.llm.provider.LLMProvider` protocol.
    """

    def __init__(self, config: LLMProviderConfig) -> None:
        """Create an adapter from a resolved config.

        Args:
            config: Frozen provider configuration (model, base_url, api_key, etc.).
        """
        self._config = config
        self._call_log: list[ProviderCallLog] = []
        self._openai_client: Any = None  # lazy singleton

    def __repr__(self) -> str:
        """Credential-safe repr: provider + model only."""
        return (
            f"OpenAICompatibleProvider(provider={self._config.provider!r}, "
            f"model={self._config.model!r})"
        )

    @property
    def call_log(self) -> list[ProviderCallLog]:
        """Audit journal (model/cost metadata only, no secrets)."""
        return self._call_log

    @property
    def config(self) -> LLMProviderConfig:
        """Return the resolved config (read-only)."""
        return self._config

    def _get_client(self) -> Any:
        """Lazy OpenAI client (created once, thread-safe for single-thread)."""
        if self._openai_client is None:
            from openai import OpenAI

            self._openai_client = OpenAI(
                api_key=self._config.api_key,
                base_url=self._config.base_url,
                timeout=self._config.timeout_s,
                max_retries=0,  # we handle retries ourselves
            )
        return self._openai_client

    def model_metadata(self) -> ModelMetadata:
        """Return provider/model identity for audit logging."""
        return ModelMetadata(provider=self._config.provider, model=self._config.model)

    def health_check(self) -> ProviderHealth:
        """Probe liveness; never raises, never leaks keys.

        Tries ``GET {base_url}/models`` first.  If that returns 403 (some
        providers restrict the models endpoint), falls back to a minimal
        chat completion probe with ``max_tokens=1``.
        """
        if not self._config.api_key:
            return ProviderHealth(ok=False, latency_ms=0.0, reason="credential missing")

        start = time.monotonic()
        url = f"{self._config.base_url}{_HEALTH_PATH}"
        request = urllib.request.Request(
            url, headers={"Authorization": "Bearer redacted"}, method="GET"
        )
        request.add_unredirected_header("Authorization", f"Bearer {self._config.api_key}")
        try:
            with urllib.request.urlopen(request, timeout=_HEALTH_TIMEOUT_S) as response:
                status = getattr(response, "status", 200)
            latency_ms = (time.monotonic() - start) * 1000.0
            if 200 <= int(status) < 300:
                return ProviderHealth(ok=True, latency_ms=latency_ms)
            # 403 on /models is common (e.g. Groq restricts model listing)
            # Fall through to completion probe
            if int(status) == 403:
                return self._health_probe_completion(start)
            return ProviderHealth(
                ok=False, latency_ms=latency_ms, reason=f"health status {int(status)}"
            )
        except urllib.error.HTTPError as exc:
            if exc.code == 403:
                return self._health_probe_completion(start)
            latency_ms = (time.monotonic() - start) * 1000.0
            return ProviderHealth(
                ok=False, latency_ms=latency_ms, reason=f"health status {exc.code}"
            )
        except Exception:
            latency_ms = (time.monotonic() - start) * 1000.0
            logger.warning("health probe failed provider=%s", self._config.provider, exc_info=False)
            return ProviderHealth(ok=False, latency_ms=latency_ms, reason="health probe failed")

    def _health_probe_completion(self, start: float) -> ProviderHealth:
        """Fallback health probe: minimal chat completion with max_tokens=1."""
        try:
            client = self._get_client()
            client.chat.completions.create(
                model=self._config.model,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=1,
                temperature=0,
            )
            latency_ms = (time.monotonic() - start) * 1000.0
            return ProviderHealth(ok=True, latency_ms=latency_ms)
        except Exception as exc:
            latency_ms = (time.monotonic() - start) * 1000.0
            return ProviderHealth(
                ok=False,
                latency_ms=latency_ms,
                reason=f"completion probe failed: {type(exc).__name__}",
            )

    def generate_structured[T: BaseModel](
        self, prompt: InvestigationPrompt | str, response_schema: type[T]
    ) -> T:
        """Call chat completions and return strictly validated output.

        Uses ``response_format={"type": "json_object"}`` for structured output.
        Validates through :func:`validate_structured_output` at the boundary —
        unknown fields are always rejected regardless of schema ``extra``.

        Raises:
            CredentialMissingError: When no API key is configured.
            ProviderUnavailableError: On timeout / 5xx / 429 after retries.
            SchemaMismatchError: When the response fails boundary validation.
        """
        if not self._config.api_key:
            raise CredentialMissingError(
                f"{self._config.provider} credential missing "
                f"(set {self._config.provider.upper()}_API_KEY)"
            )

        messages = (
            prompt.to_messages()
            if isinstance(prompt, InvestigationPrompt)
            else [{"role": "user", "content": prompt}]
        )
        input_chars = sum(len(m.get("content", "")) for m in messages)
        max_attempts = max(1, min(self._config.max_retries, 3))

        start = time.monotonic()
        last_error: BaseException | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                logger.debug(
                    "llm generate provider=%s model=%s attempt=%d",
                    self._config.provider,
                    self._config.model,
                    attempt,
                )
                client = self._get_client()
                response = client.chat.completions.create(
                    model=self._config.model,
                    messages=messages,
                    temperature=0,
                    response_format={"type": "json_object"},
                )
                content = self._extract_content(response)
                result = validate_structured_output(content, response_schema)
                self._call_log.append(
                    ProviderCallLog(
                        provider=self._config.provider,
                        model=self._config.model,
                        success=True,
                        latency_ms=(time.monotonic() - start) * 1000.0,
                        input_chars=input_chars,
                        output_chars=len(content),
                    )
                )
                return result
            except ProviderError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt >= max_attempts:
                    break
                time.sleep(0.05 * attempt)

        latency_ms = (time.monotonic() - start) * 1000.0
        kind = type(last_error).__name__ if last_error is not None else "UnknownError"
        self._call_log.append(
            ProviderCallLog(
                provider=self._config.provider,
                model=self._config.model,
                success=False,
                latency_ms=latency_ms,
                input_chars=input_chars,
                output_chars=None,
                error_kind=kind,
            )
        )
        logger.warning("llm generate failed provider=%s kind=%s", self._config.provider, kind)
        raise ProviderUnavailableError(
            f"{self._config.provider} request failed after {max_attempts} attempt(s)"
        )

    @staticmethod
    def _extract_content(response: Any) -> str:
        """Extract the assistant content string from an OpenAI SDK response."""
        try:
            content = response.choices[0].message.content
        except (AttributeError, IndexError, TypeError) as exc:
            raise ProviderUnavailableError("response missing choices content") from exc
        if not isinstance(content, str) or not content.strip():
            raise ProviderUnavailableError("response contained empty content")
        return content


# Backward-compatible aliases
GroqProvider = OpenAICompatibleProvider
LLMProviderImpl = OpenAICompatibleProvider
