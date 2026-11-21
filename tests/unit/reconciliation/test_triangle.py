"""Acceptance tests for the three-source (invoice + Stripe + bank) triangle.

The fixture under ``tests/fixtures/reconciliation/triangle/`` drives the
frozen P1 core through a small business scenario: a Google Sheets
invoice register holds what we expect to be paid, Stripe holds what was
charged and refunded, and a bank statement holds what actually landed.
No production code is modified here; the module records what the core
does today.

Scenarios marked ``supported`` assert the core's current behaviour.
Scenarios marked ``gap`` in ``expected.json`` record behaviour the
triangle still cannot express. The payout checks that used to be strict
xfails (s3, s5b, s7) now run against the ``reconcile_payout`` contract;
s4b remains a gap only for the pairwise ``reconcile`` surface, which the
payout surface supersedes for payouts.

Checks covered:

======================================  ==========  ==========================
check                                   supported   what it proves
======================================  ==========  ==========================
s1_exact_match                          yes         a clean leg closes as MATCHED
s2_fee_invoice_vs_charge                yes         fee drift is I-FEE-DRIFT
s2_fee_charge_vs_bank                   yes         fees are already inside net
s2_fee_invoice_vs_naive_bank            gap         bank row has no fee column
s2_fee_invoice_vs_enriched_bank         yes         fee knowledge fixes the code
s3_many_to_one                          yes         N charges -> 1 deposit
s4a_refund_folded                       yes         refunds folded into net match
s4b_partial_payment                     gap         pairwise surface has no partial code
s5_delayed_deposit                      yes         time skew via window_seconds
s5b_missing_deposit                     yes         absence is PENDING_EVIDENCE
s6_duplicate_bank_row                   yes         dedup must precede reconcile
s6_duplicate_drifted                    yes         duplicate flag on drift
s7_ambiguous_allocation                 yes         two fits -> REQUIRES_HUMAN
======================================  ==========  ==========================
"""

import json
import logging
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from finance.reconciliation import (
    BankDepositRecord,
    ExceptionCode,
    PaymentRecord,
    PayoutOutcome,
    PayoutReason,
    ReconciliationOutcome,
    ReconciliationTolerance,
    ensure_unique,
    find_duplicates,
    find_match,
    fingerprint_payment,
    normalize,
    reconcile,
    reconcile_payout,
)
from finance.reconciliation.errors import DuplicateError

logger = logging.getLogger(__name__)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "reconciliation" / "triangle"
CASES: dict[str, Any] = json.loads((FIXTURES / "cases.json").read_text(encoding="utf-8"))
EXPECTED: dict[str, Any] = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))[
    "checks"
]
SCENARIOS: dict[str, dict[str, Any]] = CASES["scenarios"]
TENANT = CASES["tenant_id"]
STRICT = ReconciliationTolerance()


def _scenario(name: str) -> dict[str, Any]:
    """Return one scenario block from ``cases.json``."""
    return SCENARIOS[name]


def _legs(name: str, source: str) -> list[PaymentRecord]:
    """Normalize every raw record of one source in one scenario."""
    return [normalize(record, tenant_id=TENANT) for record in _scenario(name)[source]]


def _leg(name: str, source: str, payment_id: str) -> PaymentRecord:
    """Normalize the record of ``source`` with the given ``payment_id``."""
    for record in _scenario(name)[source]:
        if record["payment_id"] == payment_id:
            return normalize(record, tenant_id=TENANT)
    raise AssertionError(f"{name}/{source} has no record {payment_id!r}")


def _deposit_from_leg(leg: PaymentRecord) -> BankDepositRecord:
    """Treat one normalized bank leg as a normalized deposit record."""
    return BankDepositRecord(
        deposit_id=leg.payment_id,
        tenant_id=leg.tenant_id,
        amount=leg.net,
        currency=leg.currency,
        posted_at=leg.occurred_at,
        statement_digest=fingerprint_payment(leg),
        line_number=2,
        fee=leg.fee,
        reference=leg.source_reference or leg.payment_id,
    )


def _assert_check(check: str, outcome: ReconciliationOutcome, code: str | None, diff: str) -> None:
    """Assert a reconcile result against the recorded expectation."""
    expected = EXPECTED[check]
    assert expected["supported"] is True, f"{check} is recorded as a gap, not a passing check"
    assert expected["outcome"] == outcome.value
    assert expected["exception_code"] == code
    assert Decimal(expected["difference"]) == Decimal(diff)


