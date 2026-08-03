"""Tests for LLM structured-output compliance at the reasoning boundary.

Targets the real ``finance/reasoning/llm_boundary.py`` provider with an
injected fake LLM client — no real LLM is ever called. Verifies the
provider only ever sees assertions (never raw data), enforces the
``CommentaryOutput`` schema, and degrades deterministically on any
non-compliant response.
"""
from __future__ import annotations

import json
from decimal import Decimal

import pytest

from finance.reasoning.llm_boundary import (
    CommentaryOutput,
    NullCommentaryProvider,
    StructuredCommentaryProvider,
    _extract_json,
)
from shared.models.assertions import Assertion, AssertionType, SupportLevel


def _assertions() -> list[Assertion]:
    """Assertions as the reasoning pipeline would produce them."""
    return [
        Assertion(
            id="num_1",
            type=AssertionType.NUMERIC,
            text="Revenue variance $80,000",
            value=Decimal("80000"),
            evidence_ids=["variance:rev_100"],
            support_level=SupportLevel.VERIFIED,
            confidence=0.9,
        ),
        Assertion(
            id="hyp_1",
            type=AssertionType.HYPOTHESIS,
            text="Volume decline likely drove the shortfall",
            evidence_ids=["gl:cogs_500"],
            support_level=SupportLevel.PROBABLE,
            confidence=0.7,
        ),
    ]


class FakeLLMClient:
    """Duck-typed LLM client stub recording every prompt it receives."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


def _compliant_payload() -> dict:
    return {
        "summary": "Revenue exceeded budget.",
        "sections": [{"heading": "Variance Analysis", "content": "Revenue is up."}],
    }


# ── Structured output compliance ─────────────────────────────────────────────


class TestStructuredOutputCompliance:
    def test_compliant_payload_is_validated_and_serialized(self) -> None:
        llm = FakeLLMClient(json.dumps(_compliant_payload()))
        provider = StructuredCommentaryProvider(llm_client=llm)
        text = provider.generate(_assertions())

        assert provider.degraded is False
        assert "Revenue exceeded budget." in text
        assert "Variance Analysis" in text

    def test_missing_required_field_degrades(self) -> None:
        payload = {"sections": [{"heading": "H", "content": "C"}]}  # no summary
        llm = FakeLLMClient(json.dumps(payload))
        provider = StructuredCommentaryProvider(llm_client=llm)

        text = provider.generate(_assertions())

        assert provider.degraded is True
        assert "Deterministic Commentary" in text

    def test_wrong_type_degrades(self) -> None:
        payload = {"summary": 42, "sections": []}  # summary must be str
        llm = FakeLLMClient(json.dumps(payload))
        provider = StructuredCommentaryProvider(llm_client=llm)

        text = provider.generate(_assertions())

        assert provider.degraded is True
        assert "Deterministic Commentary" in text

    def test_malformed_section_degrades(self) -> None:
        payload = {"summary": "s", "sections": [{"heading": "Missing content"}]}
        llm = FakeLLMClient(json.dumps(payload))
        provider = StructuredCommentaryProvider(llm_client=llm)

        text = provider.generate(_assertions())

        assert provider.degraded is True
        assert "Deterministic Commentary" in text

    def test_extra_fields_are_tolerated(self) -> None:
        payload = _compliant_payload()
        payload["extra_unexpected_key"] = "ignored"
        llm = FakeLLMClient(json.dumps(payload))
        provider = StructuredCommentaryProvider(llm_client=llm)

        text = provider.generate(_assertions())

        assert provider.degraded is False
        assert "Revenue exceeded budget." in text

    def test_non_json_response_degrades(self) -> None:
        llm = FakeLLMClient("this is not json")
        provider = StructuredCommentaryProvider(llm_client=llm)
        text = provider.generate(_assertions())
        assert provider.degraded is True
        assert "Deterministic Commentary" in text

    def test_fenced_json_is_tolerated(self) -> None:
        payload = json.dumps(_compliant_payload())
        llm = FakeLLMClient(f"```json\n{payload}\n```")
        provider = StructuredCommentaryProvider(llm_client=llm)
        text = provider.generate(_assertions())
        assert provider.degraded is False
        assert "Revenue exceeded budget." in text

    def test_recovery_after_degredation_clears_flag(self) -> None:
        llm = FakeLLMClient("not json")
        provider = StructuredCommentaryProvider(llm_client=llm)
        provider.generate(_assertions())
        assert provider.degraded is True

        llm.response = json.dumps(_compliant_payload())
        provider.generate(_assertions())
        assert provider.degraded is False


class TestExtractJson:
    def test_plain_json(self) -> None:
        assert _extract_json('{"a": 1}') == {"a": 1}

    def test_fenced_json(self) -> None:
        assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_invalid_returns_none(self) -> None:
        assert _extract_json("garbage") is None

    def test_non_dict_json_returns_none(self) -> None:
        assert _extract_json("[1, 2, 3]") is None


# ── Prompt safety: assertions only, never raw data ───────────────────────────


class TestPromptSafety:
    def test_prompt_contains_only_assertion_truth(self) -> None:
        llm = FakeLLMClient(json.dumps(_compliant_payload()))
        provider = StructuredCommentaryProvider(llm_client=llm)
        provider.generate(_assertions())

        prompt = llm.prompts[-1]
        assert "[numeric] Revenue variance $80,000" in prompt
        assert "[hypothesis] Volume decline likely drove the shortfall" in prompt

    def test_prompt_never_leaks_raw_evidence_fields(self) -> None:
        llm = FakeLLMClient(json.dumps(_compliant_payload()))
        provider = StructuredCommentaryProvider(llm_client=llm)
        provider.generate(_assertions())

        prompt = llm.prompts[-1]
        # Raw evidence identifiers and source values must never reach the LLM.
        assert "variance:rev_100" not in prompt
        assert "gl:cogs_500" not in prompt
        assert "source_value" not in prompt
        assert "evidence_ids" not in prompt

    def test_prompt_contains_anti_hallucination_rules(self) -> None:
        llm = FakeLLMClient(json.dumps(_compliant_payload()))
        provider = StructuredCommentaryProvider(llm_client=llm)
        provider.generate(_assertions())

        prompt = llm.prompts[-1]
        # The template forbids inventing values/claims — hallucination guardrail.
        assert "You may NOT invent any values" in prompt
        assert "You may NOT add any new claims" in prompt

    def test_empty_assertions_render_safely(self) -> None:
        llm = FakeLLMClient(json.dumps(_compliant_payload()))
        provider = StructuredCommentaryProvider(llm_client=llm)
        provider.generate([])

        prompt = llm.prompts[-1]
        assert "(no assertions)" in prompt


# ── Deterministic degraded mode ──────────────────────────────────────────────


class TestNullCommentaryProvider:
    def test_deterministic_summary_counts_assertions(self) -> None:
        text = NullCommentaryProvider().generate(_assertions())
        assert "Deterministic Commentary" in text
        assert "2 assertion(s)" in text

    def test_empty_assertions_produce_message(self) -> None:
        text = NullCommentaryProvider().generate([])
        assert "No assertions were produced" in text
