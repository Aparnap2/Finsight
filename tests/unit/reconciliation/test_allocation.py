"""Deposit allocation: whole-charge subsets, partial settlement, ambiguity.

Covers the spec's payout outcomes end to end: exact fit (many-to-one),
tolerance match, single-charge partial settlement, missing/out-of-window
deposit evidence, ambiguity that refuses to guess, duplicate re-ingest,
refund lag, fee drift, unexplained over-deposit, and the tenant/currency
isolation guarantees.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from finance.reconciliation.allocation import (
    Allocation,
    AllocationLeg,
    PayoutReason,
    allocate_deposit,
    reconcile_payout,
)
from finance.reconciliation.bank import BankDepositRecord
from finance.reconciliation.errors import (
    CurrencyMismatch,
    InvariantViolation,
    TenantIsolationError,
)
from finance.reconciliation.fingerprints import fingerprint_payment
from finance.reconciliation.models import ExceptionCode, PaymentRecord, PaymentStatus, PayoutOutcome
from finance.reconciliation.tolerances import ReconciliationTolerance

_AT = datetime(2026, 5, 2, 10, 0, 0, tzinfo=UTC)
_DIGEST = "c" * 64
_TENANT = "tenant-acme"
_STRICT = ReconciliationTolerance()


def _charge(
    payment_id: str,
    *,
    gross: str,
    fee: str = "0.00",
    refund: str = "0.00",
    net: str | None = None,
    currency: str = "USD",
    tenant_id: str = _TENANT,
    occurred_at: datetime = _AT,
) -> PaymentRecord:
    """Build one settled charge with Decimal-only money."""
    gross_value = Decimal(gross)
    fee_value = Decimal(fee)
    refund_value = Decimal(refund)
    return PaymentRecord(
        payment_id=payment_id,
        provider="stripe",
        provider_event_id=f"evt-{payment_id}",
        idempotency_key=f"key-{payment_id}",
        gross=gross_value,
        fee=fee_value,
        refund=refund_value,
        net=Decimal(net) if net is not None else gross_value - fee_value - refund_value,
        currency=currency,
        status=PaymentStatus.SETTLED,
        occurred_at=occurred_at,
        tenant_id=tenant_id,
    )


def _deposit(
    amount: str,
    *,
    currency: str = "USD",
    tenant_id: str = _TENANT,
    fee: str = "0.00",
    posted_at: datetime = _AT + timedelta(hours=1),
) -> BankDepositRecord:
    """Build one bank deposit whose amount is the credited net."""
    return BankDepositRecord(
        deposit_id="dep_1",
        tenant_id=tenant_id,
        amount=Decimal(amount),
        currency=currency,
        posted_at=posted_at,
        statement_digest=_DIGEST,
        line_number=2,
        fee=Decimal(fee),
        reference="payout-1",
    )


class TestWholeChargeAllocation:
    """A deposit may settle one or several whole charges."""

    def test_many_to_one_exact_fit(self) -> None:
        charges = [
            _charge("ch_1", gross="400.00", fee="12.00"),
            _charge("ch_2", gross="300.00", fee="9.00"),
            _charge("ch_3", gross="300.00", fee="9.00"),
        ]
        result = allocate_deposit(_deposit("970.00"), charges, _STRICT)
        assert result.outcome is PayoutOutcome.MATCHED
        assert result.reason is None
        assert result.exception_code is None
        assert result.allocated_total == Decimal("970.00")
        assert result.open_balance == Decimal("0.00")
        assert result.unallocated_deposit == Decimal("0.00")
        assert result.fee_total == Decimal("30.00")
        assert tuple(leg.payment_id for leg in result.legs) == ("ch_1", "ch_2", "ch_3")
        assert all(leg.allocated == leg.net for leg in result.legs)

    def test_input_order_does_not_change_the_result(self) -> None:
        charges = [
            _charge("ch_1", gross="400.00", fee="12.00"),
            _charge("ch_2", gross="300.00", fee="9.00"),
            _charge("ch_3", gross="300.00", fee="9.00"),
        ]
        forward = allocate_deposit(_deposit("970.00"), charges, _STRICT)
        backward = allocate_deposit(_deposit("970.00"), list(reversed(charges)), _STRICT)
        assert forward.fingerprint == backward.fingerprint
        assert forward.legs == backward.legs
        assert [leg.payment_id for leg in backward.legs] == ["ch_1", "ch_2", "ch_3"]

    def test_tolerance_match_absorbs_small_difference(self) -> None:
        tolerance = ReconciliationTolerance(absolute=Decimal("0.01"))
        result = allocate_deposit(
            _deposit("1000.01"), [_charge("ch_1", gross="1000.00")], tolerance
        )
        assert result.outcome is PayoutOutcome.TOLERANCE_MATCHED
        assert result.allocated_total == Decimal("1000.00")
        assert result.unallocated_deposit == Decimal("0.01")


class TestPartialSettlement:
    """A single charge may absorb part of its net; the rest stays open."""

    def test_single_charge_partial(self) -> None:
        result = allocate_deposit(_deposit("600.00"), [_charge("ch_1", gross="1000.00")], _STRICT)
        assert result.outcome is PayoutOutcome.EXCEPTION
        assert result.exception_code is ExceptionCode.PARTIAL_SETTLEMENT
        assert result.reason is PayoutReason.PARTIAL
        assert result.allocated_total == Decimal("600.00")
        assert result.open_balance == Decimal("400.00")
        assert result.unallocated_deposit == Decimal("0.00")
        assert result.legs[0].allocated == Decimal("600.00")
        assert result.legs[0].net == Decimal("1000.00")

    def test_multi_charge_shortfall_does_not_guess_a_partial(self) -> None:
        charges = [
            _charge("ch_1", gross="1000.00"),
            _charge("ch_2", gross="900.00"),
        ]
        result = allocate_deposit(_deposit("600.00"), charges, _STRICT)
        assert result.outcome is PayoutOutcome.EXCEPTION
        assert result.exception_code is ExceptionCode.PAYOUT_MISMATCH
        assert result.reason is PayoutReason.NO_CANDIDATE
        assert result.allocated_total == Decimal("0.00")
        assert result.unallocated_deposit == Decimal("600.00")
        assert result.legs == ()


class TestEvidenceGaps:
    """Missing or out-of-window deposit evidence is open, not an exception."""

    def test_missing_deposit(self) -> None:
        charge = _charge("ch_1", gross="300.00")
        result = reconcile_payout(None, [charge], _STRICT)
        assert result.outcome is PayoutOutcome.PENDING_EVIDENCE
        assert result.reason is PayoutReason.NO_DEPOSIT
        assert result.exception_code is None
        assert result.open_balance == Decimal("300.00")
        assert result.unallocated_deposit == Decimal("0.00")

    def test_outside_window(self) -> None:
        charge = _charge("ch_1", gross="300.00", occurred_at=_AT)
        result = reconcile_payout(
            _deposit("300.00", posted_at=_AT + timedelta(days=3)),
            [charge],
            _STRICT,
            window_seconds=3600,
        )
        assert result.outcome is PayoutOutcome.PENDING_EVIDENCE
        assert result.reason is PayoutReason.OUTSIDE_WINDOW
        assert result.allocated_total == Decimal("0.00")
        assert result.open_balance == Decimal("300.00")

    def test_inside_window_matches(self) -> None:
        charge = _charge("ch_1", gross="300.00", occurred_at=_AT)
        result = reconcile_payout(
            _deposit("300.00", posted_at=_AT + timedelta(minutes=30)),
            [charge],
            _STRICT,
            window_seconds=3600,
        )
        assert result.outcome is PayoutOutcome.MATCHED


class TestAmbiguity:
    """Two different charge sets fitting the same deposit require a human."""

    def test_two_candidate_sets(self) -> None:
        charges = [
            _charge("ch_1", gross="388.00"),
            _charge("ch_2", gross="291.00"),
            _charge("ch_3", gross="291.00"),
            _charge("ch_4", gross="970.00"),
        ]
        result = allocate_deposit(_deposit("970.00"), charges, _STRICT)
        assert result.outcome is PayoutOutcome.REQUIRES_HUMAN
        assert result.reason is PayoutReason.AMBIGUOUS
        assert result.exception_code is None
        assert result.legs == ()
        assert result.allocated_total == Decimal("0.00")
        assert result.open_balance == Decimal("1940.00")
        assert {candidate.payment_ids for candidate in result.candidates} == {
            ("ch_1", "ch_2", "ch_3"),
            ("ch_4",),
        }

    def test_candidate_limit_is_reported_not_exceeded(self) -> None:
        charges = [_charge(f"ch_{index}", gross="100.00") for index in range(3)]
        result = allocate_deposit(_deposit("200.00"), charges, _STRICT, max_candidates=1)
        assert result.outcome is PayoutOutcome.REQUIRES_HUMAN
        assert result.reason is PayoutReason.CANDIDATE_LIMIT
        assert result.candidates == ()


class TestResidualClassification:
    """Every residual has one deterministic, documented explanation."""

    def test_duplicate_reingest(self) -> None:
        result = allocate_deposit(
            _deposit("300.00"), [_charge("ch_1", gross="300.00")], _STRICT, duplicate=True
        )
        assert result.outcome is PayoutOutcome.EXCEPTION
        assert result.exception_code is ExceptionCode.DUPLICATE_LEDGER_ENTRY
        assert result.reason is PayoutReason.DUPLICATE
        assert result.allocated_total == Decimal("300.00")

    def test_refund_lag(self) -> None:
        charge = _charge("ch_1", gross="1000.00", refund="400.00")
        result = allocate_deposit(_deposit("1000.00"), [charge], _STRICT)
        assert result.exception_code is ExceptionCode.PARTIAL_REFUND_ACCOUNTING_LAG
        assert result.reason is PayoutReason.REFUND_LAG
        assert result.allocated_total == Decimal("600.00")
        assert result.unallocated_deposit == Decimal("400.00")

    def test_fee_drift(self) -> None:
        charges = [
            _charge("ch_1", gross="1000.00", fee="29.00"),
            _charge("ch_2", gross="30.00"),
        ]
        result = allocate_deposit(_deposit("1031.00"), charges, _STRICT)
        assert result.exception_code is ExceptionCode.FEE_MISMATCH
        assert result.reason is PayoutReason.FEE_DRIFT
        assert result.allocated_total == Decimal("1001.00")
        assert result.unallocated_deposit == Decimal("30.00")
        assert result.fee_total == Decimal("29.00")

    def test_unexplained_over_deposit(self) -> None:
        result = allocate_deposit(_deposit("600.00"), [_charge("ch_1", gross="500.00")], _STRICT)
        assert result.exception_code is ExceptionCode.PAYOUT_MISMATCH
        assert result.reason is PayoutReason.UNALLOCATED_DEPOSIT
        assert result.allocated_total == Decimal("500.00")
        assert result.unallocated_deposit == Decimal("100.00")
        assert result.open_balance == Decimal("0.00")


class TestIsolationAndValidation:
    """Tenant and currency boundaries fail closed with typed errors."""

    def test_tenant_mismatch_raises(self) -> None:
        charge = _charge("ch_1", gross="300.00", tenant_id="tenant-other")
        with pytest.raises(TenantIsolationError):
            allocate_deposit(_deposit("300.00"), [charge], _STRICT)

    def test_mixed_charge_tenants_raise(self) -> None:
        charges = [
            _charge("ch_1", gross="300.00"),
            _charge("ch_2", gross="300.00", tenant_id="tenant-other"),
        ]
        with pytest.raises(TenantIsolationError):
            reconcile_payout(None, charges, _STRICT)

    def test_currency_mismatch_raises(self) -> None:
        charge = _charge("ch_1", gross="300.00", currency="EUR")
        with pytest.raises(CurrencyMismatch):
            allocate_deposit(_deposit("300.00"), [charge], _STRICT)

    def test_empty_charges_raise(self) -> None:
        with pytest.raises(InvariantViolation):
            reconcile_payout(_deposit("300.00"), [], _STRICT)

    def test_bad_window_and_candidate_limit_raise(self) -> None:
        charge = _charge("ch_1", gross="300.00")
        with pytest.raises(InvariantViolation):
            reconcile_payout(_deposit("300.00"), [charge], _STRICT, window_seconds=-1)
        with pytest.raises(InvariantViolation):
            reconcile_payout(_deposit("300.00"), [charge], _STRICT, max_candidates=0)


class TestInvariants:
    """The frozen value objects reject incoherent construction."""

    def test_leg_allocation_bounds(self) -> None:
        base = _charge("ch_1", gross="100.00")
        fingerprint = fingerprint_payment(base)
        with pytest.raises(InvariantViolation):
            AllocationLeg(
                payment_id="ch_1",
                fingerprint=fingerprint,
                gross=Decimal("100.00"),
                fee=Decimal("0.00"),
                refund=Decimal("0.00"),
                net=Decimal("100.00"),
                allocated=Decimal("0.00"),
            )
        with pytest.raises(InvariantViolation):
            AllocationLeg(
                payment_id="ch_1",
                fingerprint=fingerprint,
                gross=Decimal("100.00"),
                fee=Decimal("0.00"),
                refund=Decimal("0.00"),
                net=Decimal("100.00"),
                allocated=Decimal("100.01"),
            )

    def test_closed_outcome_carries_no_reason(self) -> None:
        with pytest.raises(InvariantViolation):
            Allocation(
                outcome=PayoutOutcome.MATCHED,
                reason=PayoutReason.PARTIAL,
                exception_code=None,
                tenant_id=_TENANT,
                currency="USD",
            )

    def test_ambiguous_requires_candidates(self) -> None:
        with pytest.raises(InvariantViolation):
            Allocation(
                outcome=PayoutOutcome.REQUIRES_HUMAN,
                reason=PayoutReason.AMBIGUOUS,
                exception_code=None,
                tenant_id=_TENANT,
                currency="USD",
            )

    def test_fingerprint_replays(self) -> None:
        charge = _charge("ch_1", gross="300.00")
        first = allocate_deposit(_deposit("300.00"), [charge], _STRICT)
        second = allocate_deposit(_deposit("300.00"), [charge], _STRICT)
        assert first.fingerprint == second.fingerprint
