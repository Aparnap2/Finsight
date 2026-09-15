"""Versioned Exception Aggregate: the single orchestration boundary per break.

One aggregate hangs every proposal / approval / execution reference for a
single actionable reconciliation break off its ``proposal_id`` /
``approval_id`` / ``execution_id`` slots — no orphans. ``state`` mutates
only through code-owned transitions that take ``expected_state_version``
and bump ``state_version`` by exactly one; the dataclass is frozen so
direct field writes raise :class:`dataclasses.FrozenInstanceError`.

P3.2 implements the investigation chain only::

    EXCEPTION -> INVESTIGATING -> EVIDENCE_READY -> EVIDENCE_VERIFIED
        -> PROPOSED -> AWAITING_APPROVAL

Approve / execute / close transitions are rejected as out-of-scope until
their owning phases land. Banned pairs (SM-2) are always rejected.

Only the Python standard library plus P1 reconciliation contracts are
used. This module imports nothing from ``apps/``, ``agents/``, or
SQLAlchemy.
"""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from finance.exceptions.errors import ConcurrencyConflictError, IllegalTransitionError
from finance.exceptions.states import (
    ALLOWED_TRANSITIONS,
    BANNED_TRANSITIONS,
    EVIDENCE_SEALED_FROM,
    P32_TARGETS,
    ExceptionState,
    Severity,
)
from finance.reconciliation.models import ExceptionCode

logger = logging.getLogger(__name__)

_INITIAL_VERSION = 1


def _utcnow() -> datetime:
    """Return a tz-aware UTC timestamp for ``created_at``/``updated_at``."""
    return datetime.now(UTC)


