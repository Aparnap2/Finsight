"""``AccountingAdapter`` interface contract — sandbox only.

The contract declares exactly three operations: create-correcting-entry,
retrieve-entry, and void-entry. Each write accepts a caller-supplied
idempotency key; reads are keyed by entry id. P3 defines the contract
only: behavior is satisfied solely by a mock/sandbox fake. No live
QuickBooks implementation, no network calls, no real credentials.

Only the Python standard library plus P1-adjacent accounting commands
are used. This module imports nothing from ``apps/`` or ``agents/``.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, runtime_checkable

from finance.accounting.commands import CorrectingEntryCommand, JournalLine
from finance.accounting.errors import FloatMoneyError, ValidationError


class EntryStatus(StrEnum):
    """Lifecycle status of a sandbox accounting entry."""

    POSTED = "POSTED"
    VOIDED = "VOIDED"


class CallOutcome(StrEnum):
    """Auditable outcome recorded for every adapter call."""

    SUCCESS = "SUCCESS"
    IDEMPOTENCY_REPLAY = "IDEMPOTENCY_REPLAY"
    VALIDATION_FAILURE = "VALIDATION_FAILURE"
    TRANSIENT_5XX = "TRANSIENT_5XX"
    NOT_YET_VISIBLE = "NOT_YET_VISIBLE"
    NOT_FOUND = "NOT_FOUND"
    UNSUPPORTED_ACTION = "UNSUPPORTED_ACTION"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"


@dataclass(frozen=True)
class AccountingEntry:
    """An immutable sandbox entry as returned by the adapter."""

    entry_id: str
    tenant_id: str
    exception_id: str
    exception_type: str
    status: EntryStatus
    currency: str
    lines: tuple[JournalLine, ...]
    total: Decimal
    source_reference: str
    memo: str | None
    idempotency_key: str

    def __post_init__(self) -> None:
        """Enforce Decimal-only total and coerce string status."""
        if isinstance(self.total, (bool, float)):
            raise FloatMoneyError(
                f"Field 'total' must be Decimal, got {type(self.total).__name__}: "
                "float/bool money is rejected, use decimal.Decimal."
            )
        if not isinstance(self.total, Decimal) or not self.total.is_finite():
            raise ValidationError(
                f"Field 'total' must be a finite Decimal, got {type(self.total).__name__}."
            )
        status_value: object = self.status
        if isinstance(status_value, EntryStatus):
            return
        if isinstance(status_value, str):
            try:
                object.__setattr__(self, "status", EntryStatus(status_value))
            except ValueError as exc:
                raise ValidationError(f"Unknown entry status {status_value!r}.") from exc
            return
        raise ValidationError(
            "Field 'status' must be an EntryStatus or status name, "
            f"got {type(status_value).__name__}."
        )


@dataclass(frozen=True)
class AdapterCall:
    """One auditable adapter invocation: operation, key, and outcome.

    For writes ``key`` is the idempotency key; for reads it is the
    entry id under lookup.
    """

    op: str
    key: str
    outcome: CallOutcome
    entry_id: str | None = None


@runtime_checkable
class AccountingAdapter(Protocol):
    """Sandbox financial-action boundary consumed by the executor.

    Implementations MUST be sandbox-only, injectable, and deterministic:
    no randomness in verdicts, every call logged with key and outcome.
    """

    def create_correcting_entry(
        self, command: CorrectingEntryCommand, idempotency_key: str
    ) -> AccountingEntry:
        """Post a balanced correcting entry; replay-safe on key + payload."""
        ...

    def void_entry(self, entry_id: str, idempotency_key: str) -> AccountingEntry:
        """Void a posted entry exactly once; replay-safe on key + entry."""
        ...

    def get_entry(self, entry_id: str) -> AccountingEntry:
        """Retrieve an entry; may miss inside the delayed-visibility window."""
        ...
