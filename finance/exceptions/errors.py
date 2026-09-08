"""Error taxonomy for the P3.2 Exception Aggregate boundary.

All errors are deterministic, dependency-free, and carry no I/O. Three
failure modes are frozen: stale-version writes, illegal state moves, and
approval/proposal skew (reserved for the P3.4 approval phase).

Only the Python standard library is used.
"""

from __future__ import annotations


class ExceptionAggregateError(Exception):
    """Base class for all exception-aggregate errors."""


class ConcurrencyConflictError(ExceptionAggregateError):
    """Raised when ``expected_state_version`` (or state) is stale.

    No mutation is applied. Carries the expected versus actual versions
    so callers can re-read and retry with a fresh snapshot.

    Attributes:
        exception_id: Aggregate identity the write targeted.
        expected_version: Version the caller presented.
        actual_version: Current version at rejection time.
        detail: Human-readable cause (stale version, state mismatch).
    """

    def __init__(
        self,
        exception_id: str,
        expected_version: int,
        actual_version: int,
        detail: str = "stale expected_state_version",
    ) -> None:
        """Record the version skew and build the message."""
        self.exception_id = exception_id
        self.expected_version = expected_version
        self.actual_version = actual_version
        self.detail = detail
        super().__init__(
            f"CONCURRENCY_CONFLICT for {exception_id}: {detail} "
            f"(expected={expected_version} actual={actual_version})"
        )


class IllegalTransitionError(ExceptionAggregateError, ValueError):
    """Raised when a requested state move is not a legal SM-1 transition.

    Covers banned pairs (``INVESTIGATING -> EXECUTING``,
    ``PROPOSED -> EXECUTING``, ``FAILED -> CLOSED``), unlisted pairs, and
    P3.2 out-of-scope targets (approve / execute / close, owned by later
    phases). The aggregate is left unmutated.

    Attributes:
        exception_id: Aggregate identity the move targeted.
        from_state: Current state at rejection time.
        to_state: Requested target state.
        reason: Why the move was refused.
    """

    def __init__(
        self,
        exception_id: str,
        from_state: str,
        to_state: str,
        reason: str = "transition not in SM-1",
    ) -> None:
        """Record the rejected move and build the message."""
        self.exception_id = exception_id
        self.from_state = from_state
        self.to_state = to_state
        self.reason = reason
        super().__init__(
            f"Illegal transition for {exception_id}: {from_state} -> {to_state} rejected ({reason})"
        )


class ApprovalSkewError(ExceptionAggregateError, ValueError):
    """Reserved: approval triple does not pin the current proposal.

    Raised (from P3.4 on) when the presented approval's pinned
    ``(proposal_id, version, content_hash)`` triple does not exactly match
    the aggregate's current proposal slot. Reserved in P3.2 so the shape
    exists before any approval API does.
    """
