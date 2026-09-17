"""Append-only audit record for FinancialSituation lifecycle transitions.

The audit trail is a *record* of what the lifecycle did — never a driver of
transitions. :func:`emit_for_transition` is a pure constructor (no I/O, zero
network, no LLM): given the aggregate before and after a move, plus a
caller-supplied tz-aware timestamp and actor, it returns a frozen
:class:`AuditEvent` with a deterministic id and a ``Decimal`` variance
snapshot. :class:`AuditLog` is an in-memory append-only collector with
ordered read-back, per-situation filtering, and a cheap hash-chain for
tamper-evidence. The chain is optional: events link via ``prev_hash`` and
:func:`AuditLog.verify_chain` reports whether the stored order is intact.
"""

import hashlib
from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from finance.domain._types import MoneyDecimal
from finance.domain.financial_situation import FinancialSituation, SituationStatus


def _event_id(
    situation_id: str,
    from_status: SituationStatus,
    to_status: SituationStatus,
    at: datetime,
) -> str:
    """Return the deterministic id for a transition event.

    The id is the hex sha256 of ``situation_id + from + to + at`` joined
    with ``|`` separators, so identical inputs always yield the identical
    id and any input change yields a different one.
    """
    preimage = "|".join(
        (situation_id, from_status.value, to_status.value, at.isoformat())
    )
    return hashlib.sha256(preimage.encode("utf-8")).hexdigest()