def _require_id(field_name: str, value: object) -> str:
    """Validate a non-empty identifier and return it stripped."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Field '{field_name}' must be a non-empty string.")
    return value.strip()


def _coerce_state(value: object) -> ExceptionState:
    """Coerce a raw string to ``ExceptionState``, rejecting unknowns."""
    if isinstance(value, ExceptionState):
        return value
    if isinstance(value, str):
        try:
            return ExceptionState(value.strip().upper())
        except ValueError as exc:
            raise ValueError(f"Unknown exception state {value!r}.") from exc
    raise TypeError(
        f"Field 'state' must be an ExceptionState or state name, got {type(value).__name__}."
    )


def _coerce_severity(value: object) -> Severity:
    """Coerce a raw string to ``Severity``, rejecting unknowns."""
    if isinstance(value, Severity):
        return value
    if isinstance(value, str):
        try:
            return Severity(value.strip().upper())
        except ValueError as exc:
            raise ValueError(f"Unknown severity {value!r}.") from exc
    raise TypeError(
        f"Field 'severity' must be a Severity or severity name, got {type(value).__name__}."
    )


def _coerce_exception_type(value: object) -> ExceptionCode:
    """Coerce a raw string to ``ExceptionCode``; the 3-code set is closed."""
    if isinstance(value, ExceptionCode):
        return value
    if isinstance(value, str):
        try:
            return ExceptionCode(value.strip())
        except ValueError as exc:
            raise ValueError(
                f"Unknown exception_type {value!r}: must be one of the 3 frozen P1 codes."
            ) from exc
    raise TypeError(
        "Field 'exception_type' must be an ExceptionCode or code string, "
        f"got {type(value).__name__}."
    )


@dataclass(frozen=True)
class ExceptionAggregate:
    """Immutable versioned aggregate for one reconciliation break.

    Twelve spec slots: ``exception_id``, ``tenant_id``,
    ``reconciliation_result_id``, ``exception_type``, ``severity``,
    ``state``, ``state_version``, ``evidence_ids``, ``proposal_id``,
    ``approval_id``, ``execution_id``, ``created_at`` / ``updated_at``.
    ``evidence_ids`` is a tuple (append-only once sealed at
    ``EVIDENCE_VERIFIED``). Slot references start empty (``None``) until
    each phase completes.
    """

    exception_id: str
    tenant_id: str
    reconciliation_result_id: str
    exception_type: ExceptionCode
    severity: Severity
    state: ExceptionState
    state_version: int
    evidence_ids: tuple[str, ...]
    proposal_id: str | None
    approval_id: str | None
    execution_id: str | None
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        """Enforce identifiers, closed vocabularies, versions, and times."""
        object.__setattr__(self, "exception_id", _require_id("exception_id", self.exception_id))
        object.__setattr__(self, "tenant_id", _require_id("tenant_id", self.tenant_id))
        object.__setattr__(
            self,
            "reconciliation_result_id",
            _require_id("reconciliation_result_id", self.reconciliation_result_id),
        )
        object.__setattr__(self, "exception_type", _coerce_exception_type(self.exception_type))
        object.__setattr__(self, "severity", _coerce_severity(self.severity))
        object.__setattr__(self, "state", _coerce_state(self.state))
        version = self.state_version
        if not isinstance(version, int) or isinstance(version, bool):
            raise TypeError("Field 'state_version' must be an int.")
        if version < _INITIAL_VERSION:
            raise ValueError(f"Field 'state_version' must be >= {_INITIAL_VERSION}, got {version}.")
        raw_evidence = self.evidence_ids
        if isinstance(raw_evidence, list):
            coerced = tuple(raw_evidence)
        elif isinstance(raw_evidence, tuple):
            coerced = raw_evidence
        else:
            raise TypeError("Field 'evidence_ids' must be a tuple or list of str.")
        for evidence_id in coerced:
            if not isinstance(evidence_id, str) or not evidence_id.strip():
                raise ValueError("Every entry of 'evidence_ids' must be non-empty str.")
        object.__setattr__(self, "evidence_ids", coerced)
        for slot in ("proposal_id", "approval_id", "execution_id"):
            slot_value = getattr(self, slot)
            if slot_value is not None:
                object.__setattr__(self, slot, _require_id(slot, slot_value))
        for stamp in ("created_at", "updated_at"):
            stamp_value = getattr(self, stamp)
            if not isinstance(stamp_value, datetime):
                raise TypeError(f"Field '{stamp}' must be a datetime.")
            if stamp_value.tzinfo is None or stamp_value.tzinfo.utcoffset(stamp_value) is None:
                raise ValueError(f"Field '{stamp}' must be tz-aware.")

    @classmethod
    def create(
        cls,
        *,
        exception_id: str,
        tenant_id: str,
        reconciliation_result_id: str,
        exception_type: ExceptionCode | str,
        severity: Severity | str,
        evidence_ids: tuple[str, ...] | list[str] = (),
        created_at: datetime | None = None,
    ) -> ExceptionAggregate:
        """Create exactly one aggregate per break at ``EXCEPTION`` version 1.

        Args:
            exception_id: Unique aggregate identity (create-once).
            tenant_id: Owning tenant scope.
            reconciliation_result_id: Break this aggregate hangs off.
            exception_type: One of the 3 frozen P1 codes.
            severity: Initial severity metadata.
            evidence_ids: Seed evidence references (may be empty).
            created_at: Fixed clock for tests; defaults to UTC now.

        Returns:
            A new aggregate in ``EXCEPTION`` with empty phase slots.
        """
        now = created_at if created_at is not None else _utcnow()
        return cls(
            exception_id=_require_id("exception_id", exception_id),
            tenant_id=_require_id("tenant_id", tenant_id),
            reconciliation_result_id=_require_id(
                "reconciliation_result_id", reconciliation_result_id
            ),
            exception_type=_coerce_exception_type(exception_type),
            severity=_coerce_severity(severity),
            state=ExceptionState.EXCEPTION,
            state_version=_INITIAL_VERSION,
            evidence_ids=tuple(evidence_ids),
            proposal_id=None,
            approval_id=None,
            execution_id=None,
            created_at=now,
            updated_at=now,
        )

    def transition_to(
        self,
        target: ExceptionState | str,
        expected_state_version: int,
        *,
        actor: str = "system",
        evidence_ids: tuple[str, ...] | list[str] | None = None,
        proposal_id: str | None = None,
    ) -> ExceptionAggregate:
        """Apply one code-owned transition guarded by optimistic concurrency.

        Args:
            target: Requested next state (coerced from name if needed).
            expected_state_version: Must equal current ``state_version``.
            actor: Caller identity recorded by the repository audit.
            evidence_ids: Replacement evidence set; sealed (append-only)
                once the aggregate has reached ``EVIDENCE_VERIFIED``.
            proposal_id: Proposal slot value when entering ``PROPOSED``.

        Returns:
            A new aggregate with ``state_version`` bumped by exactly one.

        Raises:
            ConcurrencyConflictError: If the expected version is stale.
            IllegalTransitionError: If the move is banned, unlisted in SM-1,
                beyond P3.2 scope, seals evidence illegally, or misses a
                required slot value.
        """
        target_state = _coerce_state(target)
        if expected_state_version != self.state_version:
            raise ConcurrencyConflictError(
                self.exception_id, expected_state_version, self.state_version
            )
        pair = (self.state, target_state)
        if pair in BANNED_TRANSITIONS:
            raise IllegalTransitionError(
                self.exception_id,
                self.state.value,
                target_state.value,
                reason="banned by SM-2",
            )
        if pair not in ALLOWED_TRANSITIONS:
            raise IllegalTransitionError(self.exception_id, self.state.value, target_state.value)
        if target_state not in P32_TARGETS:
            raise IllegalTransitionError(
                self.exception_id,
                self.state.value,
                target_state.value,
                reason="beyond P3.2 scope (approve/execute/close owned by later phases)",
            )
        next_evidence = tuple(evidence_ids) if evidence_ids is not None else self.evidence_ids
        if self.state in EVIDENCE_SEALED_FROM and target_state in EVIDENCE_SEALED_FROM:
            removed = set(self.evidence_ids) - set(next_evidence)
            if removed:
                raise IllegalTransitionError(
                    self.exception_id,
                    self.state.value,
                    target_state.value,
                    reason=f"evidence_ids append-only after EVIDENCE_VERIFIED, "
                    f"would drop {sorted(removed)}",
                )
        next_proposal = self.proposal_id if proposal_id is None else proposal_id.strip()
        if target_state is ExceptionState.PROPOSED and not next_proposal:
            raise IllegalTransitionError(
                self.exception_id,
                self.state.value,
                target_state.value,
                reason="proposal_id slot must be set when entering PROPOSED",
            )
        logger.info(
            "exception transition %s -> %s id=%s v=%s actor=%s",
            self.state.value,
            target_state.value,
            self.exception_id,
            self.state_version,
            actor,
        )
        return dataclasses.replace(
            self,
            state=target_state,
            state_version=self.state_version + 1,
            evidence_ids=next_evidence,
            proposal_id=next_proposal,
            updated_at=_utcnow(),
        )

    def open_investigation(
        self, expected_state_version: int, *, actor: str = "system"
    ) -> ExceptionAggregate:
        """Move ``EXCEPTION -> INVESTIGATING`` under a version guard."""
        return self.transition_to(ExceptionState.INVESTIGATING, expected_state_version, actor=actor)

    def mark_evidence_ready(
        self,
        expected_state_version: int,
        evidence_ids: tuple[str, ...] | list[str],
        *,
        actor: str = "system",
    ) -> ExceptionAggregate:
        """Move ``INVESTIGATING -> EVIDENCE_READY`` attaching evidence."""
        return self.transition_to(
            ExceptionState.EVIDENCE_READY,
            expected_state_version,
            actor=actor,
            evidence_ids=evidence_ids,
        )

    def verify_evidence(
        self, expected_state_version: int, *, actor: str = "system"
    ) -> ExceptionAggregate:
        """Move ``EVIDENCE_READY -> EVIDENCE_VERIFIED``, sealing evidence."""
        return self.transition_to(
            ExceptionState.EVIDENCE_VERIFIED, expected_state_version, actor=actor
        )

    def draft_proposal(
        self,
        expected_state_version: int,
        proposal_id: str,
        *,
        actor: str = "system",
    ) -> ExceptionAggregate:
        """Move ``EVIDENCE_VERIFIED -> PROPOSED`` pinning the proposal slot."""
        return self.transition_to(
            ExceptionState.PROPOSED,
            expected_state_version,
            actor=actor,
            proposal_id=proposal_id,
        )

    def submit_for_approval(
        self, expected_state_version: int, *, actor: str = "system"
    ) -> ExceptionAggregate:
        """Move ``PROPOSED -> AWAITING_APPROVAL`` (P3.2 terminal step)."""
        return self.transition_to(
            ExceptionState.AWAITING_APPROVAL, expected_state_version, actor=actor
        )

    def with_severity(self, severity: Severity | str) -> ExceptionAggregate:
        """Re-derive severity metadata without a version bump.

        Severity is non-state metadata: the version stays fixed and only
        ``severity`` plus ``updated_at`` change.
        """
        return dataclasses.replace(self, severity=_coerce_severity(severity), updated_at=_utcnow())
