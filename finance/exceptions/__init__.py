"""P3.2 versioned Exception Aggregate + CAS persistence + audit.

Implements the frozen ``exception-ops`` aggregate boundary: one aggregate
per actionable reconciliation break, code-owned transitions guarded by
``expected_state_version``, atomic compare-and-swap persistence, and an
append-only audit trail. P3.2 covers the investigation chain only, up to
``AWAITING_APPROVAL`` — approve / execute / close arrive in later phases.

Only the Python standard library plus P1 reconciliation contracts and
SQLAlchemy are used. This package imports nothing from ``apps/`` or
``agents/``.
"""

from finance.exceptions.aggregate import ExceptionAggregate
from finance.exceptions.approval import ApprovalPin
from finance.exceptions.errors import (
    ApprovalSkewError,
    ConcurrencyConflictError,
    ExceptionAggregateError,
    IllegalTransitionError,
)
from finance.exceptions.models import Base, ExceptionAuditRow, ExceptionRow
from finance.exceptions.repository import ExceptionRepository
from finance.exceptions.states import (
    ALLOWED_TRANSITIONS,
    BANNED_TRANSITIONS,
    ExceptionState,
    Severity,
)

__all__ = [
    "ALLOWED_TRANSITIONS",
    "ApprovalPin",
    "ApprovalSkewError",
    "BANNED_TRANSITIONS",
    "Base",
    "ConcurrencyConflictError",
    "ExceptionAggregate",
    "ExceptionAggregateError",
    "ExceptionAuditRow",
    "ExceptionRepository",
    "ExceptionRow",
    "ExceptionState",
    "IllegalTransitionError",
    "Severity",
]
