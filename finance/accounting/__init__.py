"""Sandbox QuickBooks accounting boundary (P3.1 mock adapter).

Exposes the ``AccountingAdapter`` interface contract with a
deterministic injectable mock. Sandbox only: no network, no
credentials, no production books.
"""

from finance.accounting.adapter import (
    AccountingAdapter,
    AccountingEntry,
    AdapterCall,
    CallOutcome,
    EntryStatus,
)
from finance.accounting.commands import (
    KNOWN_EXCEPTION_CODES,
    CorrectingEntryCommand,
    JournalLine,
)
from finance.accounting.errors import (
    AccountingError,
    EntryNotFoundError,
    FloatMoneyError,
    IdempotencyConflictError,
    TransientError,
    UnsupportedActionError,
    ValidationError,
)
from finance.accounting.mock import SANDBOX_CHART_OF_ACCOUNTS, MockQuickBooksAdapter

__all__ = [
    "KNOWN_EXCEPTION_CODES",
    "SANDBOX_CHART_OF_ACCOUNTS",
    "AccountingAdapter",
    "AccountingEntry",
    "AccountingError",
    "AdapterCall",
    "CallOutcome",
    "CorrectingEntryCommand",
    "EntryNotFoundError",
    "EntryStatus",
    "FloatMoneyError",
    "IdempotencyConflictError",
    "JournalLine",
    "MockQuickBooksAdapter",
    "TransientError",
    "UnsupportedActionError",
    "ValidationError",
]
