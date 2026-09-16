"""Sandbox execution safety boundary: guard decisions and idempotency ledger.

``ExecutionGuard`` is the last-mile tripwire against autonomous financial
action: every execution must present a pinned approval command, and any
bypass attempt is counted in ``unsafe`` instead of executed.
``IdempotencyStore`` is the crash-safe key ledger backing replay safety.

Only the Python standard library plus SQLAlchemy are used. This package
imports nothing from ``apps/``, ``agents/``, or ``finance/``.
"""

from shared.safety.execution_guard import (
    ExecutionCommand,
    ExecutionGuard,
    GuardCommand,
    GuardDecision,
    GuardRequest,
)
from shared.safety.idempotency import IdempotencyStore
from shared.safety.secrets import (
    REDACTED,
    REDACTED_EMAIL,
    REDACTED_SECRET,
    contains_secret_literal,
    hash_pii,
    redact_mapping,
    redact_value,
    scrub_text,
)

__all__ = [
    "ExecutionCommand",
    "ExecutionGuard",
    "GuardCommand",
    "GuardDecision",
    "GuardRequest",
    "IdempotencyStore",
    "REDACTED",
    "REDACTED_EMAIL",
    "REDACTED_SECRET",
    "contains_secret_literal",
    "hash_pii",
    "redact_mapping",
    "redact_value",
    "scrub_text",
]
