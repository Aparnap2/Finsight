"""T3 execution record store for P6-07 deterministic execution (A2-A3, X41-X44).

The record is keyed by ``execution_id`` (== the G7 ``idempotency_key``) and
moves RESERVED -> RECEIPTED -> DECIDED, recorded and never edited. Later
presentations replay-read the recorded outcome byte-identically; a second
batch id for one key refuses with AUTHORIZATION_REPLAYED; ledger-side DU
resolves to the original outcome without double-counting; a late RESULT
after UNKNOWN supersedes by pointer with history preserved.

Refusal vocabulary (AUTHORIZATION_REPLAYED, AUTHORIZATION_SCOPE_ESCAPE,
AUTHORIZATION_EXPIRED) is the frozen T1/E1 contract signal raised via
``finance.approval.refusals.ApprovalRefused`` so pipeline propagation
matches the owning track field-for-field at reconciliation.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from finance.approval.refusals import ApprovalRefused, RefusalCode
from finance.legacy_execution.ingestion import (
    IngestionOutcome,
    ReceiptView,
    _require_tz_aware,
    outcome_fingerprint,
)


class RecordState(StrEnum):
    """Durable reservation states (A2: recorded, never edited)."""

    RESERVED = "RESERVED"
    RECEIPTED = "RECEIPTED"
    DECIDED = "DECIDED"


class RecordCollision(Exception):  # noqa: N818 -- contract refusal signal, not an error
    """Pre-existing row under a foreign binding: escalate, never merge."""

    def __init__(self, execution_id: str, message: str) -> None:
        """Record the colliding execution id and escalation reason."""
        super().__init__(f"[record/COLLISION {execution_id}] {message}")
        self.execution_id = execution_id
        self.message = message


class RecordTransitionError(Exception):
    """Illegal record transition: integrity wins over retransmission."""

    def __init__(self, execution_id: str, message: str) -> None:
        """Record the execution id and the refused transition."""
        super().__init__(f"[record/TRANSITION {execution_id}] {message}")
        self.execution_id = execution_id
        self.message = message


class ExecutionRecord(BaseModel):
    """One durable execution row keyed by execution id (PK, frozen)."""

    model_config = ConfigDict(frozen=True, strict=True)

    execution_id: str = Field(..., min_length=1)
    binding_digest: str = Field(..., min_length=1)
    company_id: str = Field(..., min_length=1)
    situation_id: str = Field(..., min_length=1)
    batch_id: str | None = None
    expires_at: datetime
    state: RecordState = RecordState.RESERVED
    receipt_key: str | None = None
    receipt_sha256: str | None = None
    receipt_at: datetime | None = None
    outcome: IngestionOutcome | None = None
    history: tuple[IngestionOutcome, ...] = Field(default_factory=tuple)
    replay_count: int = Field(default=0, ge=0)

    @field_validator("expires_at")
    @classmethod
    def _check_expiry_tz(cls, value: datetime) -> datetime:
        """Require a timezone-aware expiry (caller-supplied, no clock)."""
        return _require_tz_aware("expires_at", value)


class ExecutionRecordStore:
    """In-memory execution record with CAS claim and replay-read semantics.

    T1 owns the durable store; this class implements the T3 record
    behaviors against the same shapes so the coordinator can reconcile
    onto the owning persistence without behavior drift.
    """

    def __init__(self) -> None:
        """Start with an empty row map (no I/O, no clock)."""
        self._rows: dict[str, ExecutionRecord] = {}

    def claimed(self, execution_id: str) -> ExecutionRecord | None:
        """Return the reservation row, or None (T1 reservation query seam)."""
        return self._rows.get(execution_id)

    def claim(
        self,
        execution_id: str,
        *,
        binding_digest: str,
        company_id: str,
        situation_id: str,
        batch_id: str | None,
        expires_at: datetime,
    ) -> tuple[ExecutionRecord, bool]:
        """Atomically claim the execution id (A2 insert-or-read).

        Exactly one claimant wins; losers read the winner's row and follow
        the replay-read path. A second batch id for one key refuses with
        AUTHORIZATION_REPLAYED before any PUT (R-4/X21). A foreign binding
        on a pre-existing row escalates with RecordCollision.

        Returns:
            The row plus True when this call created it, False on replay.
        """
        existing = self._rows.get(execution_id)
        if existing is None:
            row = ExecutionRecord(
                execution_id=execution_id, binding_digest=binding_digest,
                company_id=company_id, situation_id=situation_id,
                batch_id=batch_id, expires_at=_require_tz_aware(
                    "expires_at", expires_at),
            )
            self._rows[execution_id] = row
            return row, True
        if existing.binding_digest != binding_digest:
            raise RecordCollision(
                execution_id,
                "Pre-existing row carries a foreign authorization binding; "
                "escalate for operator triage, never merge.",
            )
        if (
            batch_id is not None
            and existing.batch_id is not None
            and batch_id != existing.batch_id
        ):
            raise ApprovalRefused(
                RefusalCode.AUTHORIZATION_REPLAYED,
                "E1",
                f"Second batch {batch_id!r} for one execution id; "
                "a new id needs a new authorization cycle.",
            )
        if existing.batch_id is None and batch_id is not None:
            row = existing.model_copy(update={"batch_id": batch_id})
            self._rows[execution_id] = row
            return row, False
        return existing, False

    def attach_receipt(
        self, execution_id: str, receipt: ReceiptView
    ) -> ExecutionRecord:
        """Attach the transport receipt (RESERVED -> RECEIPTED, A2).

        Same key plus digest replays idempotently (R-2). Differing bytes
        refuse: integrity and collision semantics win over retransmission
        and no recovery path reserializes.
        """
        row = self._require_row(execution_id)
        if receipt.execution_id != execution_id:
            raise RecordTransitionError(
                execution_id, "Receipt execution seam skew; refuse, change nothing.",
            )
        if row.batch_id is not None and receipt.batch_id != row.batch_id:
            raise RecordTransitionError(
                execution_id, "Receipt batch seam skew; refuse, change nothing.",
            )
        if row.receipt_key is not None:
            if (row.receipt_key, row.receipt_sha256) == (receipt.key, receipt.sha256):
                return row
            raise RecordTransitionError(
                execution_id,
                "Receipt bytes differ from the recorded receipt; "
                "escalate, never rewrite financial meaning.",
            )
        updated = row.model_copy(
            update={
                "batch_id": row.batch_id or receipt.batch_id,
                "state": RecordState.RECEIPTED,
                "receipt_key": receipt.key,
                "receipt_sha256": receipt.sha256,
                "receipt_at": receipt.timestamp,
            }
        )
        self._rows[execution_id] = updated
        return updated

    def attach_outcome(
        self, execution_id: str, outcome: IngestionOutcome
    ) -> ExecutionRecord:
        """Attach the ingestion outcome (-> DECIDED, X38-X40).

        Byte-identical replays return the recorded row with a bumped replay
        count (R-1/R-2). A non-UNKNOWN outcome after UNKNOWN supersedes by
        pointer with the UNKNOWN entry preserved in history (R-5/X40). Any
        other second distinct outcome refuses: exactly one effect exists.
        """
        row = self._require_row(execution_id)
        if outcome.execution_id != execution_id:
            raise RecordTransitionError(
                execution_id, "Outcome execution seam skew; refuse, change nothing.",
            )
        if row.outcome is not None:
            if outcome_fingerprint(row.outcome) == outcome_fingerprint(outcome):
                updated = row.model_copy(
                    update={"replay_count": row.replay_count + 1}
                )
                self._rows[execution_id] = updated
                return updated
            if row.outcome.outcome == "UNKNOWN" and outcome.outcome != "UNKNOWN":
                updated = row.model_copy(
                    update={
                        "state": RecordState.DECIDED,
                        "outcome": outcome,
                        "history": (*row.history, row.outcome),
                    }
                )
                self._rows[execution_id] = updated
                return updated
            raise RecordTransitionError(
                execution_id,
                "A distinct outcome is already recorded; replay-read "
                "the original instead of recording a second effect.",
            )
        updated = row.model_copy(
            update={"state": RecordState.DECIDED, "outcome": outcome}
        )
        self._rows[execution_id] = updated
        return updated

    def replay(
        self,
        execution_id: str,
        *,
        binding_digest: str | None = None,
        at: datetime | None = None,
    ) -> IngestionOutcome | None:
        """Replay-read the recorded outcome without re-executing (X42).

        Drifted bindings refuse with AUTHORIZATION_SCOPE_ESCAPE (R-7) and
        presentations past expiry refuse with AUTHORIZATION_EXPIRED (R-8).
        Replays during the UNKNOWN window return UNKNOWN (R-6).
        """
        row = self._rows.get(execution_id)
        if row is None:
            return None
        if binding_digest is not None and binding_digest != row.binding_digest:
            raise ApprovalRefused(
                RefusalCode.AUTHORIZATION_SCOPE_ESCAPE,
                "E1",
                "Replay binding drifted from the recorded authorization.",
            )
        if at is not None:
            _require_tz_aware("at", at)
            if at > row.expires_at:
                raise ApprovalRefused(
                    RefusalCode.AUTHORIZATION_EXPIRED,
                    "E1",
                    "Replay presented after expires_at; "
                    "renewal is a fresh P6-06 decision.",
                )
        if row.outcome is not None:
            self._rows[execution_id] = row.model_copy(
                update={"replay_count": row.replay_count + 1}
            )
        current = self._rows[execution_id]
        return current.outcome

    def resolve_ledger_duplicate(self, execution_id: str) -> IngestionOutcome:
        """Resolve a ledger-side DU to the original outcome (R-3/A3b).

        The DU lines are recorded verbatim by ingestion; this path returns
        the already-recorded outcome with no reprocessing and no change to
        any total. Raises when nothing was recorded yet.
        """
        row = self._require_row(execution_id)
        if row.outcome is None:
            raise RecordTransitionError(
                execution_id, "Ledger DU with no recorded outcome to resolve to.",
            )
        self._rows[execution_id] = row.model_copy(
            update={"replay_count": row.replay_count + 1}
        )
        return row.outcome

    def refuse_new_batch(
        self, execution_id: str, attempted_batch_id: str
    ) -> ExecutionRecord:
        """Enforce one batch id per execution id (R-4/X21/X32).

        Re-presenting the bound batch id returns the row; attempting a new
        one refuses with AUTHORIZATION_REPLAYED before any PUT.
        """
        row = self._require_row(execution_id)
        if row.batch_id is not None and attempted_batch_id != row.batch_id:
            raise ApprovalRefused(
                RefusalCode.AUTHORIZATION_REPLAYED,
                "E1",
                f"Second batch {attempted_batch_id!r} for one execution id; "
                "a new id needs a new authorization cycle.",
            )
        return row

    def _require_row(self, execution_id: str) -> ExecutionRecord:
        """Return the row or raise (claim precedes every later stage)."""
        row = self._rows.get(execution_id)
        if row is None:
            raise RecordTransitionError(
                execution_id, "No reservation row; E1 claim must come first.",
            )
        return row
