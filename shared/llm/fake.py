"""FakeLLM: deterministic scripted provider for tests and P3 fallback drills.

No network is used. Responses and failures are scripted per response-schema
name; every call is recorded in :attr:`journal` with model/cost metadata
only (no secrets exist on this provider).
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel

from shared.llm.errors import ProviderError
from shared.llm.provider import validate_structured_output
from shared.llm.types import InvestigationPrompt, ModelMetadata, ProviderCallLog, ProviderHealth


class FakeLLM:
    """Scripted LLMProvider with a call journal."""

    def __init__(
        self,
        *,
        scripted: dict[str, dict[str, Any] | BaseModel | str] | None = None,
        failures: dict[str, BaseException] | None = None,
        fail_all: BaseException | None = None,
        healthy: bool = True,
        model: str = "fake-llm-1",
    ) -> None:
        """Create a fake provider.

        Args:
            scripted: Mapping of ``response_schema.__name__`` to a payload
                (dict, JSON string, or BaseModel) returned for that schema.
            failures: Mapping of schema name to an exception raised instead.
            fail_all: When set, every call raises this exception.
            healthy: Controls :meth:`health_check`.
            model: Model label recorded in metadata and the journal.
        """
        self._scripted: dict[str, dict[str, Any] | BaseModel | str] = dict(scripted or {})
        self._failures: dict[str, BaseException] = dict(failures or {})
        self._fail_all = fail_all
        self._healthy = healthy
        self._model = model
        self.journal: list[ProviderCallLog] = []

    def __repr__(self) -> str:
        """Credential-safe repr (this provider holds no secrets)."""
        return f"FakeLLM(model={self._model!r}, healthy={self._healthy!r})"

    @property
    def call_journal(self) -> list[ProviderCallLog]:
        """Alias for :attr:`journal` (model/cost metadata only)."""
        return self.journal

    def script_response(self, schema_name: str, payload: dict[str, Any] | BaseModel | str) -> None:
        """Script the payload returned for ``schema_name``."""
        self._scripted[schema_name] = payload

    def script_failure(self, schema_name: str, error: BaseException) -> None:
        """Script the exception raised for ``schema_name``."""
        self._failures[schema_name] = error

    def clear_journal(self) -> None:
        """Empty the call journal."""
        self.journal.clear()

    def model_metadata(self) -> ModelMetadata:
        """Return fake model identity for audit logging."""
        return ModelMetadata(provider="fake", model=self._model)

    def health_check(self) -> ProviderHealth:
        """Return the scripted liveness signal (no network)."""
        if self._healthy:
            return ProviderHealth(ok=True, latency_ms=0.0)
        return ProviderHealth(ok=False, latency_ms=0.0, reason="fake unhealthy")

    def generate_structured[T: BaseModel](
        self, prompt: InvestigationPrompt | str, response_schema: type[T]
    ) -> T:
        """Return the scripted payload after strict boundary validation."""
        start = time.monotonic()
        schema_name = getattr(response_schema, "__name__", str(response_schema))
        input_chars = self._prompt_chars(prompt)
        if self._fail_all is not None:
            self._record(False, start, input_chars, None, self._fail_all)
            raise self._fail_all
        if schema_name in self._failures:
            error = self._failures[schema_name]
            self._record(False, start, input_chars, None, error)
            raise error
        if schema_name not in self._scripted:
            error = ProviderError(f"no scripted response for {schema_name}")
            self._record(False, start, input_chars, None, error)
            raise error
        payload = self._scripted[schema_name]
        try:
            result = validate_structured_output(payload, response_schema)
        except ProviderError as exc:
            self._record(False, start, input_chars, self._output_chars(payload), exc)
            raise
        self._record(True, start, input_chars, self._output_chars(payload), None)
        return result

    def _record(
        self,
        success: bool,
        start: float,
        input_chars: int,
        output_chars: int | None,
        error: BaseException | None,
    ) -> None:
        """Append a credential-free journal entry."""
        self.journal.append(
            ProviderCallLog(
                provider="fake",
                model=self._model,
                success=success,
                latency_ms=(time.monotonic() - start) * 1000.0,
                input_chars=input_chars,
                output_chars=output_chars,
                error_kind=None if error is None else type(error).__name__,
            )
        )

    @staticmethod
    def _prompt_chars(prompt: InvestigationPrompt | str) -> int:
        """Measure rendered prompt length without retaining content."""
        if isinstance(prompt, InvestigationPrompt):
            return len(prompt.user_prompt) + len(prompt.system_prompt)
        return len(prompt)

    @staticmethod
    def _output_chars(payload: dict[str, Any] | BaseModel | str) -> int | None:
        """Measure scripted payload length without retaining content."""
        if isinstance(payload, str):
            return len(payload)
        if isinstance(payload, BaseModel):
            return len(payload.model_dump_json())
        try:
            return len(str(payload))
        except Exception:
            return None