def _assert_characterization(
    check: str, outcome: ReconciliationOutcome, code: str | None, diff: str
) -> None:
    """Assert today's behaviour for a check that is recorded as a gap."""
    expected = EXPECTED[check]
    assert expected["supported"] is False, f"{check} is not a recorded gap"
    assert expected["gap"], f"{check} is marked as a gap without a reason"
    assert expected["outcome"] == outcome.value
    assert expected["exception_code"] == code
    assert Decimal(expected["difference"]) == Decimal(diff)


def _floats(node: Any) -> list[Any]:
    """Collect every JSON float in a parsed fixture tree."""
    if isinstance(node, float):
        return [node]
    if isinstance(node, dict):
        return [found for value in node.values() for found in _floats(value)]
    if isinstance(node, list):
        return [found for value in node for found in _floats(value)]
    return []


def test_fixture_money_is_never_a_float() -> None:
    """Every amount is a decimal string; a float would bypass Decimal math."""
    assert _floats(CASES) == []


def test_every_fixture_record_satisfies_the_net_invariant() -> None:
    """``normalize`` enforces net == gross - fee - refund on all records."""
    for scenario in CASES["scenarios"].values():
        for source, records in scenario.items():
            if source in ("description",):
                continue
            for record in records:
                leg = normalize(record, tenant_id=TENANT)
                assert leg.net == leg.gross - leg.fee - leg.refund


def test_s1_exact_match() -> None:
    """Invoice, charge, and deposit agree to the cent."""
    invoice = _leg("s1_exact_match", "invoice", "INV-1000")
    charge = _leg("s1_exact_match", "stripe", "ch_1000")
    deposit = _leg("s1_exact_match", "bank", "dep_1000")

    for processor, ledger in ((invoice, charge), (charge, deposit), (invoice, deposit)):
        result = reconcile(processor, ledger, STRICT)
        _assert_check(
            "s1_exact_match", result.outcome, result.exception_code, str(result.difference)
        )


def test_s2_fee_is_visible_between_invoice_and_charge() -> None:
    """A 29.00 processor fee is classified as fee drift, not a refund lag."""
    invoice = _leg("s2_fee_explained", "invoice", "INV-1001")
    charge = _leg("s2_fee_explained", "stripe", "ch_1001")

    result = reconcile(invoice, charge, STRICT)

    _assert_check(
        "s2_fee_invoice_vs_charge", result.outcome, result.exception_code, str(result.difference)
    )
    assert result.exception_code == ExceptionCode.FEE_MISMATCH.value


def test_s2_charge_and_bank_agree_because_the_fee_is_already_in_net() -> None:
    """Stripe's net already excludes the fee, so the deposit matches it."""
    charge = _leg("s2_fee_explained", "stripe", "ch_1001")
    deposit = _leg("s2_fee_explained", "bank", "dep_1001")

    result = reconcile(charge, deposit, STRICT)

    _assert_check(
        "s2_fee_charge_vs_bank", result.outcome, result.exception_code, str(result.difference)
    )


def test_s2_naive_bank_leg_misattributes_fee_drift_to_a_refund_lag() -> None:
    """Characterization of the gap: a bank row has nowhere to put the fee.

    The deposit is a single credit of 971.00. Normalizing it as its own
    ``gross`` makes the 29.00 difference a *gross* delta, and the
    classifier has no gross-only code, so it reports I-REFUND-LAG.
    """
    invoice = _leg("s2_fee_explained", "invoice", "INV-1001")
    deposit = _leg("s2_fee_explained", "bank", "dep_1001")

    result = reconcile(invoice, deposit, STRICT)

    _assert_characterization(
        "s2_fee_invoice_vs_naive_bank",
        result.outcome,
        result.exception_code,
        str(result.difference),
    )
    assert result.exception_code == ExceptionCode.PARTIAL_REFUND_ACCOUNTING_LAG.value
    assert result.exception_code != ExceptionCode.FEE_MISMATCH.value


def test_s2_enriched_bank_leg_recovers_the_fee_code() -> None:
    """Given the processor's gross and fee, the classifier is correct."""
    invoice = _leg("s2_fee_explained", "invoice", "INV-1001")
    enriched = _leg("s2_fee_explained", "bank_enriched", "dep_1001_enriched")

    result = reconcile(invoice, enriched, STRICT)

    _assert_check(
        "s2_fee_invoice_vs_enriched_bank",
        result.outcome,
        result.exception_code,
        str(result.difference),
    )


