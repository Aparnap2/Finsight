"""T3 result ingestion for P6-07 deterministic execution (stage E6, X35-X40).

Reads the legacy RESULT file, verifies it hash-first, cross-checks the
Decimal control total against the OUTBOUND artifact, and records a
per-record outcome. Late or missing results yield an explicit UNKNOWN
state, never an assumed verdict.

The wire codec is wrapped from ``finance.legacy.protocol`` (never
reimplemented). Sibling-owned seam shapes (T1 reservation/intent, T2
artifact/transport) are modelled as minimal local views; the owning
tracks reconcile field-for-field after merge.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from finance.legacy.protocol import PROTOCOL_VERSION, build_result_key
from finance.legacy_execution.observation import (
    ObservationRefused,
    ObservedBatch,
    observe_legacy_result,
)

logger = logging.getLogger(__name__)

EXEC_RESULT_CORRUPT = "EXEC_RESULT_CORRUPT"
EXEC_CONTROL_TOTAL_MISMATCH = "EXEC_CONTROL_TOTAL_MISMATCH"
EXEC_RESULT_UNKNOWN = "EXEC_RESULT_UNKNOWN"
RESULT_POLL_WINDOW_SECONDS = 1800
RESULT_POLL_INTERVAL_SECONDS = 60


def _require_tz_aware(field_name: str, value: datetime) -> datetime:
    """Return the timestamp or raise when naive (input hygiene, no clock)."""
    if not isinstance(value, datetime):
        raise TypeError(f"Field '{field_name}' must be a datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"Field '{field_name}' must be timezone-aware.")
    return value


def _require_two_dp(field_name: str, value: Decimal) -> Decimal:
    """Return the amount or raise when it is not exactly 2 dp (no rounding)."""
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise TypeError(f"Field '{field_name}' must be decimal.Decimal.")
    try:
        quantized = value.quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValueError(f"Field '{field_name}' must be 2 dp: {value!r}") from exc
    if quantized != value:
        raise ValueError(f"Field '{field_name}' must be exactly 2 dp: {value!r}")
    return quantized


class OutcomeLabel(StrEnum):
    """Batch outcome labels recorded by ingestion (X38-X39)."""

    ACCEPTED = "ACCEPTED"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


class ArtifactView(BaseModel):
    """Minimal local view of the T2 OUTBOUND artifact seam (E3 output).

    Field-for-field compatible with the sibling contract: execution id,
    logical batch id, file name, data-record count, Decimal control total,
    exact file bytes, and whole-file digest. ``amounts_by_sequence`` threads
    the per-record amounts the control cross-check (X37) needs, since RESULT
    lines carry codes and details but no amounts.
    """

    model_config = ConfigDict(frozen=True, strict=True)

    execution_id: str = Field(..., min_length=1)
    batch_id: str = Field(..., min_length=1)
    file_name: str = Field(..., min_length=1)
    record_count: int = Field(..., ge=0)
    control_total: Decimal
    file_bytes: bytes
    outbound_sha256: str = Field(..., min_length=1)
    amounts_by_sequence: dict[int, Decimal] = Field(default_factory=dict)

    @field_validator("control_total")
    @classmethod
    def _check_control_two_dp(cls, value: Decimal) -> Decimal:
        """Require an exact 2-dp Decimal control total."""
        return _require_two_dp("control_total", value)

    @field_validator("amounts_by_sequence")
    @classmethod
    def _check_amounts_two_dp(
        cls, value: dict[int, Decimal]
    ) -> dict[int, Decimal]:
        """Require exact 2-dp Decimal amounts for every mapped sequence."""
        for sequence, amount in value.items():
            if sequence < 1:
                raise ValueError(f"Sequence must be >= 1, got {sequence}")
            _require_two_dp(f"amounts_by_sequence[{sequence}]", amount)
        return value


class ReceiptView(BaseModel):
    """Minimal local view of the T2 transport receipt seam (E4 output)."""

    model_config = ConfigDict(frozen=True, strict=True)

    execution_id: str = Field(..., min_length=1)
    batch_id: str = Field(..., min_length=1)
    key: str = Field(..., min_length=1)
    sha256: str = Field(..., min_length=1)
    byte_count: int = Field(..., ge=0)
    timestamp: datetime

    @field_validator("timestamp")
    @classmethod
    def _check_tz(cls, value: datetime) -> datetime:
        """Require a timezone-aware receipt timestamp."""
        return _require_tz_aware("timestamp", value)


class PerRecordOutcome(BaseModel):
    """One recorded per-sequence RESULT fact (code consumed as given)."""

    model_config = ConfigDict(frozen=True, strict=True)

    sequence: int = Field(..., ge=1)
    code: str = Field(..., min_length=2, max_length=2)
    detail: str = Field(default="", max_length=50)

    @field_validator("code")
    @classmethod
    def _check_code(cls, value: str) -> str:
        """Restrict codes to the ledger vocabulary AC/RJ/DU (X29)."""
        if value not in ("AC", "RJ", "DU"):
            raise ValueError(f"code must be AC, RJ, or DU, got {value!r}")
        return value


class IngestionOutcome(BaseModel):
    """Frozen recorded outcome of one E6 ingestion event (X38-X40)."""

    model_config = ConfigDict(frozen=True, strict=True)

    execution_id: str = Field(..., min_length=1)
    batch_id: str = Field(..., min_length=1)
    company_id: str = Field(..., min_length=1)
    outcome: OutcomeLabel
    per_record: tuple[PerRecordOutcome, ...] = Field(default_factory=tuple)
    accepted_count: int = Field(..., ge=0)
    rejected_count: int = Field(..., ge=0)
    duplicate_count: int = Field(..., ge=0)
    control_total: Decimal
    accepted_total: Decimal
    rejected_total: Decimal
    outbound_sha256: str = Field(..., min_length=1)
    result_sha256: str | None = None
    result_key: str | None = None
    unknown_flag: bool = False
    code: str | None = None
    reason: str = Field(..., min_length=1)
    recorded_at: datetime
    poll_deadline: datetime | None = None

    @field_validator("control_total", "accepted_total", "rejected_total")
    @classmethod
    def _check_totals_two_dp(cls, value: Decimal) -> Decimal:
        """Require exact 2-dp Decimal totals (Decimal-only money)."""
        return _require_two_dp("total", value)

    @field_validator("recorded_at")
    @classmethod
    def _check_recorded_tz(cls, value: datetime) -> datetime:
        """Require a timezone-aware record time (caller-supplied, no clock)."""
        return _require_tz_aware("recorded_at", value)

    @property
    def result_total(self) -> Decimal:
        """Return accepted plus rejected totals (DU never double-counted)."""
        return self.accepted_total + self.rejected_total


class IngestionRefused(Exception):  # noqa: N818 -- contract refusal signal, not an error
    """E6 refusal signal: corrupt input records no outcome (X36)."""

    def __init__(self, code: str, message: str) -> None:
        """Record the machine-readable code and human-readable reason."""
        super().__init__(f"[E6-ingestion/{code}] {message}")
        self.code = code
        self.stage = "E6-ingestion"
        self.message = message


class ResultReader(Protocol):
    """Minimal local protocol for the RESULT bucket read seam (FakeS3)."""

    def read_result(self, key: str) -> bytes | None:
        """Return RESULT bytes, or None when the RESULT has not landed."""
        ...  # pragma: no cover - protocol shape only


def outcome_fingerprint(outcome: IngestionOutcome) -> str:
    """Return the sha256 of the canonical outcome JSON (replay identity)."""
    return hashlib.sha256(outcome.model_dump_json().encode("utf-8")).hexdigest()


def _result_key_for(
    company_id: str, batch_id: str, result_key: str | None
) -> str:
    """Return the RESULT key, deriving it when the caller passes none."""
    if result_key is not None:
        key = result_key
    else:
        key = build_result_key(company_id, batch_id, batch_id[7:15])
    prefix = f"{company_id}/{batch_id}/"
    if not key.startswith(prefix):
        raise IngestionRefused(
            EXEC_RESULT_CORRUPT,
            f"RESULT key {key!r} escapes the {prefix!r} seam.",
        )
    return key


def _unknown_outcome(
    *,
    artifact: ArtifactView,
    company_id: str,
    now: datetime,
    window_start: datetime,
    window_seconds: int,
) -> IngestionOutcome:
    """Record an explicit UNKNOWN outcome for a missing RESULT (X39)."""
    return IngestionOutcome(
        execution_id=artifact.execution_id,
        batch_id=artifact.batch_id,
        company_id=company_id,
        outcome=OutcomeLabel.UNKNOWN,
        per_record=(),
        accepted_count=0,
        rejected_count=0,
        duplicate_count=0,
        control_total=artifact.control_total,
        accepted_total=Decimal("0.00"),
        rejected_total=Decimal("0.00"),
        outbound_sha256=artifact.outbound_sha256,
        result_sha256=None,
        result_key=None,
        unknown_flag=True,
        code=EXEC_RESULT_UNKNOWN,
        reason=(
            "No verifiable RESULT in window; asserts nothing about "
            "success or failure and never auto-transitions the case."
        ),
        recorded_at=now,
        poll_deadline=window_start + timedelta(seconds=window_seconds),
    )


def ingest_result(
    store: ResultReader,
    receipt: ReceiptView,
    *,
    artifact: ArtifactView,
    company_id: str,
    result_key: str | None = None,
    now: datetime,
    window_start: datetime,
    window_seconds: int = RESULT_POLL_WINDOW_SECONDS,
) -> IngestionOutcome:
    """Ingest the RESULT file for one execution (X35-X39).

    Composed entry: reads the RESULT, observes it via E5
    (:func:`observation.observe_legacy_result`), then records via
    :func:`ingest_observed` (E6). The pipeline audits both stages
    separately; this composer exists for single-call unit coverage.

    Args:
        store: RESULT bucket reader (FakeS3 in tests; no network here).
        receipt: T2 transport receipt bound to this execution and batch.
        artifact: T2 OUTBOUND artifact bound to this execution and batch.
        company_id: Bound company scoping the RESULT key prefix.
        result_key: Explicit RESULT key; derived from the seam when None.
        now: Caller-supplied tz-aware observation time (no clock read).
        window_start: Caller-supplied tz-aware poll window start.
        window_seconds: Poll window length (default 30 minutes per X39).

    Returns:
        The frozen recorded outcome (ACCEPTED, PARTIAL, REJECTED, UNKNOWN).

    Raises:
        IngestionRefused: EXEC_RESULT_CORRUPT on seam, shape, checksum,
            sequence, or amount-mapping failures. Raw bytes are logged;
            no outcome is recorded and no retry runs against corrupt data.
    """
    _require_tz_aware("now", now)
    _require_tz_aware("window_start", window_start)
    if receipt.execution_id != artifact.execution_id:
        raise IngestionRefused(
            EXEC_RESULT_CORRUPT,
            "Artifact/receipt execution seam skew: "
            f"{artifact.execution_id!r} vs {receipt.execution_id!r}.",
        )
    if receipt.batch_id != artifact.batch_id:
        raise IngestionRefused(
            EXEC_RESULT_CORRUPT,
            "Artifact/receipt batch seam skew: "
            f"{artifact.batch_id!r} vs {receipt.batch_id!r}.",
        )
    if hashlib.sha256(artifact.file_bytes).hexdigest() != artifact.outbound_sha256:
        raise IngestionRefused(
            EXEC_RESULT_CORRUPT,
            "Artifact bytes do not hash to outbound_sha256 (input hygiene).",
        )

    key = _result_key_for(company_id, artifact.batch_id, result_key)
    raw = store.read_result(key)
    if raw is None:
        _require_tz_aware("now", now)
        _require_tz_aware("window_start", window_start)
        return _unknown_outcome(
            artifact=artifact, company_id=company_id, now=now,
            window_start=window_start, window_seconds=window_seconds,
        )
    result_sha256 = hashlib.sha256(raw).hexdigest()
    try:
        observed = observe_legacy_result(
            raw, batch_id=artifact.batch_id, company_id=company_id
        )
    except ObservationRefused as exc:
        raise IngestionRefused(EXEC_RESULT_CORRUPT, str(exc)) from exc
    return ingest_observed(
        observed,
        artifact=artifact,
        receipt=receipt,
        company_id=company_id,
        result_key=key,
        result_sha256=result_sha256,
        now=now,
        window_start=window_start,
        window_seconds=window_seconds,
    )


def ingest_observed(
    observed: ObservedBatch | None,
    *,
    artifact: ArtifactView,
    receipt: ReceiptView,
    company_id: str,
    result_key: str,
    result_sha256: str | None,
    now: datetime,
    window_start: datetime,
    window_seconds: int = RESULT_POLL_WINDOW_SECONDS,
) -> IngestionOutcome:
    """Ingest one E5-observed batch: cross-checks, recording, UNKNOWN (E6).

    Takes the verbatim observation (E5 output) instead of raw bytes, so
    the parse layer and the agreement layer stay distinct stages with
    distinct audit entries. A ``None`` observation (RESULT absent)
    records UNKNOWN; anything else runs the full X35-X38 verification.

    Args:
        observed: The E5 observed batch, or None when the RESULT has
            not landed.
        artifact: T2 OUTBOUND artifact bound to this execution and batch.
        receipt: T2 transport receipt bound to this execution and batch.
        company_id: Bound company.
        result_key: Explicit RESULT key (already derived by the caller).
        result_sha256: SHA-256 over the observed bytes (None when absent).
        now: Caller-supplied tz-aware observation time (no clock read).
        window_start: Caller-supplied tz-aware poll window start.
        window_seconds: Poll window length.

    Returns:
        The frozen recorded outcome (ACCEPTED, PARTIAL, REJECTED, UNKNOWN).

    Raises:
        IngestionRefused: EXEC_RESULT_CORRUPT on shape, version, batch,
            sequence, or amount-mapping failures.
    """
    _require_tz_aware("now", now)
    _require_tz_aware("window_start", window_start)
    if receipt.execution_id != artifact.execution_id:
        raise IngestionRefused(
            EXEC_RESULT_CORRUPT,
            "Artifact/receipt execution seam skew: "
            f"{artifact.execution_id!r} vs {receipt.execution_id!r}.",
        )
    if receipt.batch_id != artifact.batch_id:
        raise IngestionRefused(
            EXEC_RESULT_CORRUPT,
            "Artifact/receipt batch seam skew: "
            f"{artifact.batch_id!r} vs {receipt.batch_id!r}.",
        )
    if hashlib.sha256(artifact.file_bytes).hexdigest() != artifact.outbound_sha256:
        raise IngestionRefused(
            EXEC_RESULT_CORRUPT,
            "Artifact bytes do not hash to outbound_sha256 (input hygiene).",
        )
    if observed is None:
        return _unknown_outcome(
            artifact=artifact, company_id=company_id, now=now,
            window_start=window_start, window_seconds=window_seconds,
        )
    key = result_key
    parsed = observed.records
    assert result_sha256 is not None

    for entry in parsed:
        if entry.version != PROTOCOL_VERSION:
            raise IngestionRefused(
                EXEC_RESULT_CORRUPT,
                f"RESULT version skew {entry.version!r} in {key!r}.",
            )
        if entry.batch_id != artifact.batch_id:
            raise IngestionRefused(
                EXEC_RESULT_CORRUPT,
                f"RESULT batch skew {entry.batch_id!r} in {key!r}.",
            )
    sequences = sorted(entry.sequence for entry in parsed)
    expected = list(range(1, artifact.record_count + 1))
    if sequences != expected:
        raise IngestionRefused(
            EXEC_RESULT_CORRUPT,
            f"RESULT sequence skew in {key!r}: got {sequences}, "
            f"OUTBOUND expects {expected}.",
        )

    per_record = tuple(
        PerRecordOutcome(
            sequence=entry.sequence, code=entry.code,
            detail=entry.detail,
        )
        for entry in sorted(parsed, key=lambda e: e.sequence)
    )
    accepted = tuple(r for r in per_record if r.code == "AC")
    rejected = tuple(r for r in per_record if r.code == "RJ")
    duplicates = tuple(r for r in per_record if r.code == "DU")

    if artifact.amounts_by_sequence:
        amounts = dict(artifact.amounts_by_sequence)
    elif artifact.record_count == 1:
        amounts = {1: artifact.control_total}
    else:
        amounts = {}
    missing = sorted(seq for seq in sequences if seq not in amounts)
    if missing:
        raise IngestionRefused(
            EXEC_RESULT_CORRUPT,
            f"Amount mapping missing sequences {missing}; "
            "control cross-check cannot run on assumed amounts.",
        )
    accepted_total = sum((amounts[r.sequence] for r in accepted), Decimal("0.00"))
    rejected_total = sum((amounts[r.sequence] for r in rejected), Decimal("0.00"))
    duplicate_total = sum((amounts[r.sequence] for r in duplicates), Decimal("0.00"))
    attributed = accepted_total + rejected_total + duplicate_total

    if attributed != artifact.control_total:
        return IngestionOutcome(
            execution_id=artifact.execution_id,
            batch_id=artifact.batch_id,
            company_id=company_id,
            outcome=OutcomeLabel.REJECTED,
            per_record=per_record,
            accepted_count=0,
            rejected_count=len(accepted) + len(rejected),
            duplicate_count=len(duplicates),
            control_total=artifact.control_total,
            accepted_total=Decimal("0.00"),
            rejected_total=artifact.control_total,
            outbound_sha256=artifact.outbound_sha256,
            result_sha256=result_sha256,
            result_key=key,
            unknown_flag=False,
            code=EXEC_CONTROL_TOTAL_MISMATCH,
            reason=(
                f"Control cross-check failed: attributed {attributed} "
                f"vs OUTBOUND {artifact.control_total}; "
                "recorded REJECTED in full, no partial acceptance."
            ),
            recorded_at=now,
            poll_deadline=None,
        )

    if not accepted and not rejected:
        label = OutcomeLabel.REJECTED
        reason = (
            "No accepted lines; duplicates resolve to the original "
            "outcome at the record layer without double-counting."
        )
    elif not rejected and all(r.code in ("AC", "DU") for r in per_record):
        label = OutcomeLabel.ACCEPTED
        reason = "All non-duplicate lines accepted; DU resolves to original."
    elif not accepted:
        label = OutcomeLabel.REJECTED
        reason = "No lines accepted; rejected records queue for human review."
    else:
        label = OutcomeLabel.PARTIAL
        reason = (
            "Mixed acceptance preserved as partial; rejected records "
            "are never auto-retried by this chain."
        )
    return IngestionOutcome(
        execution_id=artifact.execution_id,
        batch_id=artifact.batch_id,
        company_id=company_id,
        outcome=label,
        per_record=per_record,
        accepted_count=len(accepted),
        rejected_count=len(rejected),
        duplicate_count=len(duplicates),
        control_total=artifact.control_total,
        accepted_total=accepted_total,
        rejected_total=rejected_total,
        outbound_sha256=artifact.outbound_sha256,
        result_sha256=result_sha256,
        result_key=key,
        unknown_flag=False,
        code=None,
        reason=reason,
        recorded_at=now,
        poll_deadline=None,
    )


def reconcile_late_result(
    store: ResultReader,
    receipt: ReceiptView,
    *,
    artifact: ArtifactView,
    company_id: str,
    result_key: str | None = None,
    now: datetime,
    window_start: datetime,
    window_seconds: int = RESULT_POLL_WINDOW_SECONDS,
    prior_unknown: IngestionOutcome,
) -> IngestionOutcome:
    """Ingest a RESULT that arrived after UNKNOWN was recorded (X40).

    Runs the standard X35-X38 verification as a new recording event; the
    caller links it to the same execution id while the UNKNOWN entry is
    preserved in history (see ``record.ExecutionRecordStore``).

    Args:
        store: RESULT bucket reader.
        receipt: T2 transport receipt bound to this execution and batch.
        artifact: T2 OUTBOUND artifact bound to this execution and batch.
        company_id: Bound company scoping the RESULT key prefix.
        result_key: Explicit RESULT key; derived from the seam when None.
        now: Caller-supplied tz-aware observation time (no clock read).
        window_start: Caller-supplied tz-aware poll window start.
        window_seconds: Poll window length.
        prior_unknown: The recorded UNKNOWN outcome being reconciled.

    Returns:
        The freshly verified outcome, or a new UNKNOWN when still missing.

    Raises:
        ValueError: When ``prior_unknown`` is not an UNKNOWN outcome.
        IngestionRefused: When the late bytes are corrupt (X36).
    """
    if prior_unknown.outcome != OutcomeLabel.UNKNOWN or not prior_unknown.unknown_flag:
        raise ValueError("reconcile_late_result requires a prior_unknown UNKNOWN.")
    return ingest_result(
        store, receipt, artifact=artifact, company_id=company_id,
        result_key=result_key, now=now, window_start=window_start,
        window_seconds=window_seconds,
    )
