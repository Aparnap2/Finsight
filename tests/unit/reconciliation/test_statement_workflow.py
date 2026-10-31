"""Acceptance tests for the three-source statement workflow.

``finance.reconciliation.statement_workflow`` composes the frozen core into the
invoice -> charge -> deposit triangle. These tests drive it with the canonical
fixture and assert both the composition rules and the fixture's recorded
expectations.

Every check in ``expected.json`` is accounted for exactly once: either it is
composed here (``_COVERED``), or it belongs to a surface this workflow does not
claim and is asserted in its own test (``_NOT_COMPOSED``). Adding a check
without classifying it fails ``test_every_expected_check_is_accounted_for``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest

from finance.reconciliation.allocation import PayoutReason
from finance.reconciliation.bank import BankStatementMapping
from finance.reconciliation.errors import (
    CurrencyMismatch,
    InvariantViolation,
    TenantIsolationError,
)
from finance.reconciliation.models import ExceptionCode, PayoutOutcome
from finance.reconciliation.statement_workflow import (
    DepositResult,
    ReconciliationReport,
    StatementSources,
    main,
    run_statement_reconciliation,
    sources_from_export,
)
from finance.reconciliation.tolerances import ReconciliationTolerance

_FIXTURES = (
    Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "reconciliation" / "triangle"
)
_CASES = _FIXTURES / "cases.json"
_EXPECTED = _FIXTURES / "expected.json"
_DOCUMENT: dict[str, Any] = json.loads(_CASES.read_text(encoding="utf-8"))
_EXPECTATIONS: dict[str, Any] = json.loads(_EXPECTED.read_text(encoding="utf-8"))
_SCENARIOS: Mapping[str, Any] = _DOCUMENT["scenarios"]
_CHECKS: Mapping[str, Any] = _EXPECTATIONS["checks"]
_TENANT = str(_DOCUMENT["tenant_id"])
_CURRENCY = str(_DOCUMENT["currency"])
_DIGEST = "d" * 64
_STRICT = ReconciliationTolerance()
_WINDOW_72H = 72 * 60 * 60


def _sources(name: str, *, window_seconds: int | None = None) -> StatementSources:
    return sources_from_export(
        _SCENARIOS[name],
        tenant_id=_TENANT,
        currency=_CURRENCY,
        tolerance=_STRICT,
        statement_digest=_DIGEST,
        window_seconds=window_seconds,
    )


def _run(name: str, *, window_seconds: int | None = None) -> ReconciliationReport:
    return run_statement_reconciliation(_sources(name, window_seconds=window_seconds))


def _only_deposit(report: ReconciliationReport) -> DepositResult:
    assert len(report.deposits) == 1
    return report.deposits[0]


def _money(value: object) -> str:
    assert isinstance(value, Decimal)
    return str(value)


def _outcome(name: str, window: int | None = None) -> str:
    return _only_deposit(_run(name, window_seconds=window)).allocation.outcome.value


# --- resolutions of the fixture's recorded checks -------------------------


def _s1(report: ReconciliationReport) -> dict[str, object]:
    deposit = _only_deposit(report)
    return {
        "outcome": deposit.allocation.outcome.value,
        "exception_code": deposit.allocation.exception_code,
        "difference": _money(deposit.allocation.open_balance),
    }


def _s2_invoice_charge(report: ReconciliationReport) -> dict[str, object]:
    assert len(report.links) == 1
    link = report.links[0]
    return {
        "outcome": link.result.outcome.value,
        "exception_code": link.result.exception_code,
        "difference": _money(link.difference),
    }


def _s2_charge_bank(report: ReconciliationReport) -> dict[str, object]:
    deposit = _only_deposit(report)
    return {
        "outcome": deposit.allocation.outcome.value,
        "exception_code": deposit.allocation.exception_code,
        "difference": _money(deposit.allocation.open_balance),
    }


def _s2_enriched(report: ReconciliationReport) -> dict[str, object]:
    link = report.links[0]
    return {
        "outcome": link.result.outcome.value,
        "exception_code": link.result.exception_code,
        "difference": _money(link.difference),
    }


def _s3(report: ReconciliationReport) -> dict[str, object]:
    deposit = _only_deposit(report)
    return {
        "outcome": deposit.allocation.outcome.value,
        "exception_code": deposit.allocation.exception_code,
        "difference": _money(deposit.allocation.open_balance),
        "allocated_total": _money(deposit.allocation.allocated_total),
        "open_balance": _money(deposit.allocation.open_balance),
    }


def _s4a(report: ReconciliationReport) -> dict[str, object]:
    deposit = _only_deposit(report)
    return {
        "outcome": deposit.allocation.outcome.value,
        "exception_code": deposit.allocation.exception_code,
        "difference": _money(deposit.allocation.open_balance),
    }


def _s5(report: ReconciliationReport) -> dict[str, object]:
    deposit = _only_deposit(report)
    return {
        "outcome": deposit.allocation.outcome.value,
        "exception_code": deposit.allocation.exception_code,
        "difference": _money(deposit.allocation.open_balance),
    }


def _s6_drifted(report: ReconciliationReport) -> dict[str, object]:
    deposit = _only_deposit(report)
    assert deposit.comparison is not None
    return {
        "outcome": deposit.allocation.outcome.value,
        "exception_code": (
            None
            if deposit.allocation.exception_code is None
            else deposit.allocation.exception_code.value
        ),
        "difference": _money(deposit.comparison.difference),
    }


def _s7(report: ReconciliationReport) -> dict[str, object]:
    deposit = _only_deposit(report)
    candidates = [list(candidate.payment_ids) for candidate in deposit.allocation.candidates]
    return {
        "outcome": deposit.allocation.outcome.value,
        "exception_code": deposit.allocation.exception_code,
        "reason": (None if deposit.allocation.reason is None else deposit.allocation.reason.value),
        "candidates": candidates,
    }


_COVERED: dict[str, tuple[str, Callable[[ReconciliationReport], dict[str, object]]]] = {
    "s1_exact_match": ("s1_exact_match", _s1),
    "s2_fee_invoice_vs_charge": ("s2_fee_explained", _s2_invoice_charge),
    "s2_fee_charge_vs_bank": ("s2_fee_explained", _s2_charge_bank),
    "s2_fee_invoice_vs_enriched_bank": ("s2_fee_explained", _s2_enriched),
    "s3_many_to_one": ("s3_many_to_one", _s3),
    "s4a_refund_folded": ("s4a_refund_folded", _s4a),
    "s5_delayed_deposit": ("s5_delayed", _s5),
    "s6_duplicate_drifted": ("s6_duplicate", _s6_drifted),
    "s7_ambiguous_allocation": ("s7_ambiguous_allocation", _s7),
}

# Checks that describe a surface this workflow deliberately does not compose.
# Each is asserted by the named test instead of being silently dropped.
_NOT_COMPOSED: dict[str, str] = {
    "s2_fee_invoice_vs_naive_bank": "test_naive_bank_comparison_is_reported_as_derived_only",
    "s4b_partial_payment": "test_s4b_deposit_without_processor_legs_is_pending_evidence",
    "s5b_missing_deposit": "test_s5b_missing_bank_evidence_is_not_synthesized",
    "s6_duplicate_bank_row": "test_s6_exact_duplicate_rows_are_reported_but_not_double_allocated",
}

_COMPARED_FIELDS = (
    "outcome",
    "exception_code",
    "difference",
    "allocated_total",
    "open_balance",
    "reason",
    "candidates",
)


@pytest.mark.parametrize("name", sorted(_SCENARIOS))
def test_every_fixture_scenario_runs(name: str) -> None:
    report = _run(name)
    payload = report.to_dict()
    assert json.loads(json.dumps(payload)) == payload
    assert len(report.fingerprint) == 64


@pytest.mark.parametrize("check", sorted(_COVERED))
def test_composed_fixture_check_matches_recorded_expectation(check: str) -> None:
    expected = _CHECKS[check]
    assert expected["supported"] is True
    scenario, resolver = _COVERED[check]
    observed = resolver(_run(scenario))
    for field in _COMPARED_FIELDS:
        if field not in expected or expected[field] is None:
            continue
        assert observed[field] == expected[field], f"{check}.{field}"


def test_every_expected_check_is_accounted_for() -> None:
    assert set(_CHECKS) == set(_COVERED) | set(_NOT_COMPOSED)
    for check, test_name in _NOT_COMPOSED.items():
        entry = _CHECKS[check]
        assert entry["supported"] is False or "gap" in entry or "surface" in entry
        assert callable(globals()[test_name])


def test_s2_fee_difference_appears_on_both_edges_and_the_derived_view() -> None:
    report = _run("s2_fee_explained")
    link = report.links[0]
    deposit = _only_deposit(report)
    assert link.difference == Decimal("-29.00")
    assert deposit.allocation.outcome is PayoutOutcome.MATCHED
    assert deposit.allocation.allocated_total == Decimal("971.00")
    assert deposit.comparison is not None
    assert deposit.comparison.difference == Decimal("-29.00")


def test_s3_many_to_one_allocates_every_charge_once() -> None:
    report = _run("s3_many_to_one")
    deposit = _only_deposit(report)
    assert [leg.payment_id for leg in deposit.allocation.legs] == [
        "ch_2001",
        "ch_2002",
        "ch_2003",
    ]
    assert deposit.allocation.allocated_total == Decimal("970.00")
    assert deposit.comparison is not None
    assert deposit.comparison.invoice_ids == ("INV-2001", "INV-2002", "INV-2003")
    assert deposit.comparison.difference == Decimal("-30.00")


def test_s4a_refund_is_folded_into_the_allocated_net() -> None:
    deposit = _only_deposit(_run("s4a_refund_folded"))
    assert deposit.allocation.outcome is PayoutOutcome.MATCHED
    assert deposit.allocation.allocated_total == Decimal("571.00")
    assert deposit.allocation.refund_total == Decimal("400.00")


def test_s4b_deposit_without_processor_legs_is_pending_evidence() -> None:
    report = _run("s4b_partial_payment")
    deposit = _only_deposit(report)
    allocation = deposit.allocation
    assert report.links == ()
    assert report.unlinked_invoices == ("INV-1005",)
    assert allocation.outcome is PayoutOutcome.PENDING_EVIDENCE
    assert allocation.reason is PayoutReason.NO_CANDIDATE
    assert allocation.exception_code is None
    assert allocation.legs == ()
    assert allocation.candidates == ()
    assert allocation.allocated_total == Decimal("0.00")
    assert allocation.unallocated_deposit == Decimal("600.00")
    assert deposit.comparison is None
    assert any("pending evidence" in warning for warning in report.warnings)


def test_naive_bank_comparison_is_reported_as_derived_only() -> None:
    expected = _CHECKS["s2_fee_invoice_vs_naive_bank"]
    assert expected["supported"] is False
    report = _run("s2_fee_explained")
    deposit = _only_deposit(report)
    assert deposit.comparison is not None
    assert _money(deposit.comparison.difference) == expected["difference"]
    assert expected["gap"]


def test_s5b_missing_bank_evidence_is_not_synthesized() -> None:
    expected = _CHECKS["s5b_missing_deposit"]
    assert expected["outcome"] == "PENDING_EVIDENCE"
    report = _run("s5b_missing_deposit")
    assert report.deposits == ()
    assert any("no bank evidence" in warning for warning in report.warnings)
    assert len(report.links) == 1


@pytest.mark.parametrize(
    ("window_seconds", "expected_outcome", "expected_reason"),
    [
        (_WINDOW_72H, PayoutOutcome.MATCHED, None),
        (60 * 60, PayoutOutcome.PENDING_EVIDENCE, PayoutReason.OUTSIDE_WINDOW),
    ],
)
def test_s5_delayed_deposit_respects_the_window(
    window_seconds: int,
    expected_outcome: PayoutOutcome,
    expected_reason: PayoutReason | None,
) -> None:
    deposit = _only_deposit(_run("s5_delayed", window_seconds=window_seconds))
    assert deposit.allocation.outcome is expected_outcome
    assert deposit.allocation.reason is expected_reason


def test_s6_exact_duplicate_rows_are_reported_but_not_double_allocated() -> None:
    expected = _CHECKS["s6_duplicate_bank_row"]
    assert expected["gap"]
    report = _run("s6_duplicate")
    assert len(report.duplicate_groups) == 1
    exact = report.duplicate_groups[0]
    assert [item.line_number for item in exact] == [2, 3]
    assert len(report.deposits) == 1
    assert len(_only_deposit(report).allocation.legs) == 1


def test_s6_drifted_duplicate_is_flagged_before_partial() -> None:
    report = _run("s6_duplicate")
    deposit = _only_deposit(report)
    allocation = deposit.allocation
    assert deposit.duplicate is True
    assert [item.line_number for item in deposit.evidence] == [2, 4]
    assert len(report.drift_groups) == 1
    assert allocation.outcome is PayoutOutcome.EXCEPTION
    assert allocation.reason is PayoutReason.DUPLICATE
    assert allocation.exception_code is ExceptionCode.DUPLICATE_LEDGER_ENTRY
    assert allocation.allocated_total == Decimal("148.00")
    assert allocation.open_balance == Decimal("2.00")
    assert allocation.unallocated_deposit == Decimal("0.00")
    assert deposit.comparison is not None
    assert deposit.comparison.difference == Decimal("-2.00")


def test_s7_ambiguity_refuses_to_guess() -> None:
    report = _run("s7_ambiguous_allocation")
    deposit = _only_deposit(report)
    allocation = deposit.allocation
    assert allocation.outcome is PayoutOutcome.REQUIRES_HUMAN
    assert allocation.reason is PayoutReason.AMBIGUOUS
    assert allocation.exception_code is None
    assert len(allocation.candidates) == 2
    assert allocation.allocated_total == Decimal("0.00")
    assert allocation.unallocated_deposit == Decimal("970.00")
    assert allocation.open_balance == Decimal("1940.00")
    assert report.unlinked_charges == ("ch_3004",)


def test_report_is_deterministic_across_runs() -> None:
    first = _run("s6_duplicate").to_dict()
    second = _run("s6_duplicate").to_dict()
    assert first == second


def test_tenant_isolation_is_enforced() -> None:
    sources = _sources("s1_exact_match")
    foreign = replace(sources.invoices[0], tenant_id="tenant-other")
    with pytest.raises(TenantIsolationError):
        run_statement_reconciliation(replace(sources, invoices=(foreign,)))


def test_currency_mismatch_is_enforced_on_legs_and_mapping() -> None:
    sources = _sources("s1_exact_match")
    foreign = replace(sources.charges[0], currency="EUR")
    with pytest.raises(CurrencyMismatch):
        run_statement_reconciliation(replace(sources, charges=(foreign,)))
    with pytest.raises(CurrencyMismatch):
        run_statement_reconciliation(
            replace(sources, mapping=BankStatementMapping(statement_currency="EUR"))
        )


def test_malformed_bank_row_is_rejected_without_failing_the_run() -> None:
    sources = _sources("s1_exact_match")
    bad: dict[str, Any] = {
        "deposit_id": "not-a-decimal",
        "amount": "not-a-decimal",
        "posted_at": "2026-01-24",
    }
    report = run_statement_reconciliation(replace(sources, bank_rows=(*sources.bank_rows, bad)))
    assert report.rejects
    assert report.rejects[0][0] == 3
    assert len(report.deposits) == 1


def test_window_seconds_must_be_non_negative() -> None:
    with pytest.raises(InvariantViolation):
        _sources("s1_exact_match", window_seconds=-1)


def test_statement_sources_reject_foreign_row_types() -> None:
    sources = _sources("s1_exact_match")
    with pytest.raises(InvariantViolation):
        run_statement_reconciliation(replace(sources, bank_rows=cast(Any, "not-a-sequence")))


def test_cli_writes_the_report(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    exit_code = main(
        [
            "--cases",
            str(_CASES),
            "--scenario",
            "s4b_partial_payment",
            "--scenario",
            "s6_duplicate",
            "--out",
            str(out),
        ]
    )
    assert exit_code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert set(payload) == {"s4b_partial_payment", "s6_duplicate"}
    assert (
        payload["s4b_partial_payment"]["edges"]["charge_to_deposit"]["results"][0][
            "unallocated_deposit"
        ]
        == "600.00"
    )
    assert (
        payload["s6_duplicate"]["edges"]["charge_to_deposit"]["results"][0]["exception_code"]
        == "I-DUPLICATE"
    )


def test_statement_line_is_the_deposit_identity() -> None:
    entry = _SCENARIOS["s1_exact_match"]["bank"][0]
    rows = _sources("s1_exact_match").bank_rows
    assert rows[0]["deposit_id"] == entry["source_reference"]
    deposit = _only_deposit(_run("s1_exact_match"))
    assert deposit.deposit_id == entry["source_reference"]
    assert deposit.evidence[0].statement_reference == f"{_DIGEST}:2"
    assert deposit.evidence[0].amount == Decimal(str(entry["gross"]))


def test_outcome_and_reason_names_are_stable() -> None:
    assert _outcome("s1_exact_match") == "MATCHED"
    assert _outcome("s6_duplicate") == "EXCEPTION"
    assert _outcome("s7_ambiguous_allocation") == "REQUIRES_HUMAN"
