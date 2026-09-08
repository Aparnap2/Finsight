"""SM-1 state enum and transition tables for the Exception Aggregate.

Mirrors the frozen ``SM-1 — Allowed State-Machine Transitions`` table from
the reconciliation spec. ``ALLOWED_TRANSITIONS`` is the single source of
truth for legal moves; ``BANNED_TRANSITIONS`` names the explicitly
forbidden pairs (``INVESTIGATING -> EXECUTING``, ``PROPOSED -> EXECUTING``,
``FAILED -> CLOSED``) so rejections can cite the ban. ``P32_TARGETS`` bounds
the P3.2 implementation to the investigation chain ending at
``AWAITING_APPROVAL`` — later phases extend the reachable set without
changing SM-1.

Only the Python standard library is used.
"""

from enum import StrEnum


class ExceptionState(StrEnum):
    """Lifecycle states of an exception case (frozen SM-1 vocabulary)."""

    RECEIVED = "RECEIVED"
    NORMALIZED = "NORMALIZED"
    RECONCILING = "RECONCILING"
    MATCHED = "MATCHED"
    EXCEPTION = "EXCEPTION"
    INVESTIGATING = "INVESTIGATING"
    EVIDENCE_READY = "EVIDENCE_READY"
    EVIDENCE_VERIFIED = "EVIDENCE_VERIFIED"
    PROPOSED = "PROPOSED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTING = "EXECUTING"
    POST_VERIFYING = "POST_VERIFYING"
    EXECUTION_VERIFIED = "EXECUTION_VERIFIED"
    FAILED = "FAILED"
    CLOSED = "CLOSED"
    ESCALATED = "ESCALATED"


class Severity(StrEnum):
    """Materiality-derived severity carried as aggregate metadata."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


ALLOWED_TRANSITIONS: frozenset[tuple[ExceptionState, ExceptionState]] = frozenset(
    {
        (ExceptionState.RECEIVED, ExceptionState.NORMALIZED),
        (ExceptionState.NORMALIZED, ExceptionState.RECONCILING),
        (ExceptionState.RECONCILING, ExceptionState.MATCHED),
        (ExceptionState.MATCHED, ExceptionState.CLOSED),
        (ExceptionState.RECONCILING, ExceptionState.EXCEPTION),
        (ExceptionState.EXCEPTION, ExceptionState.INVESTIGATING),
        (ExceptionState.INVESTIGATING, ExceptionState.EVIDENCE_READY),
        (ExceptionState.EVIDENCE_READY, ExceptionState.EVIDENCE_VERIFIED),
        (ExceptionState.EVIDENCE_VERIFIED, ExceptionState.PROPOSED),
        (ExceptionState.PROPOSED, ExceptionState.AWAITING_APPROVAL),
        (ExceptionState.AWAITING_APPROVAL, ExceptionState.APPROVED),
        (ExceptionState.AWAITING_APPROVAL, ExceptionState.REJECTED),
        (ExceptionState.APPROVED, ExceptionState.EXECUTING),
        (ExceptionState.EXECUTING, ExceptionState.POST_VERIFYING),
        (ExceptionState.EXECUTING, ExceptionState.FAILED),
        (ExceptionState.POST_VERIFYING, ExceptionState.EXECUTION_VERIFIED),
        (ExceptionState.POST_VERIFYING, ExceptionState.FAILED),
        (ExceptionState.EXECUTION_VERIFIED, ExceptionState.CLOSED),
        (ExceptionState.REJECTED, ExceptionState.CLOSED),
        (ExceptionState.FAILED, ExceptionState.ESCALATED),
    }
)

BANNED_TRANSITIONS: frozenset[tuple[ExceptionState, ExceptionState]] = frozenset(
    {
        (ExceptionState.INVESTIGATING, ExceptionState.EXECUTING),
        (ExceptionState.PROPOSED, ExceptionState.EXECUTING),
        (ExceptionState.FAILED, ExceptionState.CLOSED),
    }
)

P32_TARGETS: frozenset[ExceptionState] = frozenset(
    {
        ExceptionState.INVESTIGATING,
        ExceptionState.EVIDENCE_READY,
        ExceptionState.EVIDENCE_VERIFIED,
        ExceptionState.PROPOSED,
        ExceptionState.AWAITING_APPROVAL,
    }
)

EVIDENCE_SEALED_FROM: frozenset[ExceptionState] = frozenset(
    {
        ExceptionState.EVIDENCE_VERIFIED,
        ExceptionState.PROPOSED,
        ExceptionState.AWAITING_APPROVAL,
        ExceptionState.APPROVED,
        ExceptionState.REJECTED,
        ExceptionState.EXECUTING,
        ExceptionState.POST_VERIFYING,
        ExceptionState.EXECUTION_VERIFIED,
        ExceptionState.FAILED,
        ExceptionState.CLOSED,
        ExceptionState.ESCALATED,
    }
)
