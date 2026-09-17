"""P6-02 persistence for the FinancialSituation aggregate.

Stores frozen snapshots (P6-01 money states plus P6-02 optional
lifecycle fields) keyed by ``(company_id, situation_id)``
with optimistic concurrency: every successful :meth:`save` bumps an
integer version, and a save presenting a stale ``expected_version``
raises :class:`ConcurrencyError` without mutating anything.

Aggregate-plus-audit writes are atomic: the caller may pass audit dicts
in the sibling-owned shape ``{event_id, situation_id, company_id,
from_status, to_status, at, actor}`` and both the aggregate row and the
audit rows commit in one transaction (or roll back together). The audit
shape is defined locally as :class:`SituationAuditEvent`; no audit
module is imported. The sibling lifecycle engineer owns emission and
transition logic — this repository persists and rehydrates only.

Time discipline: the repository never calls ``datetime.now``. Stored
aggregate rows carry no timestamps at all; audit rows carry only the
explicit tz-aware ``at`` supplied by the caller (naive datetimes are
rejected). Two identical save sequences therefore produce identical
stored bytes: the aggregate payload is canonical JSON (sorted keys,
compact separators, fixed-point ``Decimal`` encoding) and rehydrates via
``model_validate`` to an aggregate equal to the original.

Two backends share one semantic core. Pass an SQLAlchemy ``Engine``
(SQLite for tests; the DDL uses only portable column types so the same
tables apply to Postgres) or pass nothing for a pure-Python in-memory
map with identical semantics for fast unit tests.

This module imports nothing from ``apps/``, ``agents/``, ``shared/``,
or ``finance/reconciliation/``.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, TypedDict

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator
from sqlalchemy import DateTime, Engine, Integer, String, Text, UniqueConstraint
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from finance.domain.financial_situation import FinancialSituation, SituationStatus

logger = logging.getLogger(__name__)

_STATUS_VALUES = frozenset(item.value for item in SituationStatus)
"""Lifecycle state names accepted on stored rows and audit events."""


class ConcurrencyError(Exception):
    """Raised when a save presents a stale (or claimed-but-absent) version.

    No mutation is applied. Carries the expected versus actual versions
    so callers can re-read and retry with a fresh version.

    Attributes:
        situation_id: Aggregate identity the write targeted.
        expected_version: Version the caller presented.
        actual_version: Current version at rejection time (0 when absent).
        detail: Human-readable cause (stale version, claimed version).
    """

    def __init__(
        self,
        situation_id: str,
        expected_version: int,
        actual_version: int,
        detail: str = "stale expected version",
    ) -> None:
        """Record the version skew and build the message."""
        self.situation_id = situation_id
        self.expected_version = expected_version
        self.actual_version = actual_version
        self.detail = detail
        super().__init__(
            f"CONCURRENCY_CONFLICT for {situation_id}: {detail} "
            f"(expected={expected_version} actual={actual_version})"
        )


class SituationAuditEvent(BaseModel):
    """One immutable audit fact bound to a persisted situation version.

    Mirrors the sibling-owned emission shape; the repository owns only
    the transactional write path and the tz-aware ``at`` contract.
    """

    model_config = ConfigDict(frozen=True, strict=True)

    event_id: str
    """Unique audit identity (primary write-once key)."""

    situation_id: str
    """Case the event belongs to; must match the saved aggregate."""

    company_id: str
    """Owning company; must match the saved aggregate."""

    from_status: str
    """Lifecycle state transitioned out of (a SituationStatus value)."""

    to_status: str
    """Lifecycle state transitioned into (a SituationStatus value)."""

    at: datetime
    """Caller-supplied tz-aware instant; naive datetimes are rejected."""

    actor: str
    """Caller identity recorded for the event."""

    @field_validator("event_id", "situation_id", "company_id", "actor")
    @classmethod
    def _require_non_blank(cls, value: str) -> str:
        """Reject blank identities (fail closed, no anonymous writes)."""
        if not value.strip():
            raise ValueError("audit identity fields must be non-blank strings.")
        return value

    @field_validator("from_status", "to_status")
    @classmethod
    def _require_known_status(cls, value: str) -> str:
        """Accept only lifecycle states from the frozen P6-01 contract."""
        if value not in _STATUS_VALUES:
            raise ValueError(f"unknown SituationStatus {value!r}.")
        return value

    @field_validator("at")
    @classmethod
    def _require_tz_aware(cls, value: datetime) -> datetime:
        """Require caller-supplied tz-aware time; the repo mints no time."""
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("audit 'at' must be tz-aware (caller supplies time).")
        return value


class Base(DeclarativeBase):
    """Local declarative base for P6-02 situation tables."""


class SituationRow(Base):
    """Persisted projection of one FinancialSituation snapshot.

    No timestamps: determinism requires identical save sequences to
    yield identical row bytes, so wall-clock columns are banned here.
    """

    __tablename__ = "situations"

    company_id: Mapped[str] = mapped_column(String, primary_key=True)
    situation_id: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)


class SituationAuditRow(Base):
    """One immutable audit fact per persisted situation version."""

    __tablename__ = "situation_audits"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_situation_audits_event_once"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    situation_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    company_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    from_status: Mapped[str] = mapped_column(String, nullable=False)
    to_status: Mapped[str] = mapped_column(String, nullable=False)
    actor: Mapped[str] = mapped_column(String, nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class _StoredCase(TypedDict):
    """In-memory projection of one persisted situation row."""

    status: str
    version: int
    payload: bytes


_AUDIT_UNIQUE_NAME = "uq_situation_audits_event_once"
"""Unique constraint backing audit event dedup (see ``SituationAuditRow``)."""


def _is_audit_duplicate(exc: IntegrityError) -> bool:
    """Return True iff ``exc`` violates the audit event dedup constraint.

    Inspects the DBAPI error/constraint identity so composite-PK or
    other integrity failures propagate unchanged instead of being
    misreported as duplicate audit events.
    """
    orig = exc.orig
    diag = getattr(orig, "diag", None)
    name = getattr(diag, "constraint_name", None) if diag is not None else None
    if name is not None:
        return name == _AUDIT_UNIQUE_NAME
    text = str(orig) if orig is not None else str(exc)
    return _AUDIT_UNIQUE_NAME in text or "situation_audits.event_id" in text


def _decimal_text(value: Decimal) -> str:
    """Encode a money value in fixed-point form (no exponents)."""
    return format(value, "f")


def canonical_payload_bytes(situation: FinancialSituation) -> bytes:
    """Return the deterministic canonical bytes for an aggregate.

    Sorted keys, compact separators, and fixed-point ``Decimal``
    encoding make the output a pure function of the aggregate: equal
    aggregates always yield equal bytes on any backend. Covers the
    four P6-01 money states plus the four P6-02 optional lifecycle
    fields (``None`` encodes as JSON null; datetimes as ISO text).
    """
    payload = {
        "closed_at": situation.closed_at.isoformat() if situation.closed_at else None,
        "company_id": situation.company_id,
        "expected": _decimal_text(situation.expected),
        "legacy": _decimal_text(situation.legacy),
        "proposal_ref": situation.proposal_ref,
        "quickbooks": _decimal_text(situation.quickbooks),
        "razorpay_net": _decimal_text(situation.razorpay_net),
        "rejection_reason": situation.rejection_reason,
        "situation_id": situation.situation_id,
        "status": situation.status.value,
        "verified_total": (
            _decimal_text(situation.verified_total)
            if situation.verified_total is not None
            else None
        ),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _rehydrate(payload: str) -> FinancialSituation:
    """Rebuild an aggregate from its canonical payload (Decimal-exact).

    The frozen aggregate validates in strict mode, so canonical JSON
    strings are converted back to ``Decimal``, ``datetime``, and
    ``SituationStatus`` before ``model_validate`` — parsing is exact,
    never float-based. Absent optional keys default to ``None`` so
    P6-01-shaped rows still rehydrate.
    """
    data: dict[str, Any] = json.loads(payload)
    for key in ("expected", "razorpay_net", "quickbooks", "legacy"):
        data[key] = Decimal(data[key])
    if data.get("verified_total") is not None:
        data["verified_total"] = Decimal(data["verified_total"])
    if data.get("closed_at") is not None:
        data["closed_at"] = datetime.fromisoformat(data["closed_at"])
    data["status"] = SituationStatus(data["status"])
    return FinancialSituation.model_validate(data)


def _as_utc(value: datetime) -> datetime:
    """Re-attach UTC to naive datetimes coming back from the database."""
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=UTC)
    return value


def _coerce_audit_event(
    situation: FinancialSituation, raw: Mapping[str, Any]
) -> SituationAuditEvent:
    """Validate one caller-supplied audit dict against the saved aggregate.

    Raises:
        ValueError: If the dict is malformed, carries a naive ``at``,
            or names a different case/company than the aggregate.
    """
    data = dict(raw)
    for key in ("from_status", "to_status"):
        value = data.get(key)
        if isinstance(value, SituationStatus):
            data[key] = value.value
    try:
        event = SituationAuditEvent.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"invalid audit event for {situation.situation_id}: {exc}") from exc
    if event.situation_id != situation.situation_id or event.company_id != situation.company_id:
        raise ValueError(
            f"audit event case mismatch: {event.company_id}/{event.situation_id} "
            f"does not match {situation.company_id}/{situation.situation_id}."
        )
    return event


class SituationRepository:
    """Versioned store over ``situations`` plus the append-only audit log.

    Binds to an SQLAlchemy engine when given (tables are created on
    init; each method opens a short session), otherwise keeps an
    in-memory map with identical semantics for pure-unit speed.
    """

    def __init__(self, engine: Engine | None = None) -> None:
        """Bind to ``engine`` (creating tables) or start an empty memory store."""
        self._engine = engine
        self._lock = threading.Lock()
        self._cases: dict[tuple[str, str], _StoredCase] = {}
        self._audit_events: dict[str, SituationAuditEvent] = {}
        self._audit_order: list[str] = []
        if engine is not None:
            Base.metadata.create_all(engine)

    def save(
        self,
        situation: FinancialSituation,
        *,
        expected_version: int | None = None,
        audit_events: Sequence[Mapping[str, Any]] | None = None,
    ) -> int:
        """Upsert an aggregate snapshot, bumping its version counter.

        The first save for a ``(company_id, situation_id)`` key creates
        version 1; each later save bumps by one and returns the new
        version. ``expected_version`` opts into optimistic concurrency:
        ``None`` writes blind, ``0`` (or ``None``) creates, and any other
        value must equal the stored version or :class:`ConcurrencyError`
        is raised with no mutation. Claiming a nonzero version for an
        absent row conflicts against actual 0.

        Audit dicts commit in the same transaction as the aggregate row:
        any invalid event (or any commit failure) rolls back both.

        Args:
            situation: Frozen aggregate snapshot to persist.
            expected_version: Version the caller read, or ``None``/``0``.
            audit_events: Caller-side audit dicts in the sibling-owned
                shape; ``at`` must be tz-aware (the repository never
                mints time).

        Returns:
            The new stored version.

        Raises:
            ConcurrencyError: On stale or claimed-but-absent versions.
            ValueError: On malformed, mismatched, or duplicate audit
                events.
        """
        events = [_coerce_audit_event(situation, raw) for raw in (audit_events or [])]
        seen: set[str] = set()
        for event in events:
            if event.event_id in seen:
                raise ValueError(f"duplicate audit event_id in batch: {event.event_id!r}.")
            seen.add(event.event_id)
        if self._engine is not None:
            return self._save_sql(situation, expected_version, events)
        return self._save_memory(situation, expected_version, events)

    def get_for_company(
        self, company_id: str, situation_id: str
    ) -> FinancialSituation | None:
        """Company-scoped read — fails closed if the company is wrong.

        Returns ``None`` uniformly for missing rows, wrong-company
        lookups, and blank inputs (no existential leak).
        """
        company = company_id.strip()
        sid = situation_id.strip()
        if not company or not sid:
            return None
        if self._engine is not None:
            with Session(self._engine) as session:
                row = (
                    session.query(SituationRow)
                    .filter(
                        SituationRow.company_id == company,
                        SituationRow.situation_id == sid,
                    )
                    .one_or_none()
                )
                return _rehydrate(row.payload) if row is not None else None
        entry = self._cases.get((company, sid))
        return _rehydrate(entry["payload"].decode("utf-8")) if entry is not None else None

    def list_for_company(
        self, company_id: str, status: SituationStatus | str | None = None
    ) -> list[FinancialSituation]:
        """List a company's situations in ``situation_id`` order.

        Args:
            company_id: Owning company (blank yields ``[]``).
            status: Optional lifecycle filter (enum member or value).

        Raises:
            ValueError: If ``status`` names no frozen lifecycle state.
        """
        company = company_id.strip()
        if not company:
            return []
        wanted: str | None = None
        if status is not None:
            wanted = status.value if isinstance(status, SituationStatus) else status
            if wanted not in _STATUS_VALUES:
                raise ValueError(f"unknown SituationStatus {status!r}.")
        if self._engine is not None:
            with Session(self._engine) as session:
                query = session.query(SituationRow).filter(SituationRow.company_id == company)
                if wanted is not None:
                    query = query.filter(SituationRow.status == wanted)
                rows = query.order_by(SituationRow.situation_id.asc()).all()
                return [_rehydrate(row.payload) for row in rows]
        matches = [
            _rehydrate(entry["payload"].decode("utf-8"))
            for key, entry in sorted(self._cases.items())
            if key[0] == company and (wanted is None or entry["status"] == wanted)
        ]
        return matches

    def audit_trail(
        self, company_id: str, situation_id: str
    ) -> list[SituationAuditEvent]:
        """Return the ordered audit events for one case (oldest first).

        Scoped like :meth:`get_for_company`: wrong-company or blank
        inputs yield ``[]`` uniformly.
        """
        company = company_id.strip()
        sid = situation_id.strip()
        if not company or not sid:
            return []
        if self._engine is not None:
            with Session(self._engine) as session:
                rows = (
                    session.query(SituationAuditRow)
                    .filter(
                        SituationAuditRow.company_id == company,
                        SituationAuditRow.situation_id == sid,
                    )
                    .order_by(SituationAuditRow.id.asc())
                    .all()
                )
                return [
                    SituationAuditEvent(
                        event_id=row.event_id,
                        situation_id=row.situation_id,
                        company_id=row.company_id,
                        from_status=row.from_status,
                        to_status=row.to_status,
                        at=_as_utc(row.at),
                        actor=row.actor,
                    )
                    for row in rows
                ]
        return [
            self._audit_events[event_id]
            for event_id in self._audit_order
            if (event := self._audit_events[event_id]).company_id == company
            and event.situation_id == sid
        ]

    def stored_payload(self, company_id: str, situation_id: str) -> bytes | None:
        """Return the canonical stored bytes for one case, if visible.

        Diagnostics aid for determinism checks; scoped exactly like
        :meth:`get_for_company` (wrong-company or blank yields ``None``).
        """
        company = company_id.strip()
        sid = situation_id.strip()
        if not company or not sid:
            return None
        if self._engine is not None:
            with Session(self._engine) as session:
                row = (
                    session.query(SituationRow)
                    .filter(
                        SituationRow.company_id == company,
                        SituationRow.situation_id == sid,
                    )
                    .one_or_none()
                )
                return row.payload.encode("utf-8") if row is not None else None
        entry = self._cases.get((company, sid))
        return entry["payload"] if entry is not None else None

    def _save_sql(
        self,
        situation: FinancialSituation,
        expected_version: int | None,
        events: list[SituationAuditEvent],
    ) -> int:
        """Persist one snapshot plus audits in a single SQL transaction.

        Audit instants are normalized to UTC on write: SQLite drops
        tzinfo on ``DateTime`` columns, so normalizing up front keeps
        the stored instant exact on every backend (reads re-attach UTC
        for values that still come back naive).
        """
        assert self._engine is not None
        company = situation.company_id
        sid = situation.situation_id
        payload_text = canonical_payload_bytes(situation).decode("utf-8")
        with Session(self._engine) as session:
            row = (
                session.query(SituationRow)
                .filter(
                    SituationRow.company_id == company,
                    SituationRow.situation_id == sid,
                )
                .one_or_none()
            )
            if row is None:
                if expected_version is not None and expected_version != 0:
                    raise ConcurrencyError(
                        sid, expected_version, 0, detail="claimed version for absent row"
                    )
                new_version = 1
                session.add(
                    SituationRow(
                        company_id=company,
                        situation_id=sid,
                        status=situation.status.value,
                        version=new_version,
                        payload=payload_text,
                    )
                )
            else:
                actual_version = row.version
                if expected_version is not None and expected_version != actual_version:
                    raise ConcurrencyError(sid, expected_version, actual_version)
                new_version = actual_version + 1
                # Atomic compare-and-swap: the UPDATE lands only when no
                # concurrent transaction bumped the row after our SELECT.
                # SQLite serializes writers (belt-and-braces there); the
                # Postgres target needs this. Zero rows → lost race.
                matched = (
                    session.query(SituationRow)
                    .filter(
                        SituationRow.company_id == company,
                        SituationRow.situation_id == sid,
                        SituationRow.version == actual_version,
                    )
                    .update(
                        {
                            SituationRow.status: situation.status.value,
                            SituationRow.version: new_version,
                            SituationRow.payload: payload_text,
                        },
                        synchronize_session="fetch",
                    )
                )
                if matched != 1:
                    session.rollback()
                    raise ConcurrencyError(
                        sid,
                        expected_version,
                        actual_version,
                        detail="concurrent write won the race",
                    )
            for event in events:
                session.add(
                    SituationAuditRow(
                        event_id=event.event_id,
                        situation_id=event.situation_id,
                        company_id=event.company_id,
                        from_status=event.from_status,
                        to_status=event.to_status,
                        actor=event.actor,
                        at=event.at.astimezone(UTC),
                    )
                )
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                if _is_audit_duplicate(exc):
                    logger.warning("situation save rolled back sid=%s: %s", sid, exc)
                    raise ValueError(
                        f"audit event_id already stored for {sid}."
                    ) from exc
                raise
            logger.info("situation saved sid=%s version=%s", sid, new_version)
            return new_version

    def _save_memory(
        self,
        situation: FinancialSituation,
        expected_version: int | None,
        events: list[SituationAuditEvent],
    ) -> int:
        """Persist one snapshot plus audits atomically in memory.

        Every check runs before any mutation, so a failure leaves the
        previous snapshot and audit log untouched (same atomicity as
        the SQL transaction path). The whole check-and-mutate sequence
        holds ``self._lock`` so concurrent threads serialize exactly
        like concurrent SQL transactions.
        """
        with self._lock:
            key = (situation.company_id, situation.situation_id)
            current = self._cases.get(key)
            if current is None:
                if expected_version is not None and expected_version != 0:
                    raise ConcurrencyError(
                        situation.situation_id,
                        expected_version,
                        0,
                        detail="claimed version for absent row",
                    )
                new_version = 1
            else:
                actual_version = current["version"]
                if expected_version is not None and expected_version != actual_version:
                    raise ConcurrencyError(
                        situation.situation_id, expected_version, actual_version
                    )
                new_version = actual_version + 1
            for event in events:
                if event.event_id in self._audit_events:
                    raise ValueError(
                        f"audit event_id already stored: {event.event_id!r}."
                    )
            self._cases[key] = {
                "status": situation.status.value,
                "version": new_version,
                "payload": canonical_payload_bytes(situation),
            }
            for event in events:
                self._audit_events[event.event_id] = event
                self._audit_order.append(event.event_id)
            logger.info(
                "situation saved sid=%s version=%s",
                situation.situation_id,
                new_version,
            )
            return new_version
