"""Sandbox-only injectable mock of the QuickBooks accounting boundary.

Implements :class:`finance.accounting.adapter.AccountingAdapter` with
pure in-memory state: no network, no credentials, no production books.
Every entry id is prefixed ``MOCK-`` so sandbox records can never be
confused with real books.

Determinism: the mock contains no randomness, no clock, and no I/O.
The three spec failure modes are driven by explicit constructor scripts
("seeded", never random):

- validation failure: business-rule violations raise
  ``ValidationError`` with no record and no key reservation, so a
  corrected retry under the same key is safe;
- transient 5xx: ``transient_failures={key: n}`` raises
  ``TransientError`` ``n`` times for that key before succeeding;
  retries with the same key never duplicate because records are created
  only on the success path behind the idempotency map;
- delayed visibility: ``visibility_lag_reads=n`` makes ``get_entry``
  miss each new entry for its first ``n`` reads; the entry exists, the
  read simply raises ``EntryNotFoundError`` until the poll count elapses.

Scope routing (the caller's responsibility; enforced at the boundary):

- refund-lag (``I-REFUND-LAG``) → ``create_correcting_entry``;
- duplicate (``I-DUPLICATE``) → ``void_entry``;
- fee-mismatch (``I-FEE-DRIFT``) → proposal-only, never calls the
  adapter; any fee-typed command reaching create is rejected with
  ``UnsupportedActionError`` before any other business check.

Check order inside create is fixed and documented: key shape, scope,
business rules, transient script, idempotency replay, then persist.
Only the Python standard library plus P1 models are used. This module
imports nothing from ``apps/`` or ``agents/``.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import ClassVar

from finance.accounting.adapter import (
    AccountingAdapter,
    AccountingEntry,
    AdapterCall,
    CallOutcome,
    EntryStatus,
)
from finance.accounting.commands import CorrectingEntryCommand
from finance.accounting.errors import (
    EntryNotFoundError,
    IdempotencyConflictError,
    TransientError,
    UnsupportedActionError,
    ValidationError,
)
from finance.reconciliation.models import ExceptionCode

logger = logging.getLogger(__name__)

#: Sandbox chart of accounts: the only accounts the mock accepts.
SANDBOX_CHART_OF_ACCOUNTS = frozenset(
    {
        "1000-cash",
        "1100-ar",
        "2000-ap",
        "4000-sales",
        "4100-refunds",
        "5000-fees",
    }
)

_REFUND_LAG_CODE = ExceptionCode.PARTIAL_REFUND_ACCOUNTING_LAG.value
_FEE_MISMATCH_CODE = ExceptionCode.FEE_MISMATCH.value


@dataclass
class _StoredEntry:
    """Mutable mock bookkeeping around an immutable entry."""

    entry: AccountingEntry
    reads: int = 0


class MockQuickBooksAdapter(AccountingAdapter):
    """Injectable deterministic sandbox fake for the adapter contract."""

    sandbox_only: ClassVar[bool] = True

    def __init__(
        self,
        *,
        transient_failures: Mapping[str, int] | None = None,
        visibility_lag_reads: int = 0,
    ) -> None:
        """Seed the deterministic failure scripts.

        Args:
            transient_failures: Idempotency key → number of
                ``TransientError`` raises before that key succeeds.
            visibility_lag_reads: Reads each new entry stays invisible
                for on ``get_entry`` before it is returned.

        Raises:
            ValueError: If a script value is negative, non-integer, or a
                bool (bools are never valid counts).
        """
        script = dict(transient_failures) if transient_failures is not None else {}
        for script_key, remaining in script.items():
            if not isinstance(script_key, str):
                raise ValueError("transient_failures keys must be strings.")
            _require_count("transient_failures value", remaining)
        _require_count("visibility_lag_reads", visibility_lag_reads)
        self._transient_remaining: dict[str, int] = script
        self._visibility_lag: int = visibility_lag_reads
        self._entries: dict[str, _StoredEntry] = {}
        self._create_keys: dict[str, tuple[CorrectingEntryCommand, str]] = {}
        self._void_keys: dict[str, tuple[str, str]] = {}
        self._sequence: int = 0
        self.calls: list[AdapterCall] = []

    @property
    def entry_count(self) -> int:
        """Number of entries recorded in the sandbox books."""
        return len(self._entries)

    def create_correcting_entry(
        self, command: CorrectingEntryCommand, idempotency_key: str
    ) -> AccountingEntry:
        """Post a balanced refund-lag correcting entry (replay-safe)."""
        op = "create_correcting_entry"
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            self._log(op, repr(idempotency_key), CallOutcome.VALIDATION_FAILURE, None)
            raise ValidationError("Field 'idempotency_key' must be a non-empty string.")
        if not isinstance(command, CorrectingEntryCommand):
            self._log(op, idempotency_key, CallOutcome.VALIDATION_FAILURE, None)
            raise ValidationError(
                f"Field 'command' must be a CorrectingEntryCommand, got {type(command).__name__}."
            )
        if command.exception_type != _REFUND_LAG_CODE:
            self._log(op, idempotency_key, CallOutcome.UNSUPPORTED_ACTION, None)
            if command.exception_type == _FEE_MISMATCH_CODE:
                raise UnsupportedActionError(
                    "Fee-mismatch is proposal-only: the adapter performs "
                    "no fee write. Correct the proposal instead."
                )
            raise UnsupportedActionError(
                f"create_correcting_entry serves refund-lag ({_REFUND_LAG_CODE}) "
                f"only, got {command.exception_type!r}."
            )
        try:
            total = self._validate_command(command)
        except ValidationError:
            self._log(op, idempotency_key, CallOutcome.VALIDATION_FAILURE, None)
            raise
        if self._consume_transient(op, idempotency_key, None):
            raise TransientError(
                f"Scripted transient 5xx for key {idempotency_key!r}: "
                "retry with the same key and byte-identical payload."
            )
        prior = self._create_keys.get(idempotency_key)
        if prior is not None:
            prior_command, prior_entry_id = prior
            if prior_command == command:
                self._log(op, idempotency_key, CallOutcome.IDEMPOTENCY_REPLAY, prior_entry_id)
                return self._entries[prior_entry_id].entry
            self._log(op, idempotency_key, CallOutcome.IDEMPOTENCY_CONFLICT, None)
            raise IdempotencyConflictError(
                f"Idempotency key {idempotency_key!r} was already used with "
                "a differing payload: no write performed."
            )
        self._sequence += 1
        entry_id = f"MOCK-{self._sequence:06d}"
        entry = AccountingEntry(
            entry_id=entry_id,
            tenant_id=command.tenant_id,
            exception_id=command.exception_id,
            exception_type=command.exception_type,
            status=EntryStatus.POSTED,
            currency=command.currency,
            lines=command.lines,
            total=total,
            source_reference=command.source_reference,
            memo=command.memo,
            idempotency_key=idempotency_key,
        )
        self._entries[entry_id] = _StoredEntry(entry=entry)
        self._create_keys[idempotency_key] = (command, entry_id)
        self._log(op, idempotency_key, CallOutcome.SUCCESS, entry_id)
        return entry

    def void_entry(self, entry_id: str, idempotency_key: str) -> AccountingEntry:
        """Void a posted entry exactly once (replay-safe)."""
        op = "void_entry"
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            self._log(op, repr(idempotency_key), CallOutcome.VALIDATION_FAILURE, None)
            raise ValidationError("Field 'idempotency_key' must be a non-empty string.")
        if not isinstance(entry_id, str) or not entry_id.strip():
            self._log(op, idempotency_key, CallOutcome.VALIDATION_FAILURE, None)
            raise ValidationError("Field 'entry_id' must be a non-empty string.")
        if self._consume_transient(op, idempotency_key, entry_id):
            raise TransientError(
                f"Scripted transient 5xx for key {idempotency_key!r}: "
                "retry with the same key and entry id."
            )
        prior = self._void_keys.get(idempotency_key)
        if prior is not None:
            prior_entry_id, _ = prior
            if prior_entry_id == entry_id:
                stored = self._entries.get(entry_id)
                if stored is None:  # pragma: no cover - defensive, unreachable
                    self._log(op, idempotency_key, CallOutcome.NOT_FOUND, entry_id)
                    raise EntryNotFoundError(f"Unknown entry id {entry_id!r}.")
                self._log(op, idempotency_key, CallOutcome.IDEMPOTENCY_REPLAY, entry_id)
                return stored.entry
            self._log(op, idempotency_key, CallOutcome.IDEMPOTENCY_CONFLICT, entry_id)
            raise IdempotencyConflictError(
                f"Idempotency key {idempotency_key!r} was already used for "
                f"entry {prior_entry_id!r}: no write performed."
            )
        stored = self._entries.get(entry_id)
        if stored is None:
            self._log(op, idempotency_key, CallOutcome.NOT_FOUND, entry_id)
            raise EntryNotFoundError(f"Unknown entry id {entry_id!r}.")
        if stored.entry.status is EntryStatus.VOIDED:
            self._log(op, idempotency_key, CallOutcome.VALIDATION_FAILURE, entry_id)
            raise ValidationError(f"Entry {entry_id!r} is already voided.")
        voided = AccountingEntry(
            entry_id=stored.entry.entry_id,
            tenant_id=stored.entry.tenant_id,
            exception_id=stored.entry.exception_id,
            exception_type=stored.entry.exception_type,
            status=EntryStatus.VOIDED,
            currency=stored.entry.currency,
            lines=stored.entry.lines,
            total=stored.entry.total,
            source_reference=stored.entry.source_reference,
            memo=stored.entry.memo,
            idempotency_key=idempotency_key,
        )
        stored.entry = voided
        self._void_keys[idempotency_key] = (entry_id, voided.entry_id)
        self._log(op, idempotency_key, CallOutcome.SUCCESS, entry_id)
        return voided

    def get_entry(self, entry_id: str) -> AccountingEntry:
        """Retrieve an entry, honouring the deterministic visibility lag."""
        op = "get_entry"
        stored = self._entries.get(entry_id) if isinstance(entry_id, str) else None
        if stored is None:
            self._log(op, _log_key(entry_id), CallOutcome.NOT_FOUND, _opt_id(entry_id))
            raise EntryNotFoundError(f"Unknown entry id {entry_id!r}.")
        if stored.reads < self._visibility_lag:
            stored.reads += 1
            self._log(op, entry_id, CallOutcome.NOT_YET_VISIBLE, entry_id)
            raise EntryNotFoundError(
                f"Entry {entry_id!r} not yet visible "
                f"(poll {stored.reads}/{self._visibility_lag}): "
                "write succeeded, re-read before any post-verify verdict."
            )
        self._log(op, entry_id, CallOutcome.SUCCESS, entry_id)
        return stored.entry

    def _validate_command(self, command: CorrectingEntryCommand) -> Decimal:
        """Enforce business rules; return the balanced total.

        Raises:
            ValidationError: On empty references, unknown or
                duplicated accounts, non-positive or two-sided lines,
                too few lines, or unbalanced books. No record is created.
        """
        if not command.tenant_id.strip():
            raise ValidationError("Field 'tenant_id' must be a non-empty string.")
        if not command.exception_id.strip():
            raise ValidationError("Field 'exception_id' must be a non-empty string.")
        if not command.source_reference.strip():
            raise ValidationError("Field 'source_reference' must be a non-empty string.")
        if len(command.lines) < 2:
            raise ValidationError("A correcting entry requires at least two lines.")
        for line in command.lines:
            if not line.account.strip():
                raise ValidationError("Line account must be a non-empty string.")
            if line.account not in SANDBOX_CHART_OF_ACCOUNTS:
                raise ValidationError(
                    f"Unknown account {line.account!r}: "
                    f"must be one of {sorted(SANDBOX_CHART_OF_ACCOUNTS)}."
                )
            if line.debit < Decimal("0") or line.credit < Decimal("0"):
                raise ValidationError(
                    f"Line {line.account!r} carries a negative side: amounts must be non-negative."
                )
            debit_positive = line.debit > Decimal("0")
            credit_positive = line.credit > Decimal("0")
            if debit_positive == credit_positive:
                raise ValidationError(
                    f"Line {line.account!r} must be one-sided: exactly one of "
                    "debit/credit positive, the other zero."
                )
        debits = sum((line.debit for line in command.lines), Decimal("0"))
        credit_total = sum((line.credit for line in command.lines), Decimal("0"))
        if debits != credit_total:
            raise ValidationError(f"Unbalanced entry: debits={debits} != credits={credit_total}.")
        if debits <= Decimal("0"):
            raise ValidationError("Correcting entry total must be positive.")
        return debits

    def _consume_transient(self, op: str, key: str, entry_id: str | None) -> bool:
        """Apply the scripted 5xx budget; True means the caller must raise."""
        remaining = self._transient_remaining.get(key, 0)
        if remaining <= 0:
            return False
        self._transient_remaining[key] = remaining - 1
        self._log(op, key, CallOutcome.TRANSIENT_5XX, entry_id)
        return True

    def _log(self, op: str, key: str, outcome: CallOutcome, entry_id: str | None) -> None:
        """Record every call with key and outcome for audit replay."""
        self.calls.append(AdapterCall(op=op, key=key, outcome=outcome, entry_id=entry_id))
        logger.info(
            "adapter_call op=%s key=%s outcome=%s entry_id=%s",
            op,
            key,
            outcome.value,
            entry_id,
        )


def _require_count(field_name: str, value: object) -> None:
    """Reject bools, non-ints, and negatives for script counters."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"Field '{field_name}' must be a non-negative int.")


def _log_key(entry_id: object) -> str:
    """Render a lookup key for the call log without assuming its type."""
    return entry_id if isinstance(entry_id, str) else repr(entry_id)


def _opt_id(entry_id: object) -> str | None:
    """Return the entry id for the call log, or None for junk input."""
    return entry_id if isinstance(entry_id, str) else None
