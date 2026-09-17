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

Durability (P6-02 D4+D5+D6): every audit event is bound to the exact
stored version it ships with (``version`` must equal the bump result,
else the save is rejected as stale); every event must agree with the
stored transition (on create ``from_status`` equals the situation's own
status, on update ``from_status`` equals the stored status and
``to_status`` equals the incoming status — agreement only, the
allowed-state table is never consulted here and stays lifecycle-owned);
audit rows carry fixed-point ``variance_snapshot`` text plus a
``prev_hash`` chain verifiable via :meth:`verify_durable_chain`;
stored ``CLOSED``/``REJECTED`` rows refuse every further save
(terminal-at-rest, checked before version logic); and a stored row
re-saved with identical canonical bytes and no audit events
short-circuits to the current version with no write and no bump.
Recorded actors are stored verbatim — recorded, never verified (D7):
this repository checks event shape and agreement only, never authority.

This module imports nothing from ``apps/``, ``agents/``, ``shared/``,
or ``finance/reconciliation/``.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, TypedDict, get_args

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import DateTime, Engine, Integer, String, Text, UniqueConstraint
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from finance.domain.financial_situation import FinancialSituation, SituationStatus

logger = logging.getLogger(__name__)

_STATUS_VALUES = frozenset(item.value for item in SituationStatus)
"""Lifecycle state names accepted on stored rows and audit events."""

_TERMINAL_STATUSES = frozenset(
    {SituationStatus.CLOSED.value, SituationStatus.REJECTED.value}
)
"""Stored statuses that refuse every further save (D5 terminal-at-rest)."""


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


class TerminalStateError(ValueError):
    """Raised when a save targets a case whose stored row is terminal.

    A ``CLOSED`` or ``REJECTED`` stored row refuses every further save
    (D5 terminal-at-rest). The check runs before version logic, so a
    stale ``expected_version`` over a terminal row still surfaces as
    terminal, never as a concurrency conflict. Subclasses ``ValueError``
    so generic fail-closed handlers keep working.

    Attributes:
        situation_id: Aggregate identity the write targeted.
        stored_status: Terminal status found on the stored row.
    """

    def __init__(self, situation_id: str, stored_status: str) -> None:
        """Record the terminal status and build the message."""
        self.situation_id = situation_id
        self.stored_status = stored_status
        super().__init__(
            f"TERMINAL_STATE for {situation_id}: "
            f"stored status {stored_status} refuses further saves."
        )


