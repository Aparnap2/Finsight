"""P4 — AI investigation: evidence-grounded, bounded, non-mutating.

The LLM may explain; it cannot alter financial state. Abstention is
explicit when evidence is missing or the LLM produces no verifiable
references.
"""

from __future__ import annotations

from finance.reconciliation.investigation import (
    BoundedInvestigation,
    InvestigationContext,
)
from shared.llm.fake import FakeLLM


def _context(evidence_refs: list[str] | None = None) -> InvestigationContext:
    return InvestigationContext(
        exception_id="exc-1",
        exception_code="I-FEE-DRIFT",
        title="Fee mismatch",
        description="Stripe fee 29.00 but bank shows 0.00",
        evidence_refs=evidence_refs or [],
        match_summary="INV-1 vs ch_1: 1000.00 vs 1000.00",
        allocation_summary="dep_1: allocated 971.00",
    )


class TestBoundedInvestigation:
    def test_abstains_when_no_evidence_refs(self) -> None:
        provider = FakeLLM()
        inv = BoundedInvestigation(provider)
        finding = inv.investigate(_context([]))
        assert finding.abstained is True
        assert finding.confidence == "low"
        assert (
            "insufficient" in finding.claim.lower()
            or "no evidence" in (finding.abstention_reason or "").lower()
        )

    def test_returns_structured_finding_with_evidence(self) -> None:
        provider = FakeLLM(
            scripted={
                "InvestigationFinding": {
                    "claim": "Fee discrepancy due to timing.",
                    "evidence_refs": ["evt_1", "dep_1"],
                    "confidence": "medium",
                    "abstained": False,
                }
            }
        )
        inv = BoundedInvestigation(provider)
        finding = inv.investigate(_context(["evt_1", "dep_1"]))
        assert finding.abstained is False
        assert finding.claim == "Fee discrepancy due to timing."
        assert finding.evidence_refs == ["evt_1", "dep_1"]
        assert finding.confidence == "medium"

    def test_abstains_when_llm_produces_no_evidence_refs(self) -> None:
        provider = FakeLLM(
            scripted={
                "InvestigationFinding": {
                    "claim": "Probably a timing issue.",
                    "evidence_refs": [],
                    "confidence": "high",
                    "abstained": False,
                }
            }
        )
        inv = BoundedInvestigation(provider)
        finding = inv.investigate(_context(["evt_1"]))
        assert finding.abstained is True
        assert "evidence references" in (finding.abstention_reason or "").lower()

    def test_abstains_on_provider_failure(self) -> None:
        provider = FakeLLM(fail_all=RuntimeError("provider down"))
        inv = BoundedInvestigation(provider)
        finding = inv.investigate(_context(["evt_1"]))
        assert finding.abstained is True
        assert "provider error" in (finding.abstention_reason or "").lower()

    def test_does_not_mutate_input_context(self) -> None:
        ctx = _context(["evt_1"])
        original_refs = list(ctx.evidence_refs)
        provider = FakeLLM(
            scripted={
                "InvestigationFinding": {
                    "claim": "ok",
                    "evidence_refs": ["evt_1"],
                    "confidence": "low",
                    "abstained": False,
                }
            }
        )
        inv = BoundedInvestigation(provider)
        inv.investigate(ctx)
        assert ctx.evidence_refs == original_refs

    def test_unknown_fields_rejected(self) -> None:
        provider = FakeLLM(
            scripted={
                "InvestigationFinding": {
                    "claim": "ok",
                    "evidence_refs": ["evt_1"],
                    "confidence": "low",
                    "abstained": False,
                    "invented_field": "bad",
                }
            }
        )
        inv = BoundedInvestigation(provider)
        finding = inv.investigate(_context(["evt_1"]))
        # SchemaMismatchError is caught and becomes abstention
        assert finding.abstained is True
