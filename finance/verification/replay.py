"""P6-08 track B in-memory replay store (F31, F40, F64).

One execution holds at most one terminal verification identity: the first
record stands, identical re-records return the original, and differing
re-records refuse with ``VERIFY_DOUBLE_MINT_REFUSED``. A lock guards the
map; the store performs no I/O and reads no clock.
"""

from __future__ import annotations

from threading import Lock

from finance.domain.verification import VerificationReport
from finance.verification.minter import MintRefused
from finance.verification.reason_codes import VERIFY_DOUBLE_MINT_REFUSED

__all__ = ["ReplayStore"]


def _same_identity(first: VerificationReport, second: VerificationReport) -> bool:
    """Return True when both reports share one verification identity.

    Mirrors the minter predicate so the store and the minter agree on what
    counts as a replay: situation, execution, totals, and verdict match
    while checked_at is free to be a fresh stamp.
    """
    return (
        first.situation_id == second.situation_id
        and first.execution_id == second.execution_id
        and first.legacy_total_after == second.legacy_total_after
        and first.variance_after == second.variance_after
        and first.verdict is second.verdict
    )


class ReplayStore:
    """Execution-keyed recorded-report map with first-record-stands (F64)."""

    def __init__(self) -> None:
        """Create an empty store; no state is shared between instances."""
        self._lock = Lock()
        self._recorded: dict[str, VerificationReport] = {}

    def lookup(self, execution_id: str) -> VerificationReport | None:
        """Return the recorded report for the execution, or None when absent."""
        with self._lock:
            return self._recorded.get(execution_id)

    def record(self, report: VerificationReport) -> VerificationReport:
        """Record the report under its execution_id with F64 refusal.

        Args:
            report: Candidate terminal verification identity.

        Returns:
            The newly stored report, or the original on an identical replay.

        Raises:
            MintRefused: When the key already holds differing content; the
                first record stands and no second identity is created.
        """
        with self._lock:
            existing = self._recorded.get(report.execution_id)
            if existing is None:
                self._recorded[report.execution_id] = report
                return report
            if _same_identity(existing, report):
                return existing
            raise MintRefused(
                VERIFY_DOUBLE_MINT_REFUSED,
                f"execution {report.execution_id!r} already holds a report.",
            )
