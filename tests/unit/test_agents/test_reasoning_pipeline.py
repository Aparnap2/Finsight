"""Tests for the reasoning pipeline wired through the agents layer.

Covers the structured LLM boundary (fake injected LLM client, never a real
one), the deterministic Null fallback, the commentary-draft orchestration,
and the guarantee that raw data never reaches the commentary provider.
"""

from __future__ import annotations

import json
from decimal import Decimal

from agents.reasoning.orchestrator import run_reasoning_commentary
from finance.evidence.models import EvidenceItem
from finance.reasoning import ReasoningContext, run_reasoning_pipeline
from finance.reasoning.llm_boundary import StructuredCommentaryProvider
from shared.models.assertions import Assertion, AssertionType, SupportLevel
from shared.models.state import CommentaryDraft


def _evidence() -> list[EvidenceItem]:
    """Build a small, deterministic evidence set."""
    return [
        EvidenceItem(
            claim="Revenue variance",
            source_type="variance",
            source_id="rev_100",
            source_value=Decimal("80000"),
            confidence="high",
        ),
        EvidenceItem(
            claim="COGS variance",
            source_type="gl",
            source_id="cogs_500",
            source_value=Decimal("30000"),
            confidence="high",
        ),
    ]


def _assertions() -> list[Assertion]:
    """Typed assertions as the LLM boundary would receive them."""
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
            id="num_2",
            type=AssertionType.NUMERIC,
            text="COGS variance $30,000",
            value=Decimal("30000"),
            evidence_ids=["gl:cogs_500"],
            support_level=SupportLevel.VERIFIED,
            confidence=0.85,
        ),
    ]


class FakeLLMClient:
    """Injected LLM client stub — no real LLM is ever called."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


class SpyProvider:
    """Spy CommentaryProvider that records exactly what it receives."""

    def __init__(self) -> None:
        self.received: list[object] = []

    def generate(self, assertions: list[Assertion]) -> str:
        self.received.extend(assertions)
        return "spy commentary"


class TestStructuredCommentaryProvider:
    """The structured provider enforces the typed LLM boundary."""

    def test_valid_json_output_is_validated_and_serialized(self) -> None:
        payload = {
            "summary": "Revenue exceeded budget.",
            "sections": [
                {"heading": "Variance Analysis", "content": "Revenue is up $80,000."}
            ],
        }
        llm = FakeLLMClient(json.dumps(payload))
        provider = StructuredCommentaryProvider(llm_client=llm)

        text = provider.generate(_assertions())

        assert "Revenue exceeded budget." in text
        assert "Variance Analysis" in text
        assert provider.degraded is False

    def test_invalid_json_degrades_to_deterministic_summary(self) -> None:
        llm = FakeLLMClient("this is not json")
        provider = StructuredCommentaryProvider(llm_client=llm)

        text = provider.generate(_assertions())

        assert provider.degraded is True
        assert "Deterministic Commentary" in text
        assert "Revenue variance $80,000" in text

    def test_prompt_contains_assertions_but_no_raw_evidence_fields(self) -> None:
        payload = {"summary": "s", "sections": []}
        llm = FakeLLMClient(json.dumps(payload))
        provider = StructuredCommentaryProvider(llm_client=llm)

        provider.generate(_assertions())

        prompt = llm.prompts[-1]
        assert "[numeric] Revenue variance $80,000" in prompt
        assert "source_table" not in prompt
        assert "record_id" not in prompt
        assert "source_value" not in prompt


class TestPipelineViaAgents:
    """The pipeline behaves correctly when wired through the agents layer."""

    def test_pipeline_never_passes_raw_evidence_to_provider(self) -> None:
        spy = SpyProvider()
        run_reasoning_pipeline(_evidence(), ReasoningContext(), spy)

        assert spy.received, "the provider should have been called"
        assert all(isinstance(item, Assertion) for item in spy.received)
        assert not any(isinstance(item, EvidenceItem) for item in spy.received)
        for item in spy.received:
            assert isinstance(item, Assertion)
            assert all(isinstance(eid, str) for eid in item.evidence_ids)

    def test_run_reasoning_commentary_returns_draft_without_llm(self) -> None:
        context = ReasoningContext(period="2026-07", entity_name="Acme Corp")
        draft = run_reasoning_commentary(_evidence(), context)

        assert isinstance(draft, CommentaryDraft)
        assert draft.sections
        assert draft.generated_at
        assert draft.status == "draft"
        assert draft.assertions_used

    def test_run_reasoning_commentary_with_injected_llm_client(self) -> None:
        payload = {
            "summary": "Executive summary text.",
            "sections": [
                {"heading": "Variance Analysis", "content": "Detailed body text."}
            ],
        }
        llm = FakeLLMClient(json.dumps(payload))
        context = ReasoningContext(period="2026-07", entity_name="Acme Corp")

        draft = run_reasoning_commentary(_evidence(), context, llm_client=llm)

        assert isinstance(draft, CommentaryDraft)
        section_types = {section.section_type for section in draft.sections}
        assert "executive_summary" in section_types
        assert "variance_analysis" in section_types
