"""ReplayProvider: deterministic LLM from recorded fixtures.

Replays a previously-recorded :class:`InvestigationPlan` from a JSON fixture
file.  Used by E2E tests that need a realistic LLM output without network
calls.

Usage::

    provider = ReplayProvider.from_fixture("tests/evals/llm/fixtures/partial_refund.json")
    plan = planner.plan(request)  # returns the recorded plan
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from shared.llm.errors import ProviderError, SchemaMismatchError
from shared.llm.provider import validate_structured_output
from shared.llm.types import InvestigationPrompt, ModelMetadata, ProviderCallLog, ProviderHealth


class ReplayProvider:
    """LLMProvider that replays a fixed response from a JSON fixture."""

    def __init__(self, fixture_data: dict[str, Any], *, model: str = "replay") -> None:
        """Create a replay provider from a parsed fixture dict.

        The fixture must contain a ``"response"`` key with the JSON object
        to return from ``generate_structured``.
        """
        self._fixture = fixture_data
        self._model = model
        self._call_log: list[ProviderCallLog] = []
        self._call_count = 0

    @classmethod
    def from_fixture(cls, path: str | Path) -> ReplayProvider:
        """Load a fixture from a JSON file."""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Fixture not found: {p}")
        with open(p) as f:
            data = json.load(f)
        if "response" not in data:
            raise ValueError(f"Fixture missing 'response' key: {p}")
        return cls(data, model=data.get("model", "replay"))

    @classmethod
    def from_dict(cls, response: dict[str, Any], *, model: str = "replay") -> ReplayProvider:
        """Create a replay provider from an inline response dict."""
        return cls({"response": response}, model=model)

    def __repr__(self) -> str:
        return f"ReplayProvider(model={self._model!r}, calls={self._call_count})"

    @property
    def call_log(self) -> list[ProviderCallLog]:
        return self._call_log

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(ok=True, latency_ms=0.0)

    def model_metadata(self) -> ModelMetadata:
        return ModelMetadata(provider="replay", model=self._model)

    def generate_structured[T: BaseModel](
        self, prompt: InvestigationPrompt | str, response_schema: type[T]
    ) -> T:
        """Return the fixture response validated against the schema."""
        self._call_count += 1
        response = self._fixture["response"]
        try:
            result = validate_structured_output(response, response_schema)
        except SchemaMismatchError:
            raise
        except Exception as exc:
            raise ProviderError(f"replay failed: {exc}") from exc

        input_chars = len(str(prompt))
        self._call_log.append(
            ProviderCallLog(
                provider="replay",
                model=self._model,
                success=True,
                latency_ms=0.0,
                input_chars=input_chars,
                output_chars=len(json.dumps(response)),
            )
        )
        return result
