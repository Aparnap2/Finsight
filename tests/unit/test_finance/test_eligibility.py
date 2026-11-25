"""Unit tests for CP3 eligibility determination."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from finance.reconciliation.context import (
    EligibilityDecision,
    EligibilityStatus,
    ExceptionContext,
    ExceptionDiagnostic,
    RuleResult,
    RuleStatus,
)
from finance.reconciliation.diagnostics import determine_eligibility


def _context(evidence_refs: list[str] | None = None) -> ExceptionContext:
    return ExceptionContext(
        exception_id="exc-1",
        exception_code="I-FEE-DRIFT",
        severity="HIGH",
        title="Fee drift",
        description="desc",
        currency="USD",
        expected_net="971.00",
        actual_deposit="960.00",
        variance="11.00",
        tolerance="5.00",
        calculations={"captured": "1000.00", "fees": "29.00"},
        evidence_refs=evidence_refs if evidence_refs is not None else ["ev-1"],
        evidence=[{"type": "invoice", "record_id": "inv-1"}],
        investigation_eligible=bool(evidence_refs if evidence_refs is not None else ["ev-1"]),
    )


def _diagnostic(
    *,
    evidence_refs: list[str] | None = None,
    rule_results: list[RuleResult] | None = None,
    investigation_eligible: bool | None = None,
) -> ExceptionDiagnostic:
    ctx = _context(evidence_refs if evidence_refs is not None else ["ev-1"])
    if investigation_eligible is not None:
        ctx = ctx.model_copy(update={"investigation_eligible": investigation_eligible})
    rr = (
        rule_results
        if rule_results is not None
        else [
            RuleResult(rule_id="EVIDENCE_COMPLETENESS", status=RuleStatus.PASS),
            RuleResult(rule_id="RUN_MATCH_INTEGRITY", status=RuleStatus.PASS),
            RuleResult(rule_id="CALCULATION_CONSISTENCY", status=RuleStatus.PASS),
            RuleResult(rule_id="DUPLICATE_DETECTION", status=RuleStatus.PASS),
            RuleResult(rule_id="PAYOUT_VARIANCE", status=RuleStatus.FAIL),
        ]
    )
    return ExceptionDiagnostic(
        run_id="run-1",
        exception_id="exc-1",
        tenant_id="t-1",
        snapshot_id="snap-1",
        engine_version="1.0.0",
        context=ctx,
        rule_results=rr,
        query_count=4,
    )


def test_eligible_when_evidence_and_integrity_ok() -> None:
    d = _diagnostic()
    dec = determine_eligibility(d)
    assert dec.status == EligibilityStatus.ELIGIBLE
    assert dec.evidence_complete is True
    assert dec.integrity_ok is True
    assert dec.ambiguous is False


def test_ineligible_when_no_evidence() -> None:
    d = _diagnostic(evidence_refs=[])
    dec = determine_eligibility(d)
    assert dec.status == EligibilityStatus.INELIGIBLE
    assert dec.evidence_complete is False
    # cannot be eligible
    assert dec.status != EligibilityStatus.ELIGIBLE


def test_blocked_when_integrity_fails() -> None:
    rules = [
        RuleResult(rule_id="EVIDENCE_COMPLETENESS", status=RuleStatus.PASS),
        RuleResult(rule_id="RUN_MATCH_INTEGRITY", status=RuleStatus.FAIL),
        RuleResult(rule_id="CALCULATION_CONSISTENCY", status=RuleStatus.PASS),
        RuleResult(rule_id="DUPLICATE_DETECTION", status=RuleStatus.PASS),
    ]
    d = _diagnostic(rule_results=rules)
    dec = determine_eligibility(d)
    assert dec.status == EligibilityStatus.BLOCKED
    assert dec.integrity_ok is False
    assert "RUN_MATCH_INTEGRITY" in dec.rule_ids


def test_blocked_when_calculation_inconsistent() -> None:
    rules = [
        RuleResult(rule_id="EVIDENCE_COMPLETENESS", status=RuleStatus.PASS),
        RuleResult(rule_id="RUN_MATCH_INTEGRITY", status=RuleStatus.PASS),
        RuleResult(rule_id="CALCULATION_CONSISTENCY", status=RuleStatus.FAIL),
        RuleResult(rule_id="DUPLICATE_DETECTION", status=RuleStatus.PASS),
    ]
    d = _diagnostic(rule_results=rules)
    dec = determine_eligibility(d)
    assert dec.status == EligibilityStatus.BLOCKED


def test_review_required_on_duplicate() -> None:
    rules = [
        RuleResult(rule_id="EVIDENCE_COMPLETENESS", status=RuleStatus.PASS),
        RuleResult(rule_id="RUN_MATCH_INTEGRITY", status=RuleStatus.PASS),
        RuleResult(rule_id="CALCULATION_CONSISTENCY", status=RuleStatus.PASS),
        RuleResult(rule_id="DUPLICATE_DETECTION", status=RuleStatus.FAIL),
    ]
    d = _diagnostic(rule_results=rules)
    dec = determine_eligibility(d)
    assert dec.status == EligibilityStatus.REVIEW_REQUIRED
    assert dec.ambiguous is True


def test_nonclosing_match_does_not_force_review() -> None:
    # A match that did not close cleanly is a normal discrepancy, not an
    # ambiguity; it must not flip eligibility to REVIEW_REQUIRED.
    rules = [
        RuleResult(rule_id="EVIDENCE_COMPLETENESS", status=RuleStatus.PASS),
        RuleResult(rule_id="RUN_MATCH_INTEGRITY", status=RuleStatus.WARNING),
        RuleResult(rule_id="CALCULATION_CONSISTENCY", status=RuleStatus.PASS),
        RuleResult(rule_id="DUPLICATE_DETECTION", status=RuleStatus.PASS),
    ]
    d = _diagnostic(rule_results=rules)
    dec = determine_eligibility(d)
    assert dec.status == EligibilityStatus.ELIGIBLE


def test_precedence_ineligible_over_blocked() -> None:
    rules = [
        RuleResult(rule_id="EVIDENCE_COMPLETENESS", status=RuleStatus.FAIL),
        RuleResult(rule_id="RUN_MATCH_INTEGRITY", status=RuleStatus.FAIL),
    ]
    d = _diagnostic(evidence_refs=[], rule_results=rules)
    dec = determine_eligibility(d)
    assert dec.status == EligibilityStatus.INELIGIBLE


def test_deterministic() -> None:
    d = _diagnostic()
    a = determine_eligibility(d)
    b = determine_eligibility(d)
    assert a == b


def test_does_not_mutate_diagnostic() -> None:
    d = _diagnostic()
    before = d.model_dump_json()
    _ = determine_eligibility(d)
    assert d.model_dump_json() == before


def test_eligibility_decision_frozen() -> None:
    dec = EligibilityDecision(
        status=EligibilityStatus.ELIGIBLE,
        reason="ok",
        evidence_complete=True,
        integrity_ok=True,
        ambiguous=False,
    )
    with pytest.raises(ValidationError):
        dec.status = EligibilityStatus.BLOCKED  # type: ignore[misc]


def test_eligibility_decision_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        EligibilityDecision(
            status=EligibilityStatus.ELIGIBLE,
            reason="ok",
            evidence_complete=True,
            integrity_ok=True,
            ambiguous=False,
            noise=1,  # type: ignore[call-arg]
        )
