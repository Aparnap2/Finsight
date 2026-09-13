"""Unit tests for the P3.1 sandbox QuickBooks adapter.

Covers the frozen ``exception-ops`` adapter contract with a fully
deterministic mock: no network, no clock, no randomness. Every script
(transient budgets, visibility lag) is seeded per test via constructor
arguments.
"""

from decimal import Decimal
from typing import Any

import pytest

from finance.accounting.adapter import (
    AccountingAdapter,
    AccountingEntry,
    CallOutcome,
    EntryStatus,
)
from finance.accounting.commands import CorrectingEntryCommand, JournalLine
from finance.accounting.errors import (
    EntryNotFoundError,
    FloatMoneyError,
    IdempotencyConflictError,
    TransientError,
    UnsupportedActionError,
    ValidationError,
)
from finance.accounting.mock import MockQuickBooksAdapter
from finance.reconciliation.models import ExceptionCode

_REFUND_LAG = ExceptionCode.PARTIAL_REFUND_ACCOUNTING_LAG.value
_FEE_MISMATCH = ExceptionCode.FEE_MISMATCH.value
_DUPLICATE = ExceptionCode.DUPLICATE_LEDGER_ENTRY.value


def _lines(
    debit_account: str = "4100-refunds",
    credit_account: str = "1000-cash",
    amount: Decimal = Decimal("150.00"),
) -> tuple[JournalLine, ...]:
    """Build one balanced debit/credit leg pair."""
    return (
        JournalLine(account=debit_account, debit=amount, credit=Decimal("0")),
        JournalLine(account=credit_account, debit=Decimal("0"), credit=amount),
    )


def _command(
    *,
    exception_type: str = _REFUND_LAG,
    amount: Decimal = Decimal("150.00"),
    source_reference: str = "stripe-pi-123",
    debit_account: str = "4100-refunds",
    credit_account: str = "1000-cash",
    lines: tuple[JournalLine, ...] | None = None,
) -> CorrectingEntryCommand:
    """Build a deterministic refund-lag correcting command."""
    return CorrectingEntryCommand(
        tenant_id="tenant-acme",
        exception_id="exc-1",
        exception_type=exception_type,
        currency="USD",
        lines=lines if lines is not None else _lines(debit_account, credit_account, amount),
        source_reference=source_reference,
        memo="refund lag correction",
    )


def test_adapter_conformance_and_sandbox_markers() -> None:
    """Mock satisfies the protocol and is unmistakably sandbox-only."""
    adapter = MockQuickBooksAdapter()
    assert isinstance(adapter, AccountingAdapter)
    assert MockQuickBooksAdapter.sandbox_only is True


def test_correcting_entry_happy_path() -> None:
    """Balanced refund-lag command posts one entry and logs key+outcome."""
    adapter = MockQuickBooksAdapter()
    entry = adapter.create_correcting_entry(_command(), "key-001")

    assert isinstance(entry, AccountingEntry)
    assert entry.entry_id.startswith("MOCK-")
    assert entry.status is EntryStatus.POSTED
    assert entry.total == Decimal("150.00")
    assert adapter.entry_count == 1

    call = adapter.calls[-1]
    assert (call.op, call.key, call.outcome) == (
        "create_correcting_entry",
        "key-001",
        CallOutcome.SUCCESS,
    )
    assert call.entry_id == entry.entry_id


def test_void_happy_path() -> None:
    """Void flips a posted entry to VOIDED exactly once."""
    adapter = MockQuickBooksAdapter()
    entry = adapter.create_correcting_entry(_command(), "key-create")
    voided = adapter.void_entry(entry.entry_id, "key-void")

    assert voided.entry_id == entry.entry_id
    assert voided.status is EntryStatus.VOIDED
    assert adapter.get_entry(entry.entry_id).status is EntryStatus.VOIDED

    with pytest.raises(ValidationError, match="already voided"):
        adapter.void_entry(entry.entry_id, "key-void-again")
    assert adapter.calls[-1].outcome is CallOutcome.VALIDATION_FAILURE


def test_idempotent_retry_same_key_returns_original() -> None:
    """Same key + byte-identical payload replays without duplicating."""
    adapter = MockQuickBooksAdapter()
    first = adapter.create_correcting_entry(_command(), "key-replay")
    second = adapter.create_correcting_entry(_command(), "key-replay")

    assert second.entry_id == first.entry_id
    assert adapter.entry_count == 1
    assert adapter.calls[-1].outcome is CallOutcome.IDEMPOTENCY_REPLAY


def test_idempotency_conflict_on_differing_payload() -> None:
    """Same key + differing payload is rejected with no new record."""
    adapter = MockQuickBooksAdapter()
    adapter.create_correcting_entry(_command(amount=Decimal("150.00")), "key-clash")

    with pytest.raises(IdempotencyConflictError, match="differing payload"):
        adapter.create_correcting_entry(_command(amount=Decimal("200.00")), "key-clash")

    assert adapter.entry_count == 1
    assert adapter.calls[-1].outcome is CallOutcome.IDEMPOTENCY_CONFLICT


