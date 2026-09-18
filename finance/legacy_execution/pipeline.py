"""T3 pipeline orchestration for P6-07 deterministic execution (X5-X6).

Runs reservation -> intent -> artifact -> transport -> observation ->
ingestion -> record -> handoff in fixed order with one audit entry per
stage (stage id, input digests, permit/refuse plus code, artifact
hashes). E5 observation (verbatim ledger parse) and E6 ingestion
(cross-checks, recording, UNKNOWN) are distinct audited stages. The
first stage that refuses stops the chain; later stages never run.
T1/T2 stages arrive as injected callables against minimal local
protocols; observation, ingestion, record, and handoff default to the
real implementations. Key→batch binding is enforced on the injected
reservation store (durable authority) between intent and artifact. The
pipeline itself writes no store beyond ``record.py``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from finance.approval.refusals import ApprovalRefused
from finance.legacy_execution.handoff import ExecutionHandoff, build_handoff
from finance.legacy_execution.ingestion import (
    ArtifactView,
    IngestionOutcome,
    IngestionRefused,
    ReceiptView,
    _require_two_dp,
    _require_tz_aware,
    _result_key_for,
    ingest_observed,
    outcome_fingerprint,
)
from finance.legacy_execution.observation import (
    ObservationRefused,
    ObservedBatch,
    observe_legacy_result,
)
from finance.legacy_execution.record import ExecutionRecord, ExecutionRecordStore
from finance.legacy_execution.reservation import ReservationStore

STAGE_RESERVATION = "E1-reservation"
STAGE_INTENT = "E2-intent"
STAGE_OBSERVATION = "E5-observation"
STAGE_ARTIFACT = "E3-artifact"
STAGE_TRANSPORT = "E4-transport"
STAGE_INGESTION = "E6-ingestion"
STAGE_RECORD = "E6-record"
STAGE_HANDOFF = "handoff"
# E5 ledger observation is an explicit stage: the RESULT file read and
# verbatim parse happen here, verified cross-checks happen at E6-ingestion.


class ExecutionContext(BaseModel):
    """Frozen pipeline inputs (caller-supplied; the pipeline reads no clock)."""

    model_config = ConfigDict(frozen=True, strict=True)

    execution_id: str = Field(..., min_length=1)
    company_id: str = Field(..., min_length=1)
    situation_id: str = Field(..., min_length=1)
    authorization_id: str = Field(..., min_length=1)
    proposal_hash: str = Field(..., min_length=1)
    proposal_version: int = Field(..., ge=0)
    binding_digest: str = Field(..., min_length=1)
    expires_at: datetime
    now: datetime
    window_start: datetime
    window_seconds: int = Field(default=1800, ge=1)
    result_key: str | None = None

    @field_validator("expires_at", "now", "window_start")
    @classmethod
    def _check_tz(cls, value: datetime) -> datetime:
        """Require timezone-aware times (caller-supplied, no clock read)."""
        return _require_tz_aware("time", value)


class ReservationGrant(BaseModel):
    """Minimal local view of the T1 reservation seam (E1 permit output)."""

    model_config = ConfigDict(frozen=True, strict=True)

    execution_id: str = Field(..., min_length=1)
    batch_id: str = Field(..., min_length=1)
    company_id: str = Field(..., min_length=1)
    situation_id: str = Field(..., min_length=1)
    authorization_id: str = Field(..., min_length=1)
    proposal_hash: str = Field(..., min_length=1)
    proposal_version: int = Field(..., ge=0)
    binding_digest: str = Field(..., min_length=1)
    expires_at: datetime
    replayed: bool = False

    @field_validator("expires_at")
    @classmethod
    def _check_expiry_tz(cls, value: datetime) -> datetime:
        """Require a timezone-aware expiry."""
        return _require_tz_aware("expires_at", value)


class IntentView(BaseModel):
    """Minimal local view of the T1 intent seam (E2 projection output)."""

    model_config = ConfigDict(frozen=True, strict=True)

    execution_id: str = Field(..., min_length=1)
    action: str = Field(..., min_length=1)
    amount_exact: Decimal
    account_code: str = Field(..., min_length=1)
    company_id: str = Field(..., min_length=1)
    situation_id: str = Field(..., min_length=1)
    batch_id: str = Field(..., min_length=1)

    @field_validator("amount_exact")
    @classmethod
    def _check_amount_two_dp(cls, value: Decimal) -> Decimal:
        """Require the exact 2-dp projected amount (no drift, no rounding)."""
        return _require_two_dp("amount_exact", value)


class AuditEntry(BaseModel):
    """One append-only audit spine entry per stage (X6)."""

    model_config = ConfigDict(frozen=True, strict=True)

    stage: str = Field(..., min_length=1)
    input_digest: str = Field(..., min_length=1)
    permitted: bool
    code: str = Field(..., min_length=1)
    artifact_hashes: tuple[str, ...] = Field(default_factory=tuple)


class PipelineRefused(Exception):  # noqa: N818 -- contract refusal signal, not an error
    """Stage refusal signal: stop the chain, emit the code, change nothing."""

    def __init__(self, stage: str, code: str, message: str) -> None:
        """Record the refusing stage, code, and reason."""
        super().__init__(f"[{stage}/{code}] {message}")
        self.stage = stage
        self.code = code
        self.message = message


class PipelineResult(BaseModel):
    """Frozen pipeline outcome: permit with handoff, or first refusal."""

    model_config = ConfigDict(frozen=True, strict=True)

    execution_id: str = Field(..., min_length=1)
    permitted: bool
    code: str | None = None
    refused_stage: str | None = None
    outcome: IngestionOutcome | None = None
    handoff: ExecutionHandoff | None = None
    audit: tuple[AuditEntry, ...] = Field(default_factory=tuple)


ReservationStage = Callable[[ExecutionContext], ReservationGrant]
IntentStage = Callable[[ReservationGrant], IntentView]
ArtifactStage = Callable[[IntentView], ArtifactView]
TransportStage = Callable[[ArtifactView], ReceiptView]
ObservationStage = Callable[[ArtifactView, ReceiptView], ObservedBatch | None]
IngestionStage = Callable[
    [ArtifactView, ReceiptView, "ObservedBatch | None"], IngestionOutcome
]
RecordStage = Callable[[ReceiptView, IngestionOutcome], ExecutionRecord]
HandoffStage = Callable[[ExecutionRecord, IngestionOutcome], ExecutionHandoff]


def _digest(*parts: str) -> str:
    """Hash the canonical input summary (hashes, never raw money)."""
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _money(value: Decimal) -> str:
    """Format a total at exactly 2 dp for audit digests (never more)."""
    return f"{value:.2f}"


def run_execution(
    ctx: ExecutionContext,
    *,
    reservation: ReservationStage,
    intent: IntentStage,
    artifact: ArtifactStage,
    transport: TransportStage,
    observation: ObservationStage | None = None,
    ingestion: IngestionStage | None = None,
    record: RecordStage | None = None,
    handoff: HandoffStage | None = None,
    record_store: ExecutionRecordStore | None = None,
    reservation_store: ReservationStore | None = None,
    result_store: object | None = None,
    audit: list[AuditEntry] | None = None,
) -> PipelineResult:
    """Run the fixed E1-E6 order, short-circuiting on the first refusal.

    Args:
        ctx: Frozen execution context (ids, binding, times, window).
        reservation: T1 E1 stage (permit grant or raise refusal).
        intent: T1 E2 stage (projection or raise refusal).
        artifact: T2 E3 stage (OUTBOUND bytes or raise refusal).
        transport: T2 E4 stage (receipt or raise refusal).
        observation: E5 observation stage; defaults to reading the
            RESULT via ``result_store`` and parsing it verbatim
            (absent RESULT yields None for E6 UNKNOWN).
        ingestion: E6 ingestion stage; defaults to the real T3 ingest
            over the observed batch (must have ``result_store`` then).
        record: E6 record stage; defaults to claim/receipt/outcome via
            ``record_store`` (created ephemerally when None).
        handoff: Handoff stage; defaults to the real T3 §8 build.
        record_store: Execution record backing the default record stage.
        reservation_store: Durable key→batch binding authority used
            between intent and artifact (defaults to an ephemeral
            memory store; crash durability needs an engine-backed one).
        result_store: RESULT bucket reader for the default observe stage.
        audit: Caller-owned list receiving append-only entries.

    Returns:
        PipelineResult with the handoff on permit, or the first refusal
        stage plus code with later stages never run.
    """
    log: list[AuditEntry] = audit if audit is not None else []
    store = record_store if record_store is not None else ExecutionRecordStore()
    bindings = (
        reservation_store if reservation_store is not None else ReservationStore()
    )

    def observe_default(
        artifact_view: ArtifactView, receipt_view: ReceiptView
    ) -> ObservedBatch | None:
        del receipt_view
        if result_store is None or not hasattr(result_store, "read_result"):
            raise ValueError("Default observation needs a ResultReader result_store.")
        key = _result_key_for(
            ctx.company_id, artifact_view.batch_id, ctx.result_key
        )
        raw = result_store.read_result(key)  # type: ignore[union-attr]
        if raw is None:
            return None
        return observe_legacy_result(
            raw, batch_id=artifact_view.batch_id, company_id=ctx.company_id
        )

    def ingest_default(
        artifact_view: ArtifactView,
        receipt_view: ReceiptView,
        observed: ObservedBatch | None,
    ) -> IngestionOutcome:
        key = _result_key_for(
            ctx.company_id, artifact_view.batch_id, ctx.result_key
        )
        return ingest_observed(
            observed,
            artifact=artifact_view,
            receipt=receipt_view,
            company_id=ctx.company_id,
            result_key=key,
            result_sha256=observed.raw_sha256 if observed is not None else None,
            now=ctx.now,
            window_start=ctx.window_start,
            window_seconds=ctx.window_seconds,
        )

    def record_default(
        receipt_view: ReceiptView, outcome: IngestionOutcome
    ) -> ExecutionRecord:
        store.claim(
            ctx.execution_id, binding_digest=ctx.binding_digest,
            company_id=ctx.company_id, situation_id=ctx.situation_id,
            batch_id=receipt_view.batch_id, expires_at=ctx.expires_at,
        )
        store.attach_receipt(ctx.execution_id, receipt_view)
        return store.attach_outcome(ctx.execution_id, outcome)

    def handoff_default(
        record_row: ExecutionRecord, outcome: IngestionOutcome
    ) -> ExecutionHandoff:
        receipt_view = ReceiptView(
            execution_id=record_row.execution_id,
            batch_id=outcome.batch_id,
            key=record_row.receipt_key or "",
            sha256=record_row.receipt_sha256 or "",
            byte_count=0,
            timestamp=record_row.receipt_at or ctx.now,
        )
        current_artifact = artifact_cache["artifact"]
        return build_handoff(
            record=record_row, outcome=outcome, receipt=receipt_view,
            artifact=current_artifact, authorization_id=ctx.authorization_id,
            proposal_hash=ctx.proposal_hash,
            proposal_version=ctx.proposal_version, recorded_at=ctx.now,
        )

    observe_fn = observation if observation is not None else observe_default
    ingest_fn = ingestion if ingestion is not None else ingest_default
    record_fn = record if record is not None else record_default
    handoff_fn = handoff if handoff is not None else handoff_default
    artifact_cache: dict[str, ArtifactView] = {}

    def note(
        stage: str, digest: str, permitted: bool, code: str,
        hashes: tuple[str, ...] = (),
    ) -> None:
        log.append(
            AuditEntry(
                stage=stage, input_digest=digest, permitted=permitted,
                code=code, artifact_hashes=hashes,
            )
        )

    def refuse(
        stage: str, code: str, outcome: IngestionOutcome | None = None
    ) -> PipelineResult:
        note(stage, _digest(stage, ctx.execution_id, code), False, code)
        return PipelineResult(
            execution_id=ctx.execution_id, permitted=False, code=code,
            refused_stage=stage, outcome=outcome, handoff=None,
            audit=tuple(log),
        )

    try:
        grant = reservation(ctx)
    except PipelineRefused as exc:
        return refuse(exc.stage or STAGE_RESERVATION, exc.code)
    except ApprovalRefused as exc:
        return refuse(STAGE_RESERVATION, exc.code.value)
    note(
        STAGE_RESERVATION,
        _digest(STAGE_RESERVATION, grant.execution_id, grant.company_id,
                grant.situation_id, grant.proposal_hash,
                str(grant.proposal_version), grant.binding_digest),
        True, "PERMIT",
    )

    try:
        intent_view = intent(grant)
    except PipelineRefused as exc:
        return refuse(exc.stage or STAGE_INTENT, exc.code)
    except ApprovalRefused as exc:
        return refuse(STAGE_INTENT, exc.code.value)
    note(
        STAGE_INTENT,
        _digest(STAGE_INTENT, intent_view.execution_id, intent_view.batch_id,
                intent_view.action, _money(intent_view.amount_exact),
                intent_view.account_code),
        True, "PERMIT",
    )

    try:
        bindings.bind_batch(ctx.execution_id, intent_view.batch_id)
    except ApprovalRefused as exc:
        return refuse(STAGE_ARTIFACT, exc.code.value)
    except KeyError as exc:
        return refuse(STAGE_ARTIFACT, f"missing reservation: {exc}")

    try:
        artifact_view = artifact(intent_view)
    except PipelineRefused as exc:
        return refuse(exc.stage or STAGE_ARTIFACT, exc.code)
    except ApprovalRefused as exc:
        return refuse(STAGE_ARTIFACT, exc.code.value)
    artifact_cache["artifact"] = artifact_view
    note(
        STAGE_ARTIFACT,
        _digest(STAGE_ARTIFACT, artifact_view.execution_id,
                artifact_view.batch_id, str(artifact_view.record_count),
                _money(artifact_view.control_total)),
        True, "PERMIT", (artifact_view.outbound_sha256,),
    )

    try:
        receipt_view = transport(artifact_view)
    except PipelineRefused as exc:
        return refuse(exc.stage or STAGE_TRANSPORT, exc.code)
    except ApprovalRefused as exc:
        return refuse(STAGE_TRANSPORT, exc.code.value)
    note(
        STAGE_TRANSPORT,
        _digest(STAGE_TRANSPORT, receipt_view.execution_id,
                receipt_view.batch_id, receipt_view.key, receipt_view.sha256),
        True, "PERMIT",
        (artifact_view.outbound_sha256, receipt_view.sha256),
    )

    try:
        observed = observe_fn(artifact_view, receipt_view)
    except (PipelineRefused, ObservationRefused) as exc:
        return refuse(STAGE_OBSERVATION, exc.code)
    except ApprovalRefused as exc:
        return refuse(STAGE_OBSERVATION, exc.code.value)
    if observed is None:
        note(
            STAGE_OBSERVATION,
            _digest(STAGE_OBSERVATION, artifact_view.batch_id, "absent"),
            True, "ABSENT",
        )
    else:
        note(
            STAGE_OBSERVATION,
            _digest(
                STAGE_OBSERVATION, artifact_view.batch_id,
                str(len(observed.records)), observed.raw_sha256,
            ),
            True, "OBSERVED", (observed.raw_sha256,),
        )

    try:
        outcome = ingest_fn(artifact_view, receipt_view, observed)
    except (PipelineRefused, IngestionRefused) as exc:
        return refuse(STAGE_INGESTION, exc.code)
    except ApprovalRefused as exc:
        return refuse(STAGE_INGESTION, exc.code.value)
    note(
        STAGE_INGESTION,
        _digest(STAGE_INGESTION, outcome.execution_id, outcome.batch_id,
                outcome_fingerprint(outcome)),
        True, outcome.code or "RECORDED",
        tuple(h for h in (outcome.outbound_sha256, outcome.result_sha256)
              if h is not None),
    )

    try:
        record_row = record_fn(receipt_view, outcome)
    except (PipelineRefused, IngestionRefused) as exc:
        return refuse(STAGE_RECORD, exc.code, outcome)
    except ApprovalRefused as exc:
        return refuse(STAGE_RECORD, exc.code.value, outcome)
    note(
        STAGE_RECORD,
        _digest(STAGE_RECORD, record_row.execution_id,
                record_row.state.value, outcome_fingerprint(outcome)),
        True, "RECORDED",
    )

    try:
        handoff_out = handoff_fn(record_row, outcome)
    except PipelineRefused as exc:
        return refuse(exc.stage or STAGE_HANDOFF, exc.code, outcome)
    except ApprovalRefused as exc:
        return refuse(STAGE_HANDOFF, exc.code.value, outcome)
    note(
        STAGE_HANDOFF,
        _digest(STAGE_HANDOFF, handoff_out.execution_id,
                handoff_out.batch_id, handoff_out.outbound_sha256,
                handoff_out.result_sha256 or "absent"),
        True, "EMITTED",
        tuple(h for h in (handoff_out.outbound_sha256,
                          handoff_out.result_sha256) if h is not None),
    )
    return PipelineResult(
        execution_id=ctx.execution_id, permitted=True, code=None,
        refused_stage=None, outcome=outcome, handoff=handoff_out,
        audit=tuple(log),
    )
