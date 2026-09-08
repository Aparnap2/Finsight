"""Deterministic error taxonomy for the sandbox accounting boundary.

All errors are dependency-free and carry no I/O. They distinguish the
failure modes required by the frozen ``exception-ops`` spec: float money
input, non-retryable validation failure, scripted transient 5xx,
scoped-action rejection (fee-mismatch is proposal-only), read misses
(including the delayed-visibility window), and idempotency conflicts.

Only the Python standard library is used.
"""

from __future__ import annotations


class AccountingError(Exception):
    """Base class for all sandbox accounting errors."""


class FloatMoneyError(AccountingError, TypeError):
    """Raised when a monetary value arrives as ``float`` (or ``bool``).

    Every trust boundary in this package accepts ``Decimal`` but never
    ``float``, mirroring the ``MoneyDecimal`` boundary used elsewhere in
    FinSight.
    """


class ValidationError(AccountingError, ValueError):
    """Non-retryable validation failure: no record is created.

    Raised for invalid accounts, unbalanced lines, missing references,
    malformed keys, or double-void attempts. The adapter stores nothing
    and reserves no idempotency key, so a corrected retry is safe.
    """


class TransientError(AccountingError, RuntimeError):
    """Scripted transient 5xx: safe to retry with the same key and payload.

    Raised only while a constructor-scripted failure budget remains for
    the presented idempotency key. No record is created and the key is
    not reserved, so the retry path cannot duplicate.
    """


class UnsupportedActionError(AccountingError, ValueError):
    """Scoped-action rejection: the operation is outside adapter scope.

    Fee-mismatch breaks are proposal-only and MUST NOT reach the books;
    any fee-typed command presented to create is rejected here with no
    record and no state change.
    """


class EntryNotFoundError(AccountingError, LookupError):
    """Read miss: unknown entry id or inside the delayed-visibility window.

    A write that succeeded may still miss on ``get_entry`` until the
    configured number of lag reads has elapsed. Callers MUST poll and
    MUST NOT treat a miss as proof of a failed write.
    """


class IdempotencyConflictError(AccountingError, ValueError):
    """Same idempotency key presented with a differing payload.

    The request is rejected with no write. Replays MUST reuse the key
    with a byte-identical payload to receive the original outcome.
    """