class SituationAuditEvent(BaseModel):
    """One immutable audit fact bound to a persisted situation version.

    Mirrors the sibling-owned emission shape; the repository owns only
    the transactional write path and the tz-aware ``at`` contract.
    ``version`` binds the event to the exact stored version it ships
    with (D4a); ``variance_snapshot`` is fixed-point ``Decimal`` text or
    ``None`` (D4c); ``prev_hash`` chains to the previous event id for
    the case, ``''`` for the first (D4c). The actor is recorded verbatim
    — recorded, never verified (D7).
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
    """Caller identity recorded for the event (never verified)."""

    version: int = Field(ge=1)
    """New stored version this event ships with; stale events rejected."""

    variance_snapshot: str | None = None
    """Post-transition variance as fixed-point Decimal text (or None)."""

    prev_hash: str = ""
    """Event id of the preceding record for the case; '' for the first."""

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

    @field_validator("variance_snapshot", mode="before")
    @classmethod
    def _normalize_variance(cls, value: Any) -> str | None:
        """Accept Decimal|str|None, storing fixed-point text (Decimal-only)."""
        if value is None:
            return None
        if isinstance(value, Decimal):
            return format(value, "f")
        if isinstance(value, str):
            try:
                return format(Decimal(value), "f")
            except InvalidOperation as err:
                raise ValueError(
                    f"audit variance_snapshot is not Decimal text: {value!r}."
                ) from err
        raise ValueError(
            "audit variance_snapshot must be Decimal, Decimal text, or None; "
            f"got {type(value).__name__}."
        )


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
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    variance_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    prev_hash: Mapped[str | None] = mapped_column(Text, nullable=True)


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


def _canonical_verification(value: Any) -> dict[str, Any] | None:
    """Normalize the sibling-owned verification object to canonical dict.

    Accepts a mapping, a Pydantic model (via ``model_dump``), or any
    object exposing the canonical verification attributes, and returns
    the fixed six-key shape (``checked_at`` ISO text, ``execution_id``,
    ``legacy_total_after`` fixed-point text, ``situation_id``,
    ``variance_after`` fixed-point text, ``verdict`` value) with sorted
    keys at dump time. ``None`` stays ``None``. Money stays
    ``Decimal``-exact; unknown shapes pass through for the sibling
    layer to judge — this function never raises on shape alone.
    """
    if value is None:
        return None
    if isinstance(value, Mapping):
        data = dict(value)
    elif hasattr(value, "model_dump") and callable(value.model_dump):
        dumped = value.model_dump()
        data = dict(dumped) if isinstance(dumped, dict) else {}
    else:
        data = {
            key: getattr(value, key)
            for key in (
                "checked_at",
                "execution_id",
                "legacy_total_after",
                "situation_id",
                "variance_after",
                "verdict",
            )
            if hasattr(value, key)
        }
    checked_at = data.get("checked_at")
    if isinstance(checked_at, datetime):
        data["checked_at"] = checked_at.isoformat()
    for money_key in ("legacy_total_after", "variance_after"):
        money = data.get(money_key)
        if isinstance(money, Decimal):
            data[money_key] = format(money, "f")
    verdict = data.get("verdict")
    if isinstance(verdict, Enum):
        data["verdict"] = verdict.value
    return {
        "checked_at": data.get("checked_at"),
        "execution_id": data.get("execution_id"),
        "legacy_total_after": data.get("legacy_total_after"),
        "situation_id": data.get("situation_id"),
        "variance_after": data.get("variance_after"),
        "verdict": data.get("verdict"),
    }


def canonical_payload_bytes(situation: FinancialSituation) -> bytes:
    """Return the deterministic canonical bytes for an aggregate.

    Sorted keys, compact separators, and fixed-point ``Decimal``
    encoding make the output a pure function of the aggregate: equal
    aggregates always yield equal bytes on any backend. Covers the
    seventeen-key shape — the P6-01 money states, the P6-02 optional
    lifecycle fields, and the sibling-owned extensions (``decider_role``,
    ``evidence_ids``, ``hypothesis_count``, ``proposal_hash``,
    ``proposal_version``, ``verification``) read tolerantly via
    ``getattr`` so rows written before (or without) those fields still
    encode with ``None``/``[]`` defaults and never lose data silently.
    ``None`` encodes as JSON null; datetimes as ISO text; the nested
    verification object uses the fixed six-key canonical form.
    """
    decider = getattr(situation, "decider_role", None)
    if isinstance(decider, Enum):
        decider = decider.value
    evidence = getattr(situation, "evidence_ids", None)
    payload = {
        "closed_at": situation.closed_at.isoformat() if situation.closed_at else None,
        "company_id": situation.company_id,
        "decider_role": decider,
        "evidence_ids": list(evidence) if evidence is not None else [],
        "expected": _decimal_text(situation.expected),
        "hypothesis_count": getattr(situation, "hypothesis_count", None),
        "legacy": _decimal_text(situation.legacy),
        "proposal_hash": getattr(situation, "proposal_hash", None),
        "proposal_ref": getattr(situation, "proposal_ref", None),
        "proposal_version": getattr(situation, "proposal_version", None),
        "quickbooks": _decimal_text(situation.quickbooks),
        "razorpay_net": _decimal_text(situation.razorpay_net),
        "rejection_reason": situation.rejection_reason,
        "situation_id": situation.situation_id,
        "status": situation.status.value,
        "verification": _canonical_verification(
            getattr(situation, "verification", None)
        ),
        "verified_total": (
            _decimal_text(situation.verified_total)
            if situation.verified_total is not None
            else None
        ),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _enum_member(annotation: Any, value: str) -> Any:
    """Coerce ``str`` to an enum member using a model field annotation.

    Unwraps ``Optional``/``Union`` annotations for the first ``Enum``
    candidate; returns ``value`` unchanged when no candidate matches, so
    the frozen aggregate validates (or ignores, for unknown extras) the
    raw value itself.
    """
    candidates: list[type[Enum]] = []
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        candidates.append(annotation)
    else:
        for arg in get_args(annotation):
            try:
                if isinstance(arg, type) and issubclass(arg, Enum):
                    candidates.append(arg)
            except TypeError:
                continue
    for candidate in candidates:
        try:
            return candidate(value)
        except ValueError:
            continue
    return value


def _rehydrate_verification(raw: dict[str, Any]) -> dict[str, Any]:
    """Coerce a canonical verification dict back to model-typed values.

    Money strings return to ``Decimal``, ISO text to ``datetime``, and
    verdict strings to enum members when the sibling-owned nested model
    resolves from the aggregate annotation. Every step is best-effort:
    unknown shapes pass through for ``model_validate`` to judge, and
    absent keys stay absent so old rows still load.
    """
    data = dict(raw)
    for money_key in ("legacy_total_after", "variance_after"):
        if data.get(money_key) is not None and not isinstance(
            data[money_key], Decimal
        ):
            data[money_key] = Decimal(str(data[money_key]))
    if data.get("checked_at") is not None and isinstance(data["checked_at"], str):
        data["checked_at"] = datetime.fromisoformat(data["checked_at"])
    if isinstance(data.get("verdict"), str):
        try:
            vfield = FinancialSituation.model_fields.get("verification")
            vann: Any = vfield.annotation if vfield is not None else None
            nested: Any = None
            if isinstance(vann, type) and hasattr(vann, "model_fields"):
                nested = vann
            else:
                for arg in get_args(vann):
                    if isinstance(arg, type) and hasattr(arg, "model_fields"):
                        nested = arg
                        break
            if nested is not None:
                verdict_field = nested.model_fields.get("verdict")
                if verdict_field is not None:
                    data["verdict"] = _enum_member(
                        verdict_field.annotation, data["verdict"]
                    )
        except Exception:  # noqa: BLE001 - best-effort coercion only
            pass
    return data


def _rehydrate(payload: str) -> FinancialSituation:
    """Rebuild an aggregate from its canonical payload (Decimal-exact).

    The frozen aggregate validates in strict mode, so canonical JSON
    strings are converted back to ``Decimal``, ``datetime``, and
    ``SituationStatus`` before ``model_validate`` — parsing is exact,
    never float-based. Absent optional keys (including every
    sibling-owned extension) fall through to model defaults so P6-01-
    shaped rows still rehydrate; unknown extras are ignored by the
    frozen model. Sibling enums resolve via field annotations when the
    extended aggregate is present, else raw values pass through.
    """
    data: dict[str, Any] = json.loads(payload)
    for key in ("expected", "razorpay_net", "quickbooks", "legacy"):
        data[key] = Decimal(data[key])
    if data.get("verified_total") is not None:
        data["verified_total"] = Decimal(data["verified_total"])
    if data.get("closed_at") is not None:
        data["closed_at"] = datetime.fromisoformat(data["closed_at"])
    data["status"] = SituationStatus(data["status"])
    decider_field = FinancialSituation.model_fields.get("decider_role")
    if decider_field is not None and isinstance(data.get("decider_role"), str):
        data["decider_role"] = _enum_member(
            decider_field.annotation, data["decider_role"]
        )
    if isinstance(data.get("evidence_ids"), (list, tuple)):
        data["evidence_ids"] = tuple(data["evidence_ids"])
    if isinstance(data.get("verification"), dict):
        data["verification"] = _rehydrate_verification(data["verification"])
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

    Accepts the sibling-owned shape plus the durable options
    ``version`` (required, ``>= 1``), ``variance_snapshot``
    (``Decimal``|``str``|``None`` normalized to fixed-point text) and
    ``prev_hash`` (``str``, blank until linked at write time).

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


def _link_batch(
    events: list[SituationAuditEvent], last_stored_event_id: str
) -> list[SituationAuditEvent]:
    """Auto-link blank ``prev_hash`` values to the predecessor event id.

    The first blank links to the last stored event for the case (``''``
    when the case has no history); later blanks chain within the batch.
    Caller-set values — including forged links — are preserved as-is so
    :meth:`SituationRepository.verify_durable_chain` can detect
    tampering. Actors are recorded, never verified (D7): this path
    checks linkage shape only, never authority.
    """
    base = last_stored_event_id
    linked: list[SituationAuditEvent] = []
    for event in events:
        if event.prev_hash:
            linked.append(event)
        else:
            linked.append(event.model_copy(update={"prev_hash": base}))
        base = event.event_id
    return linked


def _check_event_agreement(
    *,
    events: list[SituationAuditEvent],
    situation: FinancialSituation,
    stored_status: str | None,
    new_version: int,
) -> None:
    """Enforce D4a version binding and D4b transition agreement.

    D4a: every event's ``version`` must equal the new stored version
    being written (stale events are rejected, never rebound). D4b: on
    create (``stored_status`` is ``None``) each event's ``from_status``
    must equal the situation's own status (the event records arrival,
    not travel); on update ``from_status`` must equal the stored status
    and ``to_status`` must equal the incoming status. The
    allowed-transition table is never consulted here — agreement, not
    authorization, stays lifecycle-owned. Actors recorded-not-verified.
    """
    current = situation.status.value
    for event in events:
        if event.version != new_version:
            raise ValueError(
                f"stale audit event {event.event_id!r}: version {event.version} "
                f"!= new stored version {new_version}."
            )
        if stored_status is None:
            if event.from_status != current:
                raise ValueError(
                    f"audit event {event.event_id!r} disagrees on create: "
                    f"from_status {event.from_status!r} != status {current!r}."
                )
        elif event.from_status != stored_status or event.to_status != current:
            raise ValueError(
                f"audit event {event.event_id!r} disagrees: "
                f"{event.from_status!r}->{event.to_status!r} against "
                f"stored {stored_status!r} -> incoming {current!r}."
            )


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
        any invalid event (or any commit failure) rolls back both. Each
        event must carry ``version`` equal to the new stored version
        being written (D4a, stale events rejected) and must agree with
        the stored transition — on create ``from_status`` equals the
        situation's own status, on update ``from_status`` equals the
        stored status and ``to_status`` equals the incoming status (D4b,
        agreement only; the allowed-state table stays lifecycle-owned).
        Blank ``prev_hash`` values auto-link to the predecessor event id
        (``''`` for the first); caller-set links are preserved verbatim
        for tamper detection. A stored ``CLOSED``/``REJECTED`` row
        refuses every further save with :class:`TerminalStateError`,
        checked before version logic (D5). A stored row re-saved with
        identical canonical bytes and no audit events short-circuits:
        the current version returns with no write and no bump (D6); any
        supplied events take the normal path (duplicate ids still
        rejected). Recorded actors are stored verbatim — recorded, never
        verified (D7).

        Args:
            situation: Frozen aggregate snapshot to persist.
            expected_version: Version the caller read, or ``None``/``0``.
            audit_events: Caller-side audit dicts in the sibling-owned
                shape plus ``version`` (required, ``>= 1``) and optional
                ``variance_snapshot``/``prev_hash``; ``at`` must be
                tz-aware (the repository never mints time).

        Returns:
            The new stored version (or the current version on a D6
            short-circuit).

        Raises:
            ConcurrencyError: On stale or claimed-but-absent versions.
            TerminalStateError: When the stored row is ``CLOSED`` or
                ``REJECTED`` (a ``ValueError`` subclass).
            ValueError: On malformed, mismatched, stale-versioned,
                disagreeing, or duplicate audit events.
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
                        version=row.version,
                        variance_snapshot=row.variance_snapshot,
                        prev_hash=row.prev_hash or "",
                    )
                    for row in rows
                ]
        return [
            self._audit_events[event_id]
            for event_id in self._audit_order
            if (event := self._audit_events[event_id]).company_id == company
            and event.situation_id == sid
        ]

    def verify_durable_chain(self, company_id: str, situation_id: str) -> bool:
        """Verify the durable hash-chain for one case (D4c tamper-evidence).

        The first stored event must carry a blank ``prev_hash`` and every
        later event must name its immediate predecessor's ``event_id``.
        Caller-forged links (preserved verbatim at write time) surface as
        ``False`` here. An empty trail — including wrong-company or blank
        inputs, scoped like :meth:`get_for_company` — verifies vacuously
        as ``True`` (no contradicting rows).
        """
        company = company_id.strip()
        sid = situation_id.strip()
        if not company or not sid:
            return True
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
                chain = [
                    (row.event_id, row.prev_hash or "") for row in rows
                ]
        else:
            chain = [
                (event.event_id, event.prev_hash)
                for event_id in self._audit_order
                if (event := self._audit_events[event_id]).company_id == company
                and event.situation_id == sid
            ]
        for index, (_event_id, prev_hash) in enumerate(chain):
            wanted = "" if index == 0 else chain[index - 1][0]
            if prev_hash != wanted:
                return False
        return True

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
        payload_bytes = canonical_payload_bytes(situation)
        payload_text = payload_bytes.decode("utf-8")
        with Session(self._engine) as session:
            row = (
                session.query(SituationRow)
                .filter(
                    SituationRow.company_id == company,
                    SituationRow.situation_id == sid,
                )
                .one_or_none()
            )
            stored_status: str | None = row.status if row is not None else None
            if row is not None and row.status in _TERMINAL_STATUSES:
                raise TerminalStateError(sid, row.status)
            if row is None:
                if expected_version is not None and expected_version != 0:
                    raise ConcurrencyError(
                        sid, expected_version, 0, detail="claimed version for absent row"
                    )
                new_version = 1
            else:
                actual_version = row.version
                if expected_version is not None and expected_version != actual_version:
                    raise ConcurrencyError(sid, expected_version, actual_version)
                new_version = actual_version + 1
                if not events and payload_bytes == row.payload.encode("utf-8"):
                    logger.info(
                        "situation save short-circuited sid=%s version=%s",
                        sid,
                        actual_version,
                    )
                    return actual_version
            _check_event_agreement(
                events=events,
                situation=situation,
                stored_status=stored_status,
                new_version=new_version,
            )
            last_id_row = (
                session.query(SituationAuditRow.event_id)
                .filter(
                    SituationAuditRow.company_id == company,
                    SituationAuditRow.situation_id == sid,
                )
                .order_by(SituationAuditRow.id.desc())
                .first()
            )
            linked = _link_batch(
                events, last_id_row[0] if last_id_row is not None else ""
            )
            if row is None:
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
            for event in linked:
                session.add(
                    SituationAuditRow(
                        event_id=event.event_id,
                        situation_id=event.situation_id,
                        company_id=event.company_id,
                        from_status=event.from_status,
                        to_status=event.to_status,
                        actor=event.actor,
                        at=event.at.astimezone(UTC),
                        version=event.version,
                        variance_snapshot=event.variance_snapshot,
                        prev_hash=event.prev_hash,
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
            stored_status: str | None = current["status"] if current is not None else None
            if current is not None and current["status"] in _TERMINAL_STATUSES:
                raise TerminalStateError(situation.situation_id, current["status"])
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
                if not events and canonical_payload_bytes(situation) == current["payload"]:
                    logger.info(
                        "situation save short-circuited sid=%s version=%s",
                        situation.situation_id,
                        actual_version,
                    )
                    return actual_version
            _check_event_agreement(
                events=events,
                situation=situation,
                stored_status=stored_status,
                new_version=new_version,
            )
            last_stored = ""
            for event_id in self._audit_order:
                prior = self._audit_events[event_id]
                if prior.company_id == situation.company_id and (
                    prior.situation_id == situation.situation_id
                ):
                    last_stored = prior.event_id
            linked = _link_batch(events, last_stored)
            for event in linked:
                if event.event_id in self._audit_events:
                    raise ValueError(
                        f"audit event_id already stored: {event.event_id!r}."
                    )
            self._cases[key] = {
                "status": situation.status.value,
                "version": new_version,
                "payload": canonical_payload_bytes(situation),
            }
            for event in linked:
                self._audit_events[event.event_id] = event
                self._audit_order.append(event.event_id)
            logger.info(
                "situation saved sid=%s version=%s",
                situation.situation_id,
                new_version,
            )
            return new_version
