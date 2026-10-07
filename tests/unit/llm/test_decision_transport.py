"""Decision transport: strict-schema capability is explicit per provider.

- Default config sends ``json_object`` (unchanged wire behavior).
- Opt-in ``strict_structured_output`` sends ``json_schema``/strict built
  from the response schema — only in OpenAICompatibleProvider, the one
  adapter whose wire protocol supports it.
- Every provider reports an honest ``structured_output_mode``; no
  provider fakes a guarantee it does not implement.
- Provider 400/transport failures surface as ProviderError, never as a
  decision (no ABSTAIN synthesis from transport state).

No network: the OpenAI SDK client is stubbed at the instance boundary.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from shared.llm import (
    FakeLLM,
    GroqProvider,
    LLMProviderConfig,
    OpenAICompatibleProvider,
    ProviderError,
    ReplayProvider,
)


class WidgetOut(BaseModel):
    name: str
    count: int


def _config(**overrides: Any) -> LLMProviderConfig:
    base: dict[str, Any] = {
        "provider": "groq",
        "base_url": "https://x",
        "api_key": "k",
        "model": "m",
    }
    base.update(overrides)
    return LLMProviderConfig(**base)


def _sdk_stub(payload_text: str, captured: dict[str, Any]) -> Any:
    def _create(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=payload_text))]
        )

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create)))


class TestStructuredOutputMode:
    def test_default_mode_is_json_object(self) -> None:
        provider = OpenAICompatibleProvider(config=_config())
        assert provider.structured_output_mode == "json_object"

    def test_strict_flag_reports_json_schema(self) -> None:
        provider = OpenAICompatibleProvider(config=_config(strict_structured_output=True))
        assert provider.structured_output_mode == "json_schema"

    def test_legacy_groq_provider_reports_json_object(self) -> None:
        provider = GroqProvider(model="m", api_key="k", base_url="https://x")
        assert provider.structured_output_mode == "json_object"

    def test_fake_and_replay_report_local_validation(self) -> None:
        assert FakeLLM().structured_output_mode == "local_validation"
        assert (
            ReplayProvider.from_dict({"response": {"name": "w", "count": 1}}).structured_output_mode
            == "local_validation"
        )


class TestStrictPayloadShape:
    def test_strict_sends_json_schema_built_from_response_schema(self) -> None:
        captured: dict[str, Any] = {}
        provider = OpenAICompatibleProvider(config=_config(strict_structured_output=True))
        provider._openai_client = _sdk_stub('{"name": "w", "count": 2}', captured)
        result = provider.generate_structured("hi", WidgetOut)
        assert result == WidgetOut(name="w", count=2)
        fmt = captured["response_format"]
        assert fmt["type"] == "json_schema"
        assert fmt["json_schema"]["strict"] is True
        assert fmt["json_schema"]["name"] == "WidgetOut"
        assert (
            fmt["json_schema"]["schema"]["properties"].keys()
            == WidgetOut.model_json_schema()["properties"].keys()
        )

    def test_default_sends_json_object(self) -> None:
        captured: dict[str, Any] = {}
        provider = OpenAICompatibleProvider(config=_config())
        provider._openai_client = _sdk_stub('{"name": "w", "count": 2}', captured)
        provider.generate_structured("hi", WidgetOut)
        assert captured["response_format"] == {"type": "json_object"}

    def test_strict_still_validates_at_boundary(self) -> None:
        captured: dict[str, Any] = {}
        provider = OpenAICompatibleProvider(config=_config(strict_structured_output=True))
        provider._openai_client = _sdk_stub('{"name": "w", "count": "NaN"}', captured)
        from shared.llm import SchemaMismatchError

        with pytest.raises(SchemaMismatchError):
            provider.generate_structured("hi", WidgetOut)


class TestTransportFailuresAreNotDecisions:
    def test_sdk_400_raises_provider_error(self) -> None:
        # NOTE: deliberately no `openai` import here: the reconcile purity
        # gate forbids LLM modules in sys.modules, so the stub raises a
        # plain transport-shaped error instead of BadRequestError.

        def _raise(**kwargs: Any) -> Any:
            raise RuntimeError("Failed to generate JSON: 400 json_validate_failed")

        stub = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_raise)))
        provider = OpenAICompatibleProvider(config=_config())
        provider._openai_client = stub
        with pytest.raises(ProviderError):
            provider.generate_structured("hi", WidgetOut)
        assert provider.call_log and provider.call_log[-1].success is False

    def test_fake_scripted_abstain_shape_validates_as_decision(self) -> None:
        from agents.p8_runtime import contract as p8_01

        fake = FakeLLM(
            scripted={
                "WidgetOut": {"name": "w", "count": 1},
            }
        )
        got = fake.generate_structured("hi", WidgetOut)
        assert got == WidgetOut(name="w", count=1)
        decision = p8_01.validate_decision_output(
            p8_01.RawModelOutput(
                run_id="r",
                text=json.dumps(
                    {
                        "outcome": "abstain",
                        "reason_code": "policy_refusal",
                        "explanation": "cannot approve refunds",
                        "missing_evidence": [],
                    }
                ),
                received_at=__import__("datetime").datetime(2026, 10, 5),
            )
        )
        assert decision.outcome == p8_01.DecisionOutcome.ABSTAIN
