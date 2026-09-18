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
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Column, Engine, MetaData, String, Table
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from finance.approval.refusals import ApprovalRefused, RefusalCode

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
    Column("batch_id", String, nullable=True),
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

    batch_id: str | None = None
    """Bound logical batch id, set once (A2/X21); null until bound."""


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

    The in-memory mapping is the unit-determinism backend; pass a
    SQLAlchemy ``Engine`` for the durable backend reusing
    ``reservation_table`` with identical semantics (single conditional
    insert, losers read the winner). The durable path is the A2/HOLD-3
    authority: a process restart must consult it (same database), never
    reconstruct bindings from scratch.
    """

    def __init__(self, engine: Engine | None = None) -> None:
        """Bind to ``engine`` (creating tables) or start empty memory."""
        self._engine = engine
        if engine is not None:
            reservation_table.create(engine, checkfirst=True)
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
        if self._engine is not None:
            return self._claim_sql(execution_id, bound)
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

    def _row_to_reservation(self, row: Mapping[str, Any]) -> Reservation:
        """Rebuild a SQL row mapping into the reservation model."""
        return Reservation(
            execution_id=row["execution_id"],
            binding_digest=row["binding_digest"],
            company_id=row["company_id"],
            situation_id=row["situation_id"],
            batch_id=row["batch_id"],
            state=ReservationState(row["state"]),
            outcome=row["outcome"],
        )

    def _claim_sql(
        self, execution_id: str, bound: ReservationBinding
    ) -> ClaimResult:
        """Claim via conditional insert; losers read the winner's row."""
        assert self._engine is not None
        with Session(self._engine) as session:
            try:
                session.execute(
                    reservation_table.insert().values(
                        execution_id=execution_id,
                        binding_digest=bound.binding_digest,
                        company_id=bound.company_id,
                        situation_id=bound.situation_id,
                        batch_id=None,
                        state=ReservationState.RESERVED.value,
                        outcome=None,
                    )
                )
                session.commit()
            except IntegrityError:
                session.rollback()
            winner = session.execute(
                reservation_table.select().where(
                    reservation_table.c.execution_id == execution_id
                )
            ).mappings().first()
            if winner is None:  # pragma: no cover - insert+select race guard
                raise KeyError(f"No reservation row for {execution_id!r}.")
            row = self._row_to_reservation(dict(winner))
            if row.binding_digest != bound.binding_digest:
                raise ApprovalRefused(
                    RefusalCode.CROSS_CASE_REFUSED,
                    "E1",
                    "Pre-existing row carries a foreign authorization "
                    "binding; escalate, never merge.",
                )
            created = (
                row.state is ReservationState.RESERVED and row.outcome is None
            )
            return ClaimResult(
                status="CLAIMED" if created else "REPLAY",
                reservation=row,
                outcome=row.outcome,
            )

    def bind_batch(self, execution_id: str, batch_id: str) -> Reservation:
        """Bind the logical batch id once (X21/A2); later ids refuse.

        The binding is set-once-or-verify on both backends: a second,
        different batch id for one execution id refuses instead of
        forking the execution identity.

        Args:
            execution_id: Token ``idempotency_key``.
            batch_id: Logical batch id to bind (A1 logical form).

        Returns:
            The row carrying the binding.

        Raises:
            KeyError: When no claim exists for ``execution_id``.
            ApprovalRefused: ``AUTHORIZATION_REPLAYED`` on a second,
                different batch id for one key.
        """
        if self._engine is not None:
            return self._bind_sql(execution_id, batch_id)
        with self._lock:
            row = self._rows[execution_id]
            if row.batch_id is not None and row.batch_id != batch_id:
                raise ApprovalRefused(
                    RefusalCode.AUTHORIZATION_REPLAYED,
                    "E3",
                    f"Second batch {batch_id!r} for one execution id; "
                    "a new id needs a new authorization cycle.",
                )
            if row.batch_id is None:
                row = row.model_copy(update={"batch_id": batch_id})
                self._rows[execution_id] = row
            return row

    def _bind_sql(self, execution_id: str, batch_id: str) -> Reservation:
        """Predicated batch bind: set once, verify after, refuse forks."""
        assert self._engine is not None
        with Session(self._engine) as session:
            updated = (
                session.query(reservation_table)
                .filter(
                    reservation_table.c.execution_id == execution_id,
                    reservation_table.c.batch_id.is_(None),
                )
                .update(
                    {reservation_table.c.batch_id: batch_id},
                    synchronize_session="fetch",
                )
            )
            session.commit()
            current = session.execute(
                reservation_table.select().where(
                    reservation_table.c.execution_id == execution_id
                )
            ).mappings().first()
            if current is None:
                raise KeyError(f"No reservation row for {execution_id!r}.")
            row = self._row_to_reservation(dict(current))
            if updated == 0 and row.batch_id != batch_id:
                raise ApprovalRefused(
                    RefusalCode.AUTHORIZATION_REPLAYED,
                    "E3",
                    f"Second batch {batch_id!r} for one execution id; "
                    "a new id needs a new authorization cycle.",
                )
            return row

    def receipt_status(self, execution_id: str) -> Reservation | None:
        """Return the reservation row for crash-resume lookup (A2).

        Args:
            execution_id: Token ``idempotency_key`` to look up.

        Returns:
            The recorded row, or null when no claim exists for the key.
        """
        if self._engine is not None:
            with Session(self._engine) as session:
                found = session.execute(
                    reservation_table.select().where(
                        reservation_table.c.execution_id == execution_id
                    )
                ).mappings().first()
                return self._row_to_reservation(dict(found)) if found else None
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
        if self._engine is not None:
            with Session(self._engine) as session:
                matched = (
                    session.query(reservation_table)
                    .filter(
                        reservation_table.c.execution_id == execution_id,
                        reservation_table.c.state == ReservationState.RESERVED.value,
                    )
                    .update(
                        {reservation_table.c.state: ReservationState.RECEIPT_RECORDED.value},
                        synchronize_session="fetch",
                    )
                )
                session.commit()
                current = self.receipt_status(execution_id)
                if current is None:
                    raise KeyError(f"No reservation row for {execution_id!r}.")
                if matched == 0:
                    return current
                return current
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
        state = (
            ReservationState(outcome)
            if outcome in ReservationState.__members__
            else ReservationState.ACCEPTED
        )
        if self._engine is not None:
            with Session(self._engine) as session:
                matched = (
                    session.query(reservation_table)
                    .filter(reservation_table.c.execution_id == execution_id)
                    .update(
                        {
                            reservation_table.c.state: state.value,
                            reservation_table.c.outcome: outcome,
                        },
                        synchronize_session="fetch",
                    )
                )
                session.commit()
                if matched == 0:
                    raise KeyError(f"No reservation row for {execution_id!r}.")
                current = self.receipt_status(execution_id)
                assert current is not None
                return current
        with self._lock:
            row = self._rows[execution_id]
            recorded = row.model_copy(update={"state": state, "outcome": outcome})
            self._rows[execution_id] = recorded
            return recorded
