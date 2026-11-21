"""Executable behavioural contract for the three-source reconciliation engine.

The operator report already checks the frozen fixture, but it computes those
checks with the same module under test. This module states the contract
*independently*: it reads the engine's public outputs and asserts the financial
invariants directly, so a defect in the reporting layer cannot hide a defect in
the engine.

Covered here:

* allocation conservation, on every fixture scenario and on a deterministic
  generated sweep;
* no charge allocated twice inside a run;
* closed arithmetic for every settled deposit (no false settlement);
* the frozen scenario catalogue: status, outcome, exception code, and money;
* order independence for invoice and processor records, and the documented
  drift rule for bank rows;
* provenance: every allocated leg resolves to an input charge, every evidence
  line to an input statement row;
* refunds reported separately and never increasing settled value;
* Decimal-only money in the emitted report;
* replay determinism;
* adversarial engine cases: fully refunded and negative-net charges.

No production code is modified, no fixture is edited, and no test is removed.
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest

from finance.reconciliation.allocation import Allocation, allocate_deposit
from finance.reconciliation.bank import BankDepositRecord
from finance.reconciliation.fingerprints import fingerprint_payment
from finance.reconciliation.models import (
    ExceptionCode,
    PaymentRecord,
    PaymentStatus,
    PayoutOutcome,
)
from finance.reconciliation.statement_workflow import (
    ReconciliationReport,
    StatementSources,
    run_statement_reconciliation,
    sources_from_export,
)
from finance.reconciliation.tolerances import ReconciliationTolerance

_FIXTURES = (
    Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "reconciliation" / "triangle"
)
_CASES = _FIXTURES / "cases.json"

_DOCUMENT: dict[str, Any] = cast("dict[str, Any]", json.loads(_CASES.read_text(encoding="utf-8")))
_SCENARIOS: Mapping[str, Mapping[str, Any]] = cast(
    "Mapping[str, Mapping[str, Any]]", _DOCUMENT["scenarios"]
)
_TENANT = str(_DOCUMENT["tenant_id"])
_CURRENCY = str(_DOCUMENT["currency"])
_DIGEST = "d" * 64
_STRICT = ReconciliationTolerance()
_ZERO = Decimal("0")
_SETTLED = (PayoutOutcome.MATCHED, PayoutOutcome.TOLERANCE_MATCHED)

#: Frozen scenario catalogue. Status and outcome are the contract, not a
#: snapshot: changing one of these rows requires a spec change.
_CATALOGUE: Mapping[str, tuple[str, str, str | None]] = {
    "s1_exact_match": ("reconciled", "MATCHED", None),
    "s2_fee_explained": ("reconciled", "MATCHED", None),
    "s3_many_to_one": ("reconciled", "MATCHED", None),
    "s4a_refund_folded": ("reconciled", "MATCHED", None),
    "s4b_partial_payment": ("pending_evidence", "PENDING_EVIDENCE", None),
    "s5_delayed": ("reconciled", "MATCHED", None),
    "s5b_missing_deposit": ("pending_evidence", "PENDING_EVIDENCE", None),
    "s6_duplicate": ("exception", "EXCEPTION", "I-DUPLICATE"),
    "s7_ambiguous_allocation": ("ambiguous", "REQUIRES_HUMAN", None),
}

_SCENARIO_IDS = tuple(sorted(_SCENARIOS))


def _sources(case: Mapping[str, Any], *, window_seconds: int | None = None) -> StatementSources:
    """Build the three sources for one fixture scenario."""
    return sources_from_export(
        case,
        tenant_id=_TENANT,
        currency=_CURRENCY,
        tolerance=_STRICT,
        statement_digest=_DIGEST,
        window_seconds=window_seconds,
    )


def _run(case: Mapping[str, Any], *, window_seconds: int | None = None) -> ReconciliationReport:
    """Run the composed workflow for one scenario."""
    return run_statement_reconciliation(_sources(case, window_seconds=window_seconds))


def _scenario(name: str) -> ReconciliationReport:
    """Run one named fixture scenario with the canonical settings."""
    return _run(_SCENARIOS[name])


def _signature(report: ReconciliationReport) -> tuple[object, ...]:
    """Return every financially meaningful value in a comparable form."""
    return (
        tuple(
            sorted(
                (link.invoice_id, link.charge_id, link.result.outcome.value, link.difference)
                for link in report.links
            )
        ),
        tuple(report.unlinked_invoices),
        tuple(report.unlinked_charges),
        tuple(
            sorted(
                (
                    deposit.deposit_id,
                    deposit.allocation.outcome.value,
                    str(deposit.allocation.reason),
                    str(deposit.allocation.exception_code),
                    deposit.allocation.allocated_total,
                    deposit.allocation.open_balance,
                    deposit.allocation.unallocated_deposit,
                )
                for deposit in report.deposits
            )
        ),
        tuple(
            sorted(
                (leg.payment_id, leg.allocated)
                for deposit in report.deposits
                for leg in deposit.allocation.legs
            )
        ),
    )


def _permuted(case: Mapping[str, Any], keys: Sequence[str]) -> dict[str, Any]:
    """Return a copy of the scenario with the named lists reversed."""
    copy: dict[str, Any] = dict(case)
    for key in keys:
        copy[key] = list(reversed(cast("list[Any]", case.get(key, []))))
    return copy


def _float_paths(node: object, path: str = "$") -> list[str]:
    """Collect the paths of every float anywhere in a JSON-safe structure."""
    found: list[str] = []
    if isinstance(node, float):
        found.append(path)
    elif isinstance(node, Mapping):
        for key, value in cast("Mapping[object, object]", node).items():
            found.extend(_float_paths(value, f"{path}.{key}"))
    elif isinstance(node, (list, tuple)):
        for index, value in enumerate(cast("Sequence[object]", node)):
            found.extend(_float_paths(value, f"{path}[{index}]"))
    return found


def _charge_records(case: Mapping[str, Any]) -> dict[str, PaymentRecord]:
    """Return the normalized processor charges keyed by payment id."""
    return {charge.payment_id: charge for charge in _sources(case).charges}


def _record(
    payment_id: str,
    *,
    gross: str,
    fee: str = "0.00",
    refund: str = "0.00",
    occurred_at: datetime | None = None,
) -> PaymentRecord:
    """Build one valid charge record for an inline adversarial case."""
    gross_value = Decimal(gross)
    fee_value = Decimal(fee)
    refund_value = Decimal(refund)
    return PaymentRecord(
        payment_id=payment_id,
        provider="stripe",
        provider_event_id=f"evt-{payment_id}",
        idempotency_key=f"idem-{payment_id}",
        gross=gross_value,
        fee=fee_value,
        refund=refund_value,
        net=gross_value - fee_value - refund_value,
        currency=_CURRENCY,
        status=PaymentStatus.CAPTURED,
        occurred_at=occurred_at or datetime(2026, 1, 10, 12, tzinfo=UTC),
        tenant_id=_TENANT,
    )


def _deposit(amount: str, *, line_number: int = 1) -> BankDepositRecord:
    """Build one valid bank deposit for an inline adversarial case."""
    return BankDepositRecord(
        deposit_id=f"dep-{line_number}",
        tenant_id=_TENANT,
        amount=Decimal(amount),
        currency=_CURRENCY,
        posted_at=datetime(2026, 1, 10, 12, tzinfo=UTC),
        statement_digest=_DIGEST,
        line_number=line_number,
    )


# --- A. allocation conservation -------------------------------------------


@pytest.mark.parametrize("name", _SCENARIO_IDS)
def test_every_deposit_conserves_its_money(name: str) -> None:
    """Allocated plus open equals eligible net, and plus residual the deposit."""
    report = _scenario(name)
    for deposit in report.deposits:
        allocation = deposit.allocation
        assert allocation.allocated_total + allocation.open_balance == (
            allocation.eligible_net_total
        ), f"{name}/{deposit.deposit_id}: charge conservation"
        assert allocation.deposit is not None, f"{name}/{deposit.deposit_id}: deposit missing"
        assert allocation.allocated_total + allocation.unallocated_deposit == (
            allocation.deposit.amount
        ), f"{name}/{deposit.deposit_id}: deposit conservation"
        assert allocation.open_balance >= _ZERO, f"{name}/{deposit.deposit_id}: negative open"
        assert allocation.unallocated_deposit >= _ZERO, (
            f"{name}/{deposit.deposit_id}: negative residual"
        )
        assert allocation.allocated_total == sum(
            (leg.allocated for leg in allocation.legs), _ZERO
        ), f"{name}/{deposit.deposit_id}: leg sum"
        assert allocation.fee_total == sum((leg.fee for leg in allocation.legs), _ZERO)
        assert allocation.refund_total == sum((leg.refund for leg in allocation.legs), _ZERO)


# --- B. no double allocation ----------------------------------------------


@pytest.mark.parametrize("name", _SCENARIO_IDS)
def test_no_charge_is_allocated_twice(name: str) -> None:
    """Each charge appears in at most one allocation leg per run."""
    report = _scenario(name)
    allocated = [leg.payment_id for deposit in report.deposits for leg in deposit.allocation.legs]
    assert len(allocated) == len(set(allocated)), f"{name}: charge allocated twice: {allocated}"
    for deposit in report.deposits:
        for leg in deposit.allocation.legs:
            assert leg.allocated > _ZERO, f"{name}: non-positive leg for {leg.payment_id}"
            assert leg.allocated <= leg.net, f"{name}: over-allocation for {leg.payment_id}"
            assert leg.net == leg.gross - leg.fee - leg.refund, f"{name}: leg net equation"


# --- D. no false settlement ------------------------------------------------


@pytest.mark.parametrize("name", _SCENARIO_IDS)
def test_a_settled_deposit_is_arithmetically_closed(name: str) -> None:
    """A settled deposit has no residual and every leg is fully credited."""
    report = _scenario(name)
    for deposit in report.deposits:
        allocation = deposit.allocation
        if allocation.outcome not in _SETTLED:
            continue
        assert allocation.legs, f"{name}/{deposit.deposit_id}: settled with no legs"
        assert allocation.unallocated_deposit == _ZERO, (
            f"{name}/{deposit.deposit_id}: settled with a residual"
        )
        assert all(leg.allocated == leg.net for leg in allocation.legs), (
            f"{name}/{deposit.deposit_id}: settled leg is not fully credited"
        )
        assert allocation.allocated_total == allocation.eligible_net_total, (
            f"{name}/{deposit.deposit_id}: settled with open charge value"
        )
        # In this fixture every deposit is the only evidence for its charges,
        # so a settled deposit also closes the whole eligible scope.
        assert allocation.open_balance == _ZERO


@pytest.mark.parametrize("name", _SCENARIO_IDS)
def test_the_catalogue_status_matches_the_run(name: str) -> None:
    """Every scenario reports the frozen status, outcome, and exception code."""
    expected_status, expected_outcome, expected_code = _CATALOGUE[name]
    report = _scenario(name)
    assert report.deposits or expected_status == "pending_evidence", f"{name}: no deposit results"
    if not report.deposits:
        assert expected_status == "pending_evidence", f"{name}: empty run cannot be settled"
        return
    statuses = {
        PayoutOutcome.MATCHED: "reconciled",
        PayoutOutcome.TOLERANCE_MATCHED: "reconciled",
        PayoutOutcome.EXCEPTION: "exception",
        PayoutOutcome.PENDING_EVIDENCE: "pending_evidence",
        PayoutOutcome.REQUIRES_HUMAN: "ambiguous",
    }
    severity = {"reconciled": 0, "pending_evidence": 1, "exception": 2, "ambiguous": 3}
    observed = max(
        (statuses[deposit.allocation.outcome] for deposit in report.deposits),
        key=lambda status: severity[status],
    )
    assert observed == expected_status, f"{name}: status {observed} != {expected_status}"
    outcomes = {deposit.allocation.outcome.value for deposit in report.deposits}
    assert expected_outcome in outcomes, f"{name}: outcome {expected_outcome} not in {outcomes}"
    codes = {
        deposit.allocation.exception_code.value
        for deposit in report.deposits
        if deposit.allocation.exception_code is not None
    }
    if expected_code is None:
        assert not codes, f"{name}: unexpected exception codes {codes}"
    else:
        assert expected_code in codes, f"{name}: expected {expected_code}, got {codes}"


@pytest.mark.parametrize("name", _SCENARIO_IDS)
def test_missing_or_ambiguous_evidence_is_never_settled(name: str) -> None:
    """An open allocation carries a reason and allocates nothing silently."""
    report = _scenario(name)
    for deposit in report.deposits:
        allocation = deposit.allocation
        if allocation.outcome in _SETTLED:
            continue
        assert allocation.reason is not None, (
            f"{name}/{deposit.deposit_id}: open outcome without a reason"
        )
        if allocation.outcome is PayoutOutcome.REQUIRES_HUMAN:
            assert len(allocation.candidates) >= 2, (
                f"{name}/{deposit.deposit_id}: ambiguity needs at least two candidates"
            )
            assert not allocation.legs, (
                f"{name}/{deposit.deposit_id}: ambiguity must not pick a leg"
            )
        if allocation.outcome is PayoutOutcome.EXCEPTION:
            assert allocation.exception_code is not None, (
                f"{name}/{deposit.deposit_id}: exception without a code"
            )


# --- E. determinism and order independence --------------------------------


@pytest.mark.parametrize("name", _SCENARIO_IDS)
def test_replay_of_a_scenario_is_identical(name: str) -> None:
    """The same inputs produce the same document and the same fingerprint."""
    first = _scenario(name)
    second = _scenario(name)
    assert first.fingerprint == second.fingerprint, f"{name}: fingerprint drifted"
    assert first.to_dict() == second.to_dict(), f"{name}: report drifted"


@pytest.mark.parametrize("name", _SCENARIO_IDS)
def test_invoice_and_charge_order_does_not_change_the_result(name: str) -> None:
    """Out-of-order invoice and processor records produce the same result."""
    case = _SCENARIOS[name]
    base = _signature(_run(case))
    reordered = _signature(_run(_permuted(case, ("invoice", "stripe"))))
    assert reordered == base, f"{name}: source order changed the financial result"


@pytest.mark.parametrize("name", _SCENARIO_IDS)
def test_bank_order_changes_only_the_authoritative_drift_row(name: str) -> None:
    """Reversing a statement either changes nothing or keeps the safety verdict.

    The documented rule is that the latest statement line wins for a reused
    deposit id. Reversing the file therefore changes *which* drifted amount is
    authoritative; it must never turn the scenario into a settlement.
    """
    case = _SCENARIOS[name]
    base = _scenario(name)
    reversed_report = _run(_permuted(case, ("bank",)))
    if not base.drift_groups:
        assert _signature(reversed_report) == _signature(base), (
            f"{name}: bank row order changed the result without a drift group"
        )
        return
    for deposit in reversed_report.deposits:
        assert deposit.allocation.outcome is PayoutOutcome.EXCEPTION, (
            f"{name}: reversed drift became {deposit.allocation.outcome.value}"
        )
        assert deposit.allocation.exception_code is ExceptionCode.DUPLICATE_LEDGER_ENTRY, (
            f"{name}: reversed drift lost the duplicate code"
        )


# --- F. provenance ---------------------------------------------------------


@pytest.mark.parametrize("name", _SCENARIO_IDS)
def test_every_allocated_leg_resolves_to_an_input_charge(name: str) -> None:
    """Each leg carries the fingerprint and money of the charge it settles."""
    case = _SCENARIOS[name]
    charges = _charge_records(case)
    bank_rows = cast("list[Any]", case.get("bank", []))
    report = _run(case)
    for deposit in report.deposits:
        for leg in deposit.allocation.legs:
            charge = charges[leg.payment_id]
            assert leg.fingerprint == fingerprint_payment(charge), (
                f"{name}: leg {leg.payment_id} fingerprint does not match its source"
            )
            assert (leg.gross, leg.fee, leg.refund, leg.net) == (
                charge.gross,
                charge.fee,
                charge.refund,
                charge.net,
            ), f"{name}: leg {leg.payment_id} money does not match its source"
        for item in deposit.evidence:
            assert 2 <= item.line_number <= len(bank_rows) + 1, (
                f"{name}: evidence line {item.line_number} is outside the statement"
            )


# --- H. refund conservation ------------------------------------------------


@pytest.mark.parametrize("name", _SCENARIO_IDS)
def test_refunds_never_increase_settled_value(name: str) -> None:
    """Settled value is bounded by net, and refunds are reported separately."""
    report = _scenario(name)
    for deposit in report.deposits:
        allocation = deposit.allocation
        for leg in allocation.legs:
            assert leg.allocated <= leg.gross - leg.fee, (
                f"{name}/{leg.payment_id}: refund was counted as settled value"
            )
            assert leg.allocated + leg.refund <= leg.gross, (
                f"{name}/{leg.payment_id}: allocated plus refund exceeds gross"
            )


def test_the_refund_scenario_reports_the_refund_separately() -> None:
    """s4a settles the net and reports the refund as its own total."""
    report = _scenario("s4a_refund_folded")
    allocation = report.deposits[0].allocation
    assert allocation.refund_total == Decimal("400.00")
    assert allocation.allocated_total == Decimal("571.00")
    assert allocation.eligible_net_total == Decimal("571.00")
    assert allocation.allocated_total + allocation.refund_total == Decimal("971.00")
    assert allocation.allocated_total + allocation.refund_total < Decimal("1000.00")


# --- C. Decimal-only money -------------------------------------------------


@pytest.mark.parametrize("name", _SCENARIO_IDS)
def test_the_report_contains_no_float_money(name: str) -> None:
    """No value in the emitted report is a float."""
    payload = _scenario(name).to_dict()
    assert _float_paths(payload) == [], f"{name}: float money in the report"


# --- adversarial engine cases ---------------------------------------------


def test_a_fully_refunded_charge_is_excluded_not_settled() -> None:
    """A charge refunded in full is not allocated and not reported as settled.

    Current behaviour, recorded deliberately: a fully refunded charge has
    ``net == 0`` and is filtered out of the eligible set, so a deposit that
    matches only refunded charges is ``PENDING_EVIDENCE`` / ``NO_CANDIDATE``
    rather than reconciled. That is safe (nothing is falsely settled) but it is
    a product gap: a fully refunded charge should eventually be reported as
    settled-by-refund, not as missing evidence.
    """
    charge = _record("full-refund", gross="100.00", refund="100.00")
    assert charge.net == _ZERO
    allocation = allocate_deposit(_deposit("100.00"), [charge], _STRICT)
    assert allocation.outcome is PayoutOutcome.PENDING_EVIDENCE
    assert allocation.allocated_total == _ZERO
    assert allocation.legs == ()


def test_a_fully_refunded_charge_does_not_absorb_a_deposit() -> None:
    """The eligible charge still settles; the refunded one is not allocated."""
    refunded = _record("full-refund", gross="100.00", refund="100.00")
    eligible = _record("live", gross="100.00")
    allocation = allocate_deposit(_deposit("100.00"), [refunded, eligible], _STRICT)
    assert allocation.outcome is PayoutOutcome.MATCHED
    assert [leg.payment_id for leg in allocation.legs] == ["live"]
    assert allocation.refund_total == _ZERO
    assert allocation.allocated_total == Decimal("100.00")


def test_a_negative_net_charge_is_never_allocated() -> None:
    """A charge whose refund exceeds its gross is excluded, not netted in."""
    charge = _record("over-refunded", gross="100.00", refund="150.00")
    assert charge.net == Decimal("-50.00")
    allocation = allocate_deposit(_deposit("100.00"), [charge], _STRICT)
    assert allocation.outcome is PayoutOutcome.PENDING_EVIDENCE
    assert allocation.allocated_total == _ZERO
    assert all(leg.allocated > _ZERO for leg in allocation.legs)


def test_an_unknown_deposit_amount_never_invents_a_match() -> None:
    """An over-sized deposit settles what it can and reports the residual."""
    allocation = allocate_deposit(_deposit("123.45"), [_record("a", gross="100.00")], _STRICT)
    assert allocation.outcome is PayoutOutcome.EXCEPTION
    assert allocation.allocated_total == Decimal("100.00")
    assert allocation.unallocated_deposit == Decimal("23.45")
    assert allocation.open_balance == _ZERO


# --- generated sweep ------------------------------------------------------


def _generated_cases(
    seed: int = 20260101, count: int = 40
) -> list[tuple[list[PaymentRecord], Decimal]]:
    """Build deterministic charge sets and deposits for the invariant sweep."""
    rng = random.Random(seed)
    cases: list[tuple[list[PaymentRecord], Decimal]] = []
    for index in range(count):
        size = rng.randint(1, 5)
        charges: list[PaymentRecord] = []
        for position in range(size):
            gross = Decimal(rng.randrange(100, 90000)) / 100
            fee = Decimal(rng.randrange(0, 500)) / 100 if rng.random() < 0.4 else _ZERO
            refund = Decimal(rng.randrange(0, 20000)) / 100 if rng.random() < 0.2 else _ZERO
            refund = min(refund, gross - fee)
            charges.append(
                _record(
                    f"gen-{index}-{position}",
                    gross=str(gross),
                    fee=str(fee),
                    refund=str(refund),
                )
            )
        nets = [charge.net for charge in charges]
        subset = [net for net in nets if rng.random() < 0.5] or [nets[0]]
        amount = sum(subset, _ZERO)
        if amount <= _ZERO:
            # A fully refunded charge has net 0; the deposit must still be a
            # real credit, so fall back to a positive amount.
            amount = nets[0] if nets[0] > _ZERO else Decimal("1.00")
        variant = rng.randrange(3)
        if variant == 1:
            amount += Decimal("0.01")
        elif variant == 2:
            amount += Decimal(rng.randrange(1, 500)) / 100
        cases.append((charges, amount))
    return cases


def _assert_conserved(allocation: Allocation) -> None:
    """Assert the conservation equations and leg bounds on any allocation."""
    assert allocation.allocated_total + allocation.open_balance == allocation.eligible_net_total
    if allocation.deposit is not None:
        assert (
            allocation.allocated_total + allocation.unallocated_deposit == allocation.deposit.amount
        )
    assert allocation.allocated_total == sum((leg.allocated for leg in allocation.legs), _ZERO)
    assert allocation.open_balance >= _ZERO
    assert allocation.unallocated_deposit >= _ZERO
    ids = [leg.payment_id for leg in allocation.legs]
    assert len(ids) == len(set(ids))
    for leg in allocation.legs:
        assert _ZERO < leg.allocated <= leg.net
        assert leg.net == leg.gross - leg.fee - leg.refund


def test_generated_sweep_conserves_money_for_every_outcome() -> None:
    """Every generated allocation satisfies the conservation equations."""
    for charges, amount in _generated_cases():
        allocation = allocate_deposit(_deposit(str(amount)), charges, _STRICT)
        _assert_conserved(allocation)


def test_generated_sweep_is_deterministic() -> None:
    """Repeating a generated allocation yields the same fingerprint."""
    for charges, amount in _generated_cases(count=15):
        first = allocate_deposit(_deposit(str(amount)), charges, _STRICT)
        second = allocate_deposit(_deposit(str(amount)), charges, _STRICT)
        assert first.fingerprint == second.fingerprint
        assert first == second


def test_generated_sweep_never_settles_without_an_exact_subset() -> None:
    """A settled generated allocation reproduces the deposit exactly.

    ``open_balance`` is charge value across the whole eligible scope, so it can
    stay positive when other charges await other deposits. Settlement is
    therefore defined by a zero residual and fully credited legs, not by an
    empty scope.
    """
    for charges, amount in _generated_cases():
        allocation = allocate_deposit(_deposit(str(amount)), charges, _STRICT)
        if allocation.outcome is not PayoutOutcome.MATCHED:
            continue
        assert allocation.allocated_total == amount
        assert allocation.unallocated_deposit == _ZERO
        assert all(leg.allocated == leg.net for leg in allocation.legs)


def test_a_deposit_outside_the_window_is_pending_not_matched() -> None:
    """The date window is a gate: no evidence inside it means no settlement."""
    charge = _record("late", gross="100.00", occurred_at=datetime(2026, 1, 10, 12, tzinfo=UTC))
    deposit = BankDepositRecord(
        deposit_id="dep-late",
        tenant_id=_TENANT,
        amount=Decimal("100.00"),
        currency=_CURRENCY,
        posted_at=datetime(2026, 1, 20, 12, tzinfo=UTC),
        statement_digest=_DIGEST,
        line_number=1,
    )
    allocation = allocate_deposit(deposit, [charge], _STRICT, window_seconds=3600)
    assert allocation.outcome is PayoutOutcome.PENDING_EVIDENCE
    assert allocation.reason is not None
    assert allocation.reason.value == "OUTSIDE_WINDOW"
    assert allocation.allocated_total == _ZERO


def test_a_window_that_contains_the_deposit_settles_it() -> None:
    """The same evidence settles once the window admits it."""
    charge = _record("late", gross="100.00", occurred_at=datetime(2026, 1, 10, 12, tzinfo=UTC))
    deposit = BankDepositRecord(
        deposit_id="dep-late",
        tenant_id=_TENANT,
        amount=Decimal("100.00"),
        currency=_CURRENCY,
        posted_at=datetime(2026, 1, 10, 15, tzinfo=UTC),
        statement_digest=_DIGEST,
        line_number=1,
    )
    allocation = allocate_deposit(deposit, [charge], _STRICT, window_seconds=3 * 3600)
    assert allocation.outcome is PayoutOutcome.MATCHED
    assert allocation.allocated_total == Decimal("100.00")


# --- the machine-readable record ------------------------------------------


def test_the_contract_report_script_verifies_the_fixture(tmp_path: Path) -> None:
    """The report script runs the documented CLI and records a pass."""
    script = Path(__file__).resolve().parents[3] / "scripts" / "reconciliation_contract_report.py"
    output = tmp_path / "contract.json"
    completed = subprocess.run(
        [sys.executable, str(script), "--out", str(output)],
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert completed.returncode == 0, completed.stderr
    payload = cast("dict[str, Any]", json.loads(output.read_text(encoding="utf-8")))
    assert payload["verdict"] == "pass"
    assert payload["checks"]["failed"] == 0
    assert [row["id"] for row in payload["scenarios"]] == list(_SCENARIO_IDS)
    assert all(row["match"] for row in payload["scenarios"])


def test_the_contract_report_records_the_declared_head_commit(tmp_path: Path) -> None:
    """A CI run on a merge ref records the head commit, not the merge commit."""
    script = Path(__file__).resolve().parents[3] / "scripts" / "reconciliation_contract_report.py"
    output = tmp_path / "contract.json"
    declared = "1" * 40
    completed = subprocess.run(
        [sys.executable, str(script), "--out", str(output)],
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
        env={**os.environ, "FINSIGHT_CONTRACT_COMMIT": declared},
    )
    assert completed.returncode == 0, completed.stderr
    payload = cast("dict[str, Any]", json.loads(output.read_text(encoding="utf-8")))
    assert payload["commit"] == declared
    # The checkout is recorded separately, so the record still says what ran.
    assert payload["checked_out_commit"] != declared
    assert len(payload["checked_out_commit"]) == 40
