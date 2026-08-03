"""Unit tests for the deterministic reasoning pipeline (finance.reasoning).

Covers the pipeline with a fake ``CommentaryProvider`` (deterministic
string), confidence in [0, 1] as ``Decimal``, provenance coverage of every
evidence id, the Null provider without an LLM, and the guarantee that raw
data never reaches the commentary provider.
"""

from __future__ import annotations

from decimal import Decimal

from finance.evidence.models import EvidenceItem
from finance.reasoning import (
    ReasoningContext,
    ReasoningReport,
    run_reasoning_pipeline,
)
from finance.reasoning.confidence import (
    agreement_score,
    materiality_factor,
    score_assertion,
)
from shared.models.assertions import Assertion, AssertionType, SupportLevel


def _evidence() -> list[EvidenceItem]:
    """Build a small, deterministic evidence set."""
    return [
        EvidenceItem(
            claim="Marketing spend variance",
            source_type="variance",
            source_id="acct_4010",
            source_value=Decimal("50000"),
            confidence="high",
        ),
        EvidenceItem(
            claim="Marketing spend variance (GL corroboration)",
            source_type="gl",
            source_id="acct_4010",
            source_value=Decimal("50000"),
            confidence="high",
        ),
        EvidenceItem(
            claim="Headcount driver behind the variance",
            source_type="driver",
            source_id="headcount_eng",
            source_value=Decimal("12"),
            confidence="medium",
        ),
    ]


class FakeCommentaryProvider:
    """Deterministic fake provider that records everything it receives."""

    def __init__(self) -> None:
        self.received: list[object] = []
        self.calls = 0

    def generate(self, assertions: list[Assertion]) -> str:
        self.calls += 1
        self.received.extend(assertions)
        return "Fake commentary text"


class TestRunReasoningPipeline:
    """End-to-end behaviour of the pipeline with a fake provider."""

    def test_runs_with_fake_provider(self) -> None:
        provider = FakeCommentaryProvider()
        context = ReasoningContext(
            period="2026-07",
            entity_name="Acme Corp",
            materiality_threshold=Decimal("1000"),
        )
        report = run_reasoning_pipeline(_evidence(), context, provider)

        assert isinstance(report, ReasoningReport)
        assert provider.calls == 1
        assert len(report.assertions) > 0
        assert report.commentary == "Fake commentary text"

    def test_provider_never_receives_raw_data(self) -> None:
        provider = FakeCommentaryProvider()
        run_reasoning_pipeline(_evidence(), ReasoningContext(), provider)

        assert provider.received, "the provider should have been called"
        assert all(isinstance(item, Assertion) for item in provider.received)
        assert not any(isinstance(item, EvidenceItem) for item in provider.received)

    def test_confidence_scores_are_decimal_in_unit_interval(self) -> None:
        report = run_reasoning_pipeline(
            _evidence(), ReasoningContext(), FakeCommentaryProvider()
        )
        assert report.confidence
        for score in report.confidence.values():
            assert isinstance(score, Decimal)
            assert Decimal("0") <= score <= Decimal("1")

    def test_provenance_includes_every_evidence_id(self) -> None:
        evidence = _evidence()
        report = run_reasoning_pipeline(
            evidence, ReasoningContext(), FakeCommentaryProvider()
        )
        assert len(report.evidence_ids) == len(evidence)
        provenance_ids = {entry.evidence_id for entry in report.provenance}
        assert set(report.evidence_ids) <= provenance_ids

    def test_provenance_trails_assertion_linkage(self) -> None:
        report = run_reasoning_pipeline(
            _evidence(), ReasoningContext(), FakeCommentaryProvider()
        )
        created = [
            entry for entry in report.provenance if entry.step == "assertion_created"
        ]
        assert created
        for entry in created:
            assert entry.assertion_id in report.confidence

    def test_empty_evidence_still_produces_report(self) -> None:
        report = run_reasoning_pipeline(
            [], ReasoningContext(), FakeCommentaryProvider()
        )
        assert report.evidence_ids == []
        assert report.assertions == []
        assert report.commentary == "Fake commentary text"
        assert report.degraded is False


class TestNullProvider:
    """The deterministic Null provider needs no LLM at all."""

    def test_null_provider_works_without_llm(self) -> None:
        report = run_reasoning_pipeline(_evidence(), ReasoningContext())
        assert isinstance(report.commentary, str)
        assert report.commentary
        assert report.degraded is True

    def test_null_provider_is_deterministic(self) -> None:
        first = run_reasoning_pipeline(_evidence(), ReasoningContext())
        second = run_reasoning_pipeline(_evidence(), ReasoningContext())
        assert first.commentary == second.commentary
        assert first.confidence == second.confidence


class TestConfidence:
    """Deterministic, Decimal-based confidence scoring."""

    def test_score_assertion_deterministic_and_bounded(self) -> None:
        assertion = Assertion(
            id="num_1",
            type=AssertionType.NUMERIC,
            text="Marketing spend variance $50,000",
            value=Decimal("50000"),
            evidence_ids=["variance:acct_4010", "gl:acct_4010"],
            support_level=SupportLevel.VERIFIED,
        )
        evidence = _evidence()[:2]
        first = score_assertion(assertion, evidence, Decimal("1000"))
        second = score_assertion(assertion, evidence, Decimal("1000"))
        assert first == second
        assert Decimal("0") <= first <= Decimal("1")

    def test_materiality_factor(self) -> None:
        assert materiality_factor(Decimal("50000"), Decimal("1000")) == Decimal("1")
        assert materiality_factor(Decimal("100"), Decimal("1000")) == Decimal("0.1")
        assert materiality_factor(None, Decimal("1000")) == Decimal("0.5")

    def test_agreement_score(self) -> None:
        agreeing = [
            EvidenceItem(
                claim="a",
                source_type="gl",
                source_id="1",
                source_value=Decimal("10"),
                confidence="high",
            ),
            EvidenceItem(
                claim="b",
                source_type="variance",
                source_id="2",
                source_value=Decimal("10"),
                confidence="high",
            ),
        ]
        assert agreement_score(agreeing) == Decimal("1")

        disagreeing = [
            EvidenceItem(
                claim="a",
                source_type="gl",
                source_id="1",
                source_value=Decimal("10"),
                confidence="high",
            ),
            EvidenceItem(
                claim="b",
                source_type="variance",
                source_id="2",
                source_value=Decimal("20"),
                confidence="high",
            ),
        ]
        assert agreement_score(disagreeing) == Decimal("0.5")

        # 2 items agree out of 3 -> 2/3, not 2/2 (regression guard for the
        # distinct-value-count bug that returned 2.0 for two agreeing items).
        majority = [
            EvidenceItem(
                claim="a",
                source_type="gl",
                source_id="1",
                source_value=Decimal("10"),
                confidence="high",
            ),
            EvidenceItem(
                claim="b",
                source_type="variance",
                source_id="2",
                source_value=Decimal("10"),
                confidence="high",
            ),
            EvidenceItem(
                claim="c",
                source_type="driver",
                source_id="3",
                source_value=Decimal("20"),
                confidence="medium",
            ),
        ]
        assert agreement_score(majority) == Decimal("2") / Decimal("3")
