"""HITL approval service (T2): 10 ordered gates plus crash-safe CAS.

``ApprovalService.decide`` enforces exactly ten gates in order, then
atomically persists the terminal state and the immutable record in one
database transaction with NO execution scheduling (no ``execution_id`` is
ever set, no worker is notified): a crash after commit leaves
``APPROVED``/``REJECTED`` plus the record durable, and a fresh handle
resumes from the database alone.

Gate order (each gate raises before any mutation):

1. exception exists (else ``IllegalTransitionError``);
2. state is ``AWAITING_APPROVAL`` — terminal re-decision with an unseen
   key is ``ConcurrencyConflictError``; any other non-awaiting state is
   ``IllegalTransitionError``;
3. ``expected_state_version`` equals the snapshot version (else
   ``ConcurrencyConflictError``);
4. proposal resolves through ``proposals_lookup`` (else
   ``IllegalTransitionError``);
5. pinned version equals the proposal version (else ``ApprovalSkewError``);
6. pinned hash equals the stored hash AND ``verify_hash`` passes (else
   ``ApprovalSkewError``);
7. proposal evidence is a subset of the aggregate sealed set (else
   ``IllegalTransitionError``);
8. policy allows: sandbox-only action plus ``amount <= threshold``,
   a pure function of (proposal, threshold) — deterministic;
9. idempotency: a seen key for this exception returns the prior record;
   a key bound to another exception is ``ConcurrencyConflictError``;
10. single predicated ``UPDATE`` (CAS) to ``APPROVED``/``REJECTED`` plus
    the immutable record insert and audit row, committed atomically —
    zero affected rows is ``ConcurrencyConflictError``.

Idempotent replays (gates 2/3) yield to gate 9: a presenting key that
already owns a record for this exception returns that record instead of
raising a stale-state conflict. The prefetch behind this is read-only;
no gate mutates before gate 10.

``ExceptionRepository.apply`` cannot serve gate 10: its Python-side
``transition_to`` rejects ``AWAITING_APPROVAL -> APPROVED/REJECTED`` as
beyond P3.2 scope, so this service issues the same predicated-CAS shape
(``WHERE exception_id + state_version + state``) directly against
``ExceptionRow``. Error types are reused from
``finance.exceptions.errors`` — never redefined here.

Only SQLAlchemy plus ``finance.*`` are used. This module imports nothing
from ``apps/``, ``agents/``, or ``shared/``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import Engine, String, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from finance.approvals.decision import (
    ApprovalCommand,
    ApprovalDecision,
    ApprovalRecord,
    approval_id_for,
)
from finance.exceptions.aggregate import ExceptionAggregate
from finance.exceptions.approval import ApprovalPin
from finance.exceptions.errors import (
    ApprovalSkewError,
    ConcurrencyConflictError,
    IllegalTransitionError,
)
from finance.exceptions.models import Base, ExceptionAuditRow, ExceptionRow
from finance.exceptions.states import ExceptionState
from finance.proposals.builder import verify_hash
from finance.proposals.proposal import Proposal, ProposalAction

logger = logging.getLogger(__name__)

#: Actions the sandbox executor is allowed to book; anything else is
#: policy-rejected (deterministic, no external input).
_SANDBOX_ACTIONS: frozenset[ProposalAction] = frozenset(
    {
        ProposalAction.CREATE_CORRECTING_ENTRY,
        ProposalAction.VOID_DUPLICATE,
    }
)

#: States after which no further decision is accepted with a fresh key.
_TERMINAL_STATES: frozenset[ExceptionState] = frozenset(
    {
        ExceptionState.APPROVED,
        ExceptionState.REJECTED,
    }
)

#: Lookup shape: exact mapping or callable returning the proposal or None.
ProposalLookup = Mapping[str, Proposal] | Callable[[str], Proposal | None]


class ApprovalRow(Base):
    """Persisted projection of one :class:`ApprovalRecord` (immutable)."""

    __tablename__ = "approvals"

    approval_id: Mapped[str] = mapped_column(String, primary_key=True)
    exception_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    proposal_id: Mapped[str] = mapped_column(String, nullable=False)
    proposal_version: Mapped[int] = mapped_column(nullable=False)
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    decision: Mapped[str] = mapped_column(String, nullable=False)
    approver_id: Mapped[str] = mapped_column(String, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    state_version: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)


def _resolve_proposal(lookup: ProposalLookup, proposal_id: str) -> Proposal | None:
    """Resolve one proposal from a mapping or callable lookup."""
    if isinstance(lookup, Mapping):
        candidate = lookup.get(proposal_id)
        return candidate if isinstance(candidate, Proposal) else None
    return lookup(proposal_id)


def _row_to_record(row: ApprovalRow) -> ApprovalRecord:
    """Rehydrate an immutable record from its persisted row."""
    created = row.created_at
    if created.tzinfo is None or created.tzinfo.utcoffset(created) is None:
        created = created.replace(tzinfo=UTC)
    return ApprovalRecord(
        approval_id=row.approval_id,
        exception_id=row.exception_id,
        proposal_id=row.proposal_id,
        proposal_version=row.proposal_version,
        content_hash=row.content_hash,
        decision=ApprovalDecision(row.decision),
        approver_id=row.approver_id,
        idempotency_key=row.idempotency_key,
        state_version=row.state_version,
        created_at=created,
    )


class ApprovalService:
    """Ten-gate HITL decision service with atomic CAS persistence.

    The service owns an engine over the same database as
    ``ExceptionRepository``; each method opens short sessions so fresh
    handles observe committed decisions (crash-resume).
    """

    def __init__(self, engine: Engine, *, amount_threshold: Decimal) -> None:
        """Bind the service to an engine and set the policy threshold.

        Args:
            engine: SQLAlchemy engine shared with ``ExceptionRepository``.
            amount_threshold: Exclusive policy ceiling — proposals with
                ``amount <= threshold`` pass gate 8 (``Decimal``-only;
                ``float``/``bool`` are rejected).
        """
        if isinstance(amount_threshold, (bool, float)):
            raise TypeError("amount_threshold must be Decimal: float/bool money is rejected.")
        if not isinstance(amount_threshold, Decimal) or not amount_threshold.is_finite():
            raise ValueError("amount_threshold must be a finite Decimal.")
        if amount_threshold <= Decimal("0"):
            raise ValueError("amount_threshold must be positive.")
        self._engine = engine
        self._threshold = amount_threshold
        Base.metadata.create_all(engine)

    @property
    def amount_threshold(self) -> Decimal:
        """Return the configured policy ceiling."""
        return self._threshold

    def get_by_idempotency_key(self, idempotency_key: str) -> ApprovalRecord | None:
        """Read one record by key (resume path after a crash)."""
        with Session(self._engine) as session:
            row = (
                session.query(ApprovalRow)
                .filter(ApprovalRow.idempotency_key == idempotency_key)
                .one_or_none()
            )
            return _row_to_record(row) if row is not None else None

    def get_for_exception(self, exception_id: str) -> list[ApprovalRecord]:
        """Return all records bound to one exception (oldest first)."""
        with Session(self._engine) as session:
            rows = (
                session.query(ApprovalRow)
                .filter(ApprovalRow.exception_id == exception_id)
                .order_by(ApprovalRow.created_at.asc())
                .all()
            )
            return [_row_to_record(row) for row in rows]

    def policy_allows(self, proposal: Proposal) -> bool:
        """Deterministically decide whether policy admits a proposal.

        Args:
            proposal: The pinned proposal under review.

        Returns:
            True only when the action is sandbox-bookable and
            ``proposal.amount <= threshold``.
        """
        return proposal.action in _SANDBOX_ACTIONS and proposal.amount <= self._threshold

    def decide(
        self,
        cmd: ApprovalCommand,
        repo: object,
        proposals_lookup: ProposalLookup,
    ) -> ApprovalRecord:
        """Apply one HITL decision through the ten ordered gates.

        Args:
            cmd: Validated decision command (no money/action fields).
            repo: ``ExceptionRepository``-shaped store exposing ``get``.
            proposals_lookup: Mapping or callable resolving proposals.

        Returns:
            The persisted record — freshly decided, or the prior record
            on an idempotent replay (gate 9).

        Raises:
            IllegalTransitionError: Gates 1, 2 (non-terminal), 4, 7, 8.
            ConcurrencyConflictError: Gates 2 (terminal), 3, 9 (cross
                binding), 10 (lost CAS race).
            ApprovalSkewError: Gates 5, 6.
        """
        get = repo.get
        target = (
            ExceptionState.APPROVED
            if cmd.decision is ApprovalDecision.APPROVED
            else ExceptionState.REJECTED
        )

        # Read-only prefetch backing gate 9; replays yield at gates 2/3.
        prior = self.get_by_idempotency_key(cmd.idempotency_key)

        # Gate 1: exception exists.
        snapshot = get(cmd.exception_id)
        if snapshot is None or not isinstance(snapshot, ExceptionAggregate):
            raise IllegalTransitionError(
                cmd.exception_id, "-", target.value, reason="exception not found"
            )

        # Gate 2: state is AWAITING_APPROVAL (replays yield to gate 9).
        if snapshot.state is not ExceptionState.AWAITING_APPROVAL:
            if (
                prior is not None
                and prior.exception_id == snapshot.exception_id
                and snapshot.state in _TERMINAL_STATES
            ):
                return prior
            if snapshot.state in _TERMINAL_STATES:
                raise ConcurrencyConflictError(
                    snapshot.exception_id,
                    cmd.expected_state_version,
                    snapshot.state_version,
                    detail=f"exception already decided ({snapshot.state.value})",
                )
            raise IllegalTransitionError(
                snapshot.exception_id,
                snapshot.state.value,
                target.value,
                reason=f"state {snapshot.state.value} is not AWAITING_APPROVAL",
            )

        # Gate 3: expected version matches (replays yield to gate 9).
        if cmd.expected_state_version != snapshot.state_version:
            if prior is not None and prior.exception_id == snapshot.exception_id:
                return prior
            raise ConcurrencyConflictError(
                snapshot.exception_id,
                cmd.expected_state_version,
                snapshot.state_version,
            )

        # Gate 4: proposal exists.
        proposal = _resolve_proposal(proposals_lookup, cmd.proposal_id)
        if proposal is None:
            raise IllegalTransitionError(
                snapshot.exception_id,
                snapshot.state.value,
                target.value,
                reason=f"unknown proposal {cmd.proposal_id}",
            )

        # Gate 5: pinned version matches.
        if proposal.version != cmd.proposal_version:
            raise ApprovalSkewError(
                f"Approval {approval_id_for(cmd.idempotency_key)} pins "
                f"({cmd.proposal_id}, v{cmd.proposal_version}) but proposal "
                f"is at v{proposal.version}."
            )

        # Gate 6: pinned hash matches AND stored hash verifies.
        pin = ApprovalPin(
            proposal_id=cmd.proposal_id,
            proposal_version=cmd.proposal_version,
            content_hash=cmd.proposal_content_hash,
            approval_id=approval_id_for(cmd.idempotency_key),
        )
        pin.verify(proposal.proposal_id, proposal.version, proposal.content_hash)
        if not verify_hash(proposal):
            raise ApprovalSkewError(
                f"Proposal {proposal.proposal_id} v{proposal.version} fails "
                "hash verification: stored content_hash drifted."
            )

        # Gate 7: proposal evidence is a subset of the sealed aggregate set.
        sealed = set(snapshot.evidence_ids)
        missing = [item for item in proposal.evidence_ids if item not in sealed]
        if missing:
            raise IllegalTransitionError(
                snapshot.exception_id,
                snapshot.state.value,
                target.value,
                reason=f"proposal evidence unsatisfied: {sorted(missing)} not verified",
            )

        # Gate 8: deterministic policy (sandbox-only action, amount ceiling).
        if not self.policy_allows(proposal):
            raise IllegalTransitionError(
                snapshot.exception_id,
                snapshot.state.value,
                target.value,
                reason=(
                    f"policy denied: action={proposal.action.value} "
                    f"amount={proposal.amount} threshold={self._threshold}"
                ),
            )

        # Gate 9: idempotency — seen key returns the prior record.
        if prior is not None:
            if prior.exception_id != snapshot.exception_id:
                raise ConcurrencyConflictError(
                    snapshot.exception_id,
                    cmd.expected_state_version,
                    snapshot.state_version,
                    detail=f"idempotency key already bound to {prior.exception_id}",
                )
            return prior

        record = ApprovalRecord.create(
            cmd=cmd,
            state_version=snapshot.state_version + 1,
            created_at=datetime.now(UTC),
        )
        return self._cas_apply(snapshot, target, record, approver=cmd.approver_id)

    def _cas_apply(
        self,
        snapshot: ExceptionAggregate,
        target: ExceptionState,
        record: ApprovalRecord,
        *,
        approver: str,
    ) -> ApprovalRecord:
        """Gate 10: atomic CAS to terminal state plus immutable record.

        One transaction advances the exception row (predicated on
        ``exception_id + state_version + state``), inserts the approval
        row, and appends the audit fact. Nothing schedules execution:
        ``execution_id`` is never set.

        Raises:
            ConcurrencyConflictError: Predicated ``UPDATE`` hit zero rows
                (a concurrent writer won), or the key raced another
                insert (returns the winner when it is ours).
        """
        with Session(self._engine) as session:
            stmt = (
                update(ExceptionRow)
                .where(
                    ExceptionRow.exception_id == snapshot.exception_id,
                    ExceptionRow.state_version == snapshot.state_version,
                    ExceptionRow.state == snapshot.state.value,
                )
                .values(
                    state=target.value,
                    state_version=ExceptionRow.state_version + 1,
                    approval_id=record.approval_id,
                    updated_at=record.created_at,
                )
            )
            result = session.execute(stmt)
            if result.rowcount != 1:
                session.rollback()
                current = self._current_version(snapshot.exception_id)
                self._audit_outcome(
                    snapshot,
                    target.value,
                    approver,
                    "REJECTED",
                    f"CONCURRENCY_CONFLICT expected={snapshot.state_version} actual={current}",
                    actual_version=current,
                )
                raise ConcurrencyConflictError(
                    snapshot.exception_id,
                    snapshot.state_version,
                    current,
                    detail="atomic CAS UPDATE affected 0 rows",
                )
            session.add(
                ApprovalRow(
                    approval_id=record.approval_id,
                    exception_id=record.exception_id,
                    proposal_id=record.proposal_id,
                    proposal_version=record.proposal_version,
                    content_hash=record.content_hash,
                    decision=record.decision.value,
                    approver_id=record.approver_id,
                    idempotency_key=record.idempotency_key,
                    state_version=record.state_version,
                    created_at=record.created_at,
                )
            )
            session.add(
                ExceptionAuditRow(
                    exception_id=snapshot.exception_id,
                    tenant_id=snapshot.tenant_id,
                    actor=approver,
                    from_state=snapshot.state.value,
                    attempted_state=target.value,
                    expected_version=snapshot.state_version,
                    actual_version=record.state_version,
                    outcome="APPLIED",
                    reason=f"{snapshot.state.value} -> {target.value} {record.approval_id}",
                    created_at=record.created_at,
                )
            )
            try:
                session.commit()
            except IntegrityError:
                # Key raced a concurrent insert: the winner owns the decision.
                session.rollback()
                winner = self.get_by_idempotency_key(record.idempotency_key)
                if winner is not None and winner.exception_id == record.exception_id:
                    logger.info(
                        "approval idempotency race key=%s winner=%s.",
                        record.idempotency_key,
                        winner.approval_id,
                    )
                    return winner
                current = self._current_version(snapshot.exception_id)
                raise ConcurrencyConflictError(
                    snapshot.exception_id,
                    snapshot.state_version,
                    current,
                    detail="idempotency key conflict on approval insert",
                ) from None
        logger.info(
            "approval decided id=%s exception=%s decision=%s v=%s.",
            record.approval_id,
            record.exception_id,
            record.decision.value,
            record.state_version,
        )
        return record

    def _current_version(self, exception_id: str) -> int:
        """Read the live aggregate version (-1 when the row is gone)."""
        with Session(self._engine) as session:
            row = session.get(ExceptionRow, exception_id)
            return row.state_version if row is not None else -1

    def _audit_outcome(
        self,
        snapshot: ExceptionAggregate,
        attempted_state: str,
        actor: str,
        outcome: str,
        reason: str,
        *,
        actual_version: int | None = None,
    ) -> None:
        """Append one audit fact without mutating the aggregate row."""
        with Session(self._engine) as session:
            session.add(
                ExceptionAuditRow(
                    exception_id=snapshot.exception_id,
                    tenant_id=snapshot.tenant_id,
                    actor=actor,
                    from_state=snapshot.state.value,
                    attempted_state=attempted_state,
                    expected_version=snapshot.state_version,
                    actual_version=(
                        actual_version if actual_version is not None else snapshot.state_version
                    ),
                    outcome=outcome,
                    reason=reason,
                    created_at=datetime.now(UTC),
                )
            )
            session.commit()