@pytest.mark.parametrize(
    ("label", "kwargs"),
    [
        (
            "unbalanced",
            {"lines": _lines(amount=Decimal("150.00"))[:1] + _lines(amount=Decimal("99.00"))[1:]},
        ),
        ("unknown-account", {"debit_account": "9999-nope"}),
        ("blank-account", {"debit_account": "   "}),
        ("missing-ref", {"source_reference": "   "}),
        (
            "two-sided-line",
            {
                "lines": (
                    JournalLine(account="4100-refunds", debit=Decimal("10"), credit=Decimal("5")),
                    JournalLine(account="1000-cash", debit=Decimal("0"), credit=Decimal("15")),
                )
            },
        ),
    ],
)
def test_validation_failure_creates_no_record(label: str, kwargs: dict[str, Any]) -> None:
    """Invalid account / unbalanced / missing ref → error, no record."""
    assert label, "parametrized case must carry a label for test ids"
    adapter = MockQuickBooksAdapter()
    with pytest.raises(ValidationError):
        adapter.create_correcting_entry(_command(**kwargs), "key-bad")
    assert adapter.entry_count == 0
    assert adapter.calls[-1].outcome is CallOutcome.VALIDATION_FAILURE


def test_transient_then_success_records_single_entry() -> None:
    """Scripted fail-first-2 then success yields exactly one record."""
    adapter = MockQuickBooksAdapter(transient_failures={"key-flaky": 2})

    with pytest.raises(TransientError, match="transient 5xx"):
        adapter.create_correcting_entry(_command(), "key-flaky")
    with pytest.raises(TransientError, match="transient 5xx"):
        adapter.create_correcting_entry(_command(), "key-flaky")

    entry = adapter.create_correcting_entry(_command(), "key-flaky")
    replay = adapter.create_correcting_entry(_command(), "key-flaky")

    assert replay.entry_id == entry.entry_id
    assert adapter.entry_count == 1
    outcomes = [call.outcome for call in adapter.calls]
    assert outcomes == [
        CallOutcome.TRANSIENT_5XX,
        CallOutcome.TRANSIENT_5XX,
        CallOutcome.SUCCESS,
        CallOutcome.IDEMPOTENCY_REPLAY,
    ]


def test_delayed_visibility_lag_then_visible() -> None:
    """Write succeeds but reads miss until the poll count elapses."""
    adapter = MockQuickBooksAdapter(visibility_lag_reads=2)
    entry = adapter.create_correcting_entry(_command(), "key-lag")

    with pytest.raises(EntryNotFoundError, match="not yet visible"):
        adapter.get_entry(entry.entry_id)
    with pytest.raises(EntryNotFoundError, match="not yet visible"):
        adapter.get_entry(entry.entry_id)

    visible = adapter.get_entry(entry.entry_id)
    assert visible.entry_id == entry.entry_id
    outcomes = [call.outcome for call in adapter.calls if call.op == "get_entry"]
    assert outcomes == [
        CallOutcome.NOT_YET_VISIBLE,
        CallOutcome.NOT_YET_VISIBLE,
        CallOutcome.SUCCESS,
    ]


def test_get_unknown_entry_is_not_found() -> None:
    """Unknown ids miss without touching the books."""
    adapter = MockQuickBooksAdapter()
    with pytest.raises(EntryNotFoundError, match="Unknown entry id"):
        adapter.get_entry("MOCK-000999")
    assert adapter.calls[-1].outcome is CallOutcome.NOT_FOUND


def test_unsupported_fee_action_rejected() -> None:
    """Fee-mismatch is proposal-only: adapter rejects with no record."""
    adapter = MockQuickBooksAdapter()
    with pytest.raises(UnsupportedActionError, match="proposal-only"):
        adapter.create_correcting_entry(_command(exception_type=_FEE_MISMATCH), "key-fee")
    assert adapter.entry_count == 0
    assert adapter.calls[-1].outcome is CallOutcome.UNSUPPORTED_ACTION


def test_duplicate_code_rejected_on_create() -> None:
    """Create serves refund-lag only; duplicate belongs to the void path."""
    adapter = MockQuickBooksAdapter()
    with pytest.raises(UnsupportedActionError, match="refund-lag"):
        adapter.create_correcting_entry(_command(exception_type=_DUPLICATE), "key-dup")
    assert adapter.entry_count == 0


@pytest.mark.parametrize("money", [10.5, True])
def test_decimal_only_float_rejected(money: object) -> None:
    """Float/bool money is rejected at the command boundary."""
    with pytest.raises(FloatMoneyError):
        JournalLine(account="4100-refunds", debit=money, credit=Decimal("0"))  # type: ignore[arg-type]