class AuditEvent(BaseModel):
    """One immutable record of a single lifecycle transition.

    The event pins who moved which situation from which state to which
    state, when (caller-supplied tz-aware ``at``), and the post-transition
    variance in exact ``Decimal`` arithmetic. ``prev_hash`` optionally
    links to the preceding event id for tamper-evidence; it defaults to
    empty and is filled by :meth:`AuditLog.append` when the caller leaves
    it blank.
    """

    model_config = ConfigDict(frozen=True, strict=True)

    event_id: str
    """Deterministic sha256 of situation_id + from + to + at."""

    situation_id: str
    """Parent case id, shape ``FS-YYYY-MMDD-NNNNN``."""

    company_id: str = "meridian"
    """Always ``meridian``; the single-company boundary follows the base."""

    from_status: SituationStatus
    """Lifecycle state before the transition."""

    to_status: SituationStatus
    """Lifecycle state after the transition."""

    at: datetime
    """Caller-supplied transition time; must be tz-aware."""

    actor: str
    """Who performed the transition (human id or system principal)."""

    variance_snapshot: MoneyDecimal | None = None
    """Post-transition variance (books minus provider net), Decimal-only."""

    prev_hash: str = ""
    """Event id of the preceding record; empty when unlinked."""

    version: int | None = None
    """Stored version this event ships with (D4a parity with durable rows).

    Optional so existing volatile-only flows keep working; when set it
    must be ``>= 1``. The repository requires it on durable writes.
    """

    @field_validator("event_id")
    @classmethod
    def _validate_event_id(cls, value: str) -> str:
        """Require a non-empty deterministic event id."""
        if not value.strip():
            raise ValueError("event_id must be a non-empty string.")
        return value

    @field_validator("company_id")
    @classmethod
    def _validate_company_id(cls, value: str) -> str:
        """Enforce the single-company boundary (meridian only)."""
        if value != "meridian":
            raise ValueError(
                "company_id must be 'meridian' (single-company boundary), "
                f"got {value!r}."
            )
        return value

    @field_validator("version")
    @classmethod
    def _validate_version(cls, value: int | None) -> int | None:
        """Require a positive version whenever one is pinned."""
        if value is not None and value < 1:
            raise ValueError(
                "version must be >= 1 when set, "
                f"got {value!r}."
            )
        return value

    @field_validator("at")
    @classmethod
    def _validate_at_tz_aware(cls, value: datetime) -> datetime:
        """Reject tz-naive timestamps; the caller must supply tz-aware time."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("at must be a tz-aware datetime (naive rejected).")
        return value

    @field_validator("actor")
    @classmethod
    def _validate_actor(cls, value: str) -> str:
        """Require a non-blank actor; anonymous transitions are rejected."""
        if not value.strip():
            raise ValueError("actor must be a non-empty string.")
        return value

    @model_validator(mode="after")
    def _validate_statuses_differ(self) -> "AuditEvent":
        """Reject no-op records: a transition must move state."""
        if self.from_status == self.to_status:
            raise ValueError(
                f"from_status and to_status must differ, got {self.from_status}."
            )
        return self


def emit_for_transition(
    situation_before: FinancialSituation,
    situation_after: FinancialSituation,
    *,
    at: datetime,
    actor: str,
) -> AuditEvent:
    """Build the audit event for a completed transition (pure, no I/O).

    The function records what the lifecycle did; it never gates or drives
    the move itself, so it does not consult the allowed-transition table —
    any genuinely performed move (including sibling-owned fast paths) can
    be recorded. It does enforce record integrity: both snapshots must
    belong to the same situation and company (``company_id`` is
    immutable), the actor must be non-blank, and ``at`` must be tz-aware.

    Args:
        situation_before: Aggregate snapshot before the move.
        situation_after: Aggregate snapshot after the move.
        at: Caller-supplied tz-aware transition time.
        actor: Human id or system principal that performed the move.

    Returns:
        A frozen event with deterministic id and Decimal variance snapshot.

    Raises:
        ValueError: If the snapshots disagree on situation or company id,
            if the actor is blank, or if either status did not move.
    """
    if not isinstance(actor, str) or not actor.strip():
        raise ValueError("actor must be a non-empty string.")
    if situation_before.situation_id != situation_after.situation_id:
        raise ValueError(
            "Cannot audit a transition across situations: "
            f"{situation_before.situation_id!r} != "
            f"{situation_after.situation_id!r}."
        )
    if situation_before.company_id != situation_after.company_id:
        raise ValueError(
            "company_id is immutable across a transition: "
            f"{situation_before.company_id!r} != "
            f"{situation_after.company_id!r}."
        )
    variance: Decimal = situation_after.variance()
    return AuditEvent(
        event_id=_event_id(
            situation_after.situation_id,
            situation_before.status,
            situation_after.status,
            at,
        ),
        situation_id=situation_after.situation_id,
        company_id=situation_after.company_id,
        from_status=situation_before.status,
        to_status=situation_after.status,
        at=at,
        actor=actor,
        variance_snapshot=variance,
    )


class AuditLog:
    """Append-only in-memory collector of audit events.

    Events are stored in append order and read back as immutable tuples;
    the log exposes no delete, remove, clear, pop, or item-assignment API,
    so recorded history cannot be rewritten. When an appended event leaves
    ``prev_hash`` blank and the log is non-empty, the log links it to the
    previous event id, keeping the default chain verifiable; a caller-set
    ``prev_hash`` is preserved as-is so forged links stay detectable.
    """

    def __init__(self) -> None:
        """Create an empty log."""
        self._events: list[AuditEvent] = []

    def append(self, event: AuditEvent) -> AuditEvent:
        """Append one event, auto-linking ``prev_hash`` when blank.

        Args:
            event: The event to record.

        Returns:
            The stored event (a linked copy when auto-linking applied).
        """
        if not isinstance(event, AuditEvent):
            raise TypeError(
                f"AuditLog only stores AuditEvent, got {type(event).__name__}."
            )
        stored = event
        if self._events and not event.prev_hash:
            stored = event.model_copy(
                update={"prev_hash": self._events[-1].event_id}
            )
        self._events.append(stored)
        return stored

    def all_events(self) -> tuple[AuditEvent, ...]:
        """Return every recorded event in append order."""
        return tuple(self._events)

    def events_for(self, situation_id: str) -> tuple[AuditEvent, ...]:
        """Return the recorded events for one situation, in append order."""
        return tuple(e for e in self._events if e.situation_id == situation_id)

    def verify_chain(self) -> bool:
        """Check the hash-chain: every event links to its predecessor.

        Returns:
            True when every non-first event's ``prev_hash`` equals the
            previous event's id (vacuously true for zero or one event).
        """
        return all(
            self._events[i].prev_hash == self._events[i - 1].event_id
            for i in range(1, len(self._events))
        )

    def __len__(self) -> int:
        """Return the number of recorded events."""
        return len(self._events)

    def __iter__(self) -> Iterator[AuditEvent]:
        """Iterate recorded events in append order."""
        return iter(self._events)
