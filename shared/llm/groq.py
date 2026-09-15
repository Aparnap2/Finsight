"""GroqProvider: stdlib urllib transport with injectable stub for testing.

This module retains the original urllib-based implementation used by unit
tests that inject ``transport=`` stubs.  For production use, prefer
:mod:`shared.llm.openai_compatible` (OpenAI SDK-based, connection pooling).

The two implementations share the same :class:`~shared.llm.provider.LLMProvider`
protocol and are interchangeable.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from shared.llm.errors import CredentialMissingError, ProviderError, ProviderUnavailableError
from shared.llm.provider import validate_structured_output
from shared.llm.types import InvestigationPrompt, ModelMetadata, ProviderCallLog, ProviderHealth

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 3
_DEFAULT_TIMEOUT_S = 10.0
_HEALTH_TIMEOUT_S = 5.0

TransportFn = Callable[[str, dict[str, Any], dict[str, str], float], dict[str, Any]]


def _default_transport(
    url: str, payload: dict[str, Any], headers: dict[str, str], timeout_s: float
) -> dict[str, Any]:
    """POST JSON via stdlib urllib and return the decoded response body."""
    body = json.dumps(payload).encode("utf-8")
    request_headers = {"Content-Type": "application/json", **headers}
    request = urllib.request.Request(url, data=body, headers=request_headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        raw = response.read().decode("utf-8")
    decoded = json.loads(raw)
    if not isinstance(decoded, dict):
        raise ProviderError("groq transport returned a non-object response")
    return decoded


class GroqProvider:
    """LLMProvider backed by Groq with injectable urllib transport.

    Used by unit tests that need to stub HTTP responses via ``transport=``.
    For production, use :class:`~shared.llm.openai_compatible.OpenAICompatibleProvider`.
    """

    def __init__(
        self,
        *,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        max_retries: int = _MAX_ATTEMPTS,
        transport: TransportFn | None = None,
    ) -> None:
        self._model_override = model
        self._base_url_override = base_url
        self._api_key_override = api_key
        self._timeout_s = timeout_s
        self._max_attempts = max(1, min(int(max_retries), _MAX_ATTEMPTS))
        self._transport: TransportFn = transport or _default_transport
        self._call_log: list[ProviderCallLog] = []

    def __repr__(self) -> str:
        return f"GroqProvider(model={self._resolve_model()!r})"

    @property
    def call_log(self) -> list[ProviderCallLog]:
        return self._call_log

    def _resolve_model(self) -> str:
        if self._model_override:
            return self._model_override
        from shared.config import get_settings

        return get_settings().groq_chat_model

    def _resolve_base_url(self) -> str:
        if self._base_url_override:
            return self._base_url_override
        from shared.config import get_settings

        return get_settings().groq_base_url.rstrip("/")

    def _resolve_api_key(self) -> str:
        if self._api_key_override is not None:
            key = self._api_key_override
        else:
            from shared.config import get_settings

            key = get_settings().groq_api_key
        if not key:
            raise CredentialMissingError("groq credential missing (set GROQ_API_KEY)")
        return key

    def model_metadata(self) -> ModelMetadata:
        return ModelMetadata(provider="groq", model=self._resolve_model())

    def health_check(self) -> ProviderHealth:
        start = time.monotonic()
        try:
            key = self._resolve_api_key()
        except CredentialMissingError:
            return ProviderHealth(ok=False, latency_ms=0.0, reason="credential missing")
        url = f"{self._resolve_base_url()}/models"
        request = urllib.request.Request(
            url, headers={"Authorization": "Bearer redacted"}, method="GET"
        )
        request.add_unredirected_header("Authorization", f"Bearer {key}")
        try:
            with urllib.request.urlopen(request, timeout=_HEALTH_TIMEOUT_S) as response:
                status = getattr(response, "status", 200)
            latency_ms = (time.monotonic() - start) * 1000.0
            if 200 <= int(status) < 300:
                return ProviderHealth(ok=True, latency_ms=latency_ms)
            return ProviderHealth(
                ok=False, latency_ms=latency_ms, reason=f"health status {int(status)}"
            )
        except urllib.error.HTTPError as exc:
            latency_ms = (time.monotonic() - start) * 1000.0
            return ProviderHealth(
                ok=False, latency_ms=latency_ms, reason=f"health status {exc.code}"
            )
        except Exception:
            latency_ms = (time.monotonic() - start) * 1000.0
            logger.warning("groq health probe failed", exc_info=False)
            return ProviderHealth(ok=False, latency_ms=latency_ms, reason="health probe failed")

    def generate_structured[T: BaseModel](
        self, prompt: InvestigationPrompt | str, response_schema: type[T]
    ) -> T:
        key = self._resolve_api_key()
        model = self._resolve_model()
        url = f"{self._resolve_base_url()}/chat/completions"
        messages = (
            prompt.to_messages()
            if isinstance(prompt, InvestigationPrompt)
            else [{"role": "user", "content": prompt}]
        )
        input_chars = sum(len(m.get("content", "")) for m in messages)
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        wire_headers = {"Authorization": f"Bearer {key}"}

        start = time.monotonic()
        last_error: BaseException | None = None
        for _attempt in range(1, self._max_attempts + 1):
            try:
                logger.debug("groq generate_structured model=%s url=%s", model, url)
                decoded = self._transport(url, payload, wire_headers, self._timeout_s)
                content = self._extract_content(decoded)
                result = validate_structured_output(content, response_schema)
                self._call_log.append(
                    ProviderCallLog(
                        provider="groq",
                        model=model,
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
                if _attempt >= self._max_attempts:
                    break
                time.sleep(0.05 * _attempt)

        latency_ms = (time.monotonic() - start) * 1000.0
        kind = type(last_error).__name__ if last_error is not None else "UnknownError"
        self._call_log.append(
            ProviderCallLog(
                provider="groq",
                model=model,
                success=False,
                latency_ms=latency_ms,
                input_chars=input_chars,
                output_chars=None,
                error_kind=kind,
            )
        )
        logger.warning("groq generate_structured failed kind=%s", kind)
        raise ProviderUnavailableError(f"groq request failed after {self._max_attempts} attempt(s)")

    @staticmethod
    def _extract_content(decoded: dict[str, Any]) -> str:
        try:
            content = decoded["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderUnavailableError("groq response missing choices content") from exc
        if not isinstance(content, str) or not content.strip():
            raise ProviderUnavailableError("groq response contained empty content")
        return content
