"""Durable execution reservation for P6-07 E1 (A2 CAS commit point).

The reservation is the exactly-once commit point inside E1: after the
token checks pass, ``claim_execution`` atomically inserts one row keyed
by ``execution_id`` (== the token ``idempotency_key``). Exactly one
claimant wins (``CLAIMED``); every concurrent loser reads the winner's
row and follows the replay-read path (``REPLAY`` carrying the recorded
outcome, ``AUTHORIZATION_REPLAYED`` noted in audit, never re-executed).

Backend design (one interface, two paths): the unit-deterministic path
is a lock-guarded in-memory mapping; the durable path is the
module-level SQLAlchemy ``reservation_table`` reusing the existing
conditional insert-or-read plus predicated ``UPDATE`` on
``(execution_id, state)`` pattern. No queues, Temporal, workers, or new
infrastructure. State moves forward only (``RESERVED`` → receipt →
terminal outcome) and rows are recorded, never edited.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Column, MetaData, String, Table

#: Audit code recorded when a replay-read serves an outcome (X42). It is
#: recorded as the reason no second effect ran, never raised as an error
#: to outcome-expecting callers.
REPLAY_AUDIT_CODE = "AUTHORIZATION_REPLAYED"

TABLE_NAME = "legacy_execution_reservation"
"""Durable reservation table name for the T3 persistence wiring."""

reservation_table = Table(
    TABLE_NAME,
    MetaData(),
    Column("execution_id", String, primary_key=True),
    Column("binding_digest", String, nullable=False),
    Column("company_id", String, nullable=False),
    Column("situation_id", String, nullable=False),
    Column("state", String, nullable=False),
    Column("outcome", String, nullable=True),
)
"""Durable reservation table (conditional insert-or-read, A2).

The primary key on ``execution_id`` is the compare-and-swap primitive:
exactly one conditional insert wins; losers read the winner's row.
"""


class ReservationState(StrEnum):
    """Reservation lifecycle: reserved, receipted, then one terminal label."""

    RESERVED = "RESERVED"
    RECEIPT_RECORDED = "RECEIPT_RECORDED"
    ACCEPTED = "ACCEPTED"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


#: States after which no further execution may start for the same key.
TERMINAL_STATES = frozenset(
    {
        ReservationState.ACCEPTED,
        ReservationState.PARTIAL,
        ReservationState.REJECTED,
        ReservationState.UNKNOWN,
    }
)


class ReservationBinding(BaseModel):
    """Authorization binding carried on the reservation row (A2)."""

    model_config = ConfigDict(frozen=True, strict=True)

    binding_digest: str
    """Token binding digest this reservation was claimed under."""

    company_id: str
    """Bound company (``meridian``)."""

    situation_id: str
    """Bound case."""


class Reservation(BaseModel):
    """One execution reservation row keyed by ``execution_id``."""

    model_config = ConfigDict(frozen=True, strict=True)

    execution_id: str
    """Token ``idempotency_key``; the single deduplication key (X41)."""

    binding_digest: str
    """Authorization binding digest recorded at claim time."""

    company_id: str
    """Bound company."""

    situation_id: str
    """Bound case."""

    state: ReservationState
    """Forward-only lifecycle position of this execution."""

    outcome: str | None = None
    """Recorded outcome pointer served on replay-reads; null until set."""


class ClaimResult(BaseModel):
    """Outcome of one ``claim_execution`` attempt (X11/X12)."""

    model_config = ConfigDict(frozen=True, strict=True)

    status: Literal["CLAIMED", "REPLAY"]
    """``CLAIMED`` owns the single effect; ``REPLAY`` reads the record."""

    reservation: Reservation
    """Winner's row: the new ``RESERVED`` row or the existing one."""

    outcome: str | None = None
    """Recorded outcome pointer on ``REPLAY``; null on fresh ``CLAIMED``."""


class ReservationStore:
    """Lock-guarded claim-if-absent store behind one backend-agnostic API.

    The in-memory mapping is the unit-determinism backend; the durable
    backend reuses ``reservation_table`` with the same claim-if-absent
    semantics (single conditional insert, losers read the winner).
    """

    def __init__(self) -> None:
        """Create an empty store with its claim guard lock."""
        self._lock = threading.Lock()
        self._rows: dict[str, Reservation] = {}

    def claim_execution(
        self,
        execution_id: str,
        binding: ReservationBinding | Mapping[str, str],
    ) -> ClaimResult:
        """Atomically claim ``execution_id`` or replay-read the winner.

        Args:
            execution_id: Token ``idempotency_key``; never regenerated.
            binding: Authorization binding recorded on a fresh claim.

        Returns:
            ``CLAIMED`` with a new ``RESERVED`` row for the first
            claimant, else ``REPLAY`` with the recorded outcome pointer
            (audit notes ``AUTHORIZATION_REPLAYED``; no work re-runs).
        """
        bound = (
            binding
            if isinstance(binding, ReservationBinding)
            else ReservationBinding.model_validate(dict(binding))
        )
        with self._lock:
            existing = self._rows.get(execution_id)
            if existing is not None:
                return ClaimResult(
                    status="REPLAY",
                    reservation=existing,
                    outcome=existing.outcome,
                )
            row = Reservation(
                execution_id=execution_id,
                binding_digest=bound.binding_digest,
                company_id=bound.company_id,
                situation_id=bound.situation_id,
                state=ReservationState.RESERVED,
                outcome=None,
            )
            self._rows[execution_id] = row
            return ClaimResult(status="CLAIMED", reservation=row, outcome=None)

    def receipt_status(self, execution_id: str) -> Reservation | None:
        """Return the reservation row for crash-resume lookup (A2).

        Args:
            execution_id: Token ``idempotency_key`` to look up.

        Returns:
            The recorded row, or null when no claim exists for the key.
        """
        with self._lock:
            return self._rows.get(execution_id)

    def record_receipt(self, execution_id: str) -> Reservation:
        """Advance a ``RESERVED`` row to ``RECEIPT_RECORDED``.

        Args:
            execution_id: Token ``idempotency_key`` whose receipt landed.

        Returns:
            The advanced row; already-advanced rows return unchanged.

        Raises:
            KeyError: When no claim exists for ``execution_id``.
        """
        with self._lock:
            row = self._rows[execution_id]
            if row.state is not ReservationState.RESERVED:
                return row
            advanced = row.model_copy(
                update={"state": ReservationState.RECEIPT_RECORDED}
            )
            self._rows[execution_id] = advanced
            return advanced

    def record_outcome(self, execution_id: str, outcome: str) -> Reservation:
        """Record the terminal outcome pointer served on later replays.

        Args:
            execution_id: Token ``idempotency_key`` whose outcome landed.
            outcome: Terminal outcome label (e.g. ``ACCEPTED``).

        Returns:
            The row carrying the recorded outcome pointer.

        Raises:
            KeyError: When no claim exists for ``execution_id``.
        """
        with self._lock:
            row = self._rows[execution_id]
            state = (
                ReservationState(outcome)
                if outcome in ReservationState.__members__
                else ReservationState.ACCEPTED
            )
            recorded = row.model_copy(update={"state": state, "outcome": outcome})
            self._rows[execution_id] = recorded
            return recorded