def test_s2_triangle_is_not_transitive() -> None:
    """invoice=charge and charge=deposit, yet invoice!=deposit.

    A triangle must be joined through the processor leg, not asserted
    pairwise; this is the arithmetic reason the bank leg needs the
    processor's fee rather than standing alone.
    """
    invoice = _leg("s2_fee_explained", "invoice", "INV-1001")
    charge = _leg("s2_fee_explained", "stripe", "ch_1001")
    deposit = _leg("s2_fee_explained", "bank", "dep_1001")

    assert reconcile(invoice, charge, STRICT).outcome is ReconciliationOutcome.EXCEPTION
    assert reconcile(charge, deposit, STRICT).outcome is ReconciliationOutcome.MATCHED
    assert reconcile(invoice, deposit, STRICT).outcome is ReconciliationOutcome.EXCEPTION


def test_s3_fixture_arithmetic_sums_to_the_payout() -> None:
    """388.00 + 291.00 + 291.00 is exactly the 970.00 credited."""
    charges = _legs("s3_many_to_one", "stripe")
    deposit = _legs("s3_many_to_one", "bank")[0]

    assert [charge.net for charge in charges] == [
        Decimal("388.00"),
        Decimal("291.00"),
        Decimal("291.00"),
    ]
    assert sum((charge.net for charge in charges), Decimal("0")) == deposit.net


def test_s3_each_charge_is_an_exception_against_the_payout() -> None:
    """The core can only compare a charge to the deposit one at a time."""
    charges = _legs("s3_many_to_one", "stripe")
    deposit = _legs("s3_many_to_one", "bank")[0]

    outcomes = {reconcile(charge, deposit, STRICT).outcome for charge in charges}

    assert outcomes == {ReconciliationOutcome.EXCEPTION}


def test_s3_one_deposit_reconciles_three_charges() -> None:
    """The payout contract allocates one deposit across several charges."""
    charges = _legs("s3_many_to_one", "stripe")
    deposit = _deposit_from_leg(_legs("s3_many_to_one", "bank")[0])

    result = reconcile_payout(deposit, charges, STRICT)

    expected = EXPECTED["s3_many_to_one"]
    assert result.outcome is PayoutOutcome.MATCHED
    assert result.reason is None
    assert result.exception_code is None
    assert result.allocated_total == Decimal(expected["allocated_total"])
    assert result.open_balance == Decimal(expected["open_balance"])
    assert result.unallocated_deposit == Decimal("0.00")
    assert [leg.payment_id for leg in result.legs] == ["ch_2001", "ch_2002", "ch_2003"]


def test_s4a_refund_folded_into_net_matches_the_deposit() -> None:
    """1000.00 charged, 29.00 fee, 400.00 refunded leaves 571.00."""
    charge = _leg("s4a_refund_folded", "stripe", "ch_1004")
    deposit = _leg("s4a_refund_folded", "bank", "dep_1004")

    result = reconcile(charge, deposit, STRICT)

    _assert_check(
        "s4a_refund_folded", result.outcome, result.exception_code, str(result.difference)
    )
    assert charge.refund == Decimal("400.00")


def test_s4b_underpayment_is_indistinguishable_from_a_refund_lag() -> None:
    """Characterization of the gap: 400.00 short with no refund at all."""
    invoice = _leg("s4b_partial_payment", "invoice", "INV-1005")
    deposit = _leg("s4b_partial_payment", "bank", "dep_1005")

    result = reconcile(invoice, deposit, STRICT)

    _assert_characterization(
        "s4b_partial_payment", result.outcome, result.exception_code, str(result.difference)
    )
    assert result.exception_code == ExceptionCode.PARTIAL_REFUND_ACCOUNTING_LAG.value


def test_s5_delayed_deposit_matches_when_the_time_window_allows_it() -> None:
    """A three-day settlement lag is expressible through ``find_match``."""
    charge = _leg("s5_delayed", "stripe", "ch_1006")
    deposit = _leg("s5_delayed", "bank", "dep_1006")

    assert find_match(charge, [deposit], STRICT) is deposit
    assert find_match(charge, [deposit], STRICT, window_seconds=3 * 24 * 3600) is deposit
    assert find_match(charge, [deposit], STRICT, window_seconds=3600) is None

    result = reconcile(charge, deposit, STRICT)
    _assert_check(
        "s5_delayed_deposit", result.outcome, result.exception_code, str(result.difference)
    )


def test_s5b_missing_deposit_yields_an_unmatched_expected_state() -> None:
    """An absent deposit is open evidence, not an invented leg."""
    charge = _leg("s5b_missing_deposit", "stripe", "ch_1007")
    deposits = _legs("s5b_missing_deposit", "bank")
    assert deposits == []

    result = reconcile_payout(None, [charge], STRICT)

    expected = EXPECTED["s5b_missing_deposit"]
    assert result.outcome is PayoutOutcome.PENDING_EVIDENCE
    assert result.reason is PayoutReason.NO_DEPOSIT
    assert result.exception_code is None
    assert result.open_balance == Decimal(expected["open_balance"])
    assert result.unallocated_deposit == Decimal("0.00")


def test_s6_duplicate_rows_are_grouped_by_the_dedup_layer() -> None:
    """Three imports of one bank line collapse to a single key group."""
    rows = _legs("s6_duplicate", "bank")

    groups = find_duplicates(rows)

    assert len(groups) == 1
    assert len(next(iter(groups.values()))) == 3
    with pytest.raises(DuplicateError):
        ensure_unique(rows)


def test_s6_duplicate_flag_cannot_fire_on_an_exact_match() -> None:
    """Dedup has to run before reconcile: equal nets close as MATCHED.

    ``reconcile(..., duplicate=True)`` only reaches ``classify`` after
    the tolerance check fails, so an exactly-matching duplicate is
    reported as clean. This is why the caller must dedup first.
    """
    charge = _leg("s6_duplicate", "stripe", "ch_1008")
    duplicate = _leg("s6_duplicate", "bank", "dep_1008a")

    result = reconcile(charge, duplicate, STRICT, duplicate=True)

    _assert_check(
        "s6_duplicate_bank_row", result.outcome, result.exception_code, str(result.difference)
    )
    assert result.outcome is ReconciliationOutcome.MATCHED


def test_s6_duplicate_flag_fires_when_the_duplicate_also_drifted() -> None:
    """A re-import that was edited to 148.00 is attributed to duplication."""
    charge = _leg("s6_duplicate", "stripe", "ch_1008")
    drifted = _leg("s6_duplicate", "bank", "dep_1008c")

    result = reconcile(charge, drifted, STRICT, duplicate=True)

    _assert_check(
        "s6_duplicate_drifted", result.outcome, result.exception_code, str(result.difference)
    )
    assert result.exception_code == ExceptionCode.DUPLICATE_LEDGER_ENTRY.value


def test_s7_find_match_silently_picks_one_plausible_allocation() -> None:
    """Characterization of the gap: 970.00 matches the last charge, not the sum."""
    charges = _legs("s7_ambiguous_allocation", "stripe")
    deposit = _legs("s7_ambiguous_allocation", "bank")[0]

    matched = find_match(deposit, charges, STRICT)

    assert matched is charges[-1]
    assert matched.payment_id == "ch_3004"
    assert sum((charge.net for charge in charges[:3]), Decimal("0")) == deposit.net


def test_s7_ambiguous_allocation_is_reported_as_ambiguous() -> None:
    """Refuse to choose when two allocations both balance exactly."""
    charges = _legs("s7_ambiguous_allocation", "stripe")
    deposit = _deposit_from_leg(_legs("s7_ambiguous_allocation", "bank")[0])

    result = reconcile_payout(deposit, charges, STRICT)

    expected = EXPECTED["s7_ambiguous_allocation"]
    assert result.outcome is PayoutOutcome.REQUIRES_HUMAN
    assert result.reason is PayoutReason.AMBIGUOUS
    assert result.exception_code is None
    assert result.legs == ()
    assert {candidate.payment_ids for candidate in result.candidates} == {
        tuple(candidate) for candidate in expected["candidates"]
    }


def test_gap_inventory_matches_the_recorded_expectations() -> None:
    """The fixture declares its gaps; nothing is silently passing."""
    gaps = {name for name, check in EXPECTED.items() if check["supported"] is False}

    assert gaps == {
        "s2_fee_invoice_vs_naive_bank",
        "s4b_partial_payment",
    }
    for name in gaps:
        assert EXPECTED[name]["gap"], f"{name} is marked as a gap without a reason"
