"""T3 verification handoff for P6-07 deterministic execution (X45-X47, §8).

Builds the exact artifact P6-08 consumes to prove the outcome. The handoff
is data, never a verdict: it asserts bytes, codes, totals, and hashes, and
carries no EXECUTION_VERIFIED/FAILED judgment, no case close, and no
residual-variance math. Absent RESULT data leaves result fields null with
``unknown_flag`` true, never zero-filled.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from finance.legacy_execution.ingestion import (
    ArtifactView,
    IngestionOutcome,
    OutcomeLabel,
    ReceiptView,
    _require_two_dp,
    _require_tz_aware,
)
from finance.legacy_execution.record import ExecutionRecord


class PerRecordEntry(BaseModel):
    """One per-sequence handoff fact: sequence, ledger code, verbatim detail."""

    model_config = ConfigDict(frozen=True, strict=True)

    sequence: int = Field(..., ge=1)
    code: str = Field(..., min_length=2, max_length=2)
    detail: str = Field(default="", max_length=50)


class ExecutionHandoff(BaseModel):
    """Frozen §8 handoff shape (X46, consumed verbatim by P6-08)."""

    model_config = ConfigDict(frozen=True, strict=True)

    execution_id: str = Field(..., min_length=1)
    authorization_id: str = Field(..., min_length=1)
    proposal_hash: str = Field(..., min_length=1)
    proposal_version: int = Field(..., ge=0)
    company_id: str = Field(..., min_length=1)
    situation_id: str = Field(..., min_length=1)
    batch_id: str = Field(..., min_length=1)
    s3_outbound_key: str = Field(..., min_length=1)
    outbound_sha256: str = Field(..., min_length=1)
    control_total: Decimal
    record_count: int = Field(..., ge=0)
    accepted_count: int = Field(..., ge=0)
    rejected_count: int = Field(..., ge=0)
    accepted_total: Decimal | None = None
    rejected_total: Decimal | None = None
    per_record: tuple[PerRecordEntry, ...] = Field(default_factory=tuple)
    result_key: str | None = None
    result_sha256: str | None = None
    outcome: str = Field(..., min_length=1)
    unknown_flag: bool = False
    recorded_at: datetime

    @field_validator("control_total")
    @classmethod
    def _check_control_two_dp(cls, value: Decimal) -> Decimal:
        """Require an exact 2-dp Decimal control total."""
        return _require_two_dp("control_total", value)

    @field_validator("accepted_total", "rejected_total")
    @classmethod
    def _check_optional_totals_two_dp(
        cls, value: Decimal | None
    ) -> Decimal | None:
        """Require exact 2-dp Decimal totals whenever results are present."""
        if value is None:
            return None
        return _require_two_dp("total", value)

    @field_validator("recorded_at")
    @classmethod
    def _check_recorded_tz(cls, value: datetime) -> datetime:
        """Require a timezone-aware record time (caller-supplied, no clock)."""
        return _require_tz_aware("recorded_at", value)

    @model_validator(mode="after")
    def _check_unknown_consistency(self) -> ExecutionHandoff:
        """Tie null result fields to unknown_flag (nulls, never zeros)."""
        unknown = self.outcome == OutcomeLabel.UNKNOWN.value
        if unknown != self.unknown_flag:
            raise ValueError("unknown_flag must be true exactly with UNKNOWN.")
        if unknown:
            if self.result_key is not None or self.result_sha256 is not None:
                raise ValueError("UNKNOWN handoff must leave result refs null.")
            if self.accepted_total is not None or self.rejected_total is not None:
                raise ValueError("UNKNOWN handoff must leave result totals null.")
        elif self.result_sha256 is None or self.result_key is None:
            raise ValueError("Recorded handoff must carry the RESULT refs.")
        return self


def build_handoff(
    *,
    record: ExecutionRecord,
    outcome: IngestionOutcome,
    receipt: ReceiptView,
    artifact: ArtifactView,
    authorization_id: str,
    proposal_hash: str,
    proposal_version: int,
    recorded_at: datetime,
) -> ExecutionHandoff:
    """Build the §8 handoff from the recorded outcome (integrity carrier).

    Carries both digests so P6-08 can re-verify bytes without trusting this
    chain's labels. Totals stay Decimal 2-dp; floats anywhere invalidate the
    handoff at the Pydantic boundary.

    Args:
        record: The durable execution row owning this outcome.
        outcome: The recorded ingestion outcome (pointer target).
        receipt: The transport receipt (OUTBOUND key provenance).
        artifact: The OUTBOUND artifact (counts, totals, digest).
        authorization_id: Bound G7 token id.
        proposal_hash: Pinned proposal hash.
        proposal_version: Pinned proposal version.
        recorded_at: Caller-supplied tz-aware record time (no clock read).

    Returns:
        The frozen handoff; data only, never a verdict.

    Raises:
        ValueError: On id seam skew or receipt/artifact digest mismatch.
    """
    if not (
        record.execution_id == outcome.execution_id == receipt.execution_id
        == artifact.execution_id
    ):
        raise ValueError("Handoff execution seam skew; refuse, change nothing.")
    if not (
        record.batch_id in (None, artifact.batch_id)
        and outcome.batch_id == receipt.batch_id == artifact.batch_id
    ):
        raise ValueError("Handoff batch seam skew; refuse, change nothing.")
    if receipt.sha256 != artifact.outbound_sha256:
        raise ValueError("Receipt digest differs from the artifact digest.")
    unknown = outcome.outcome == OutcomeLabel.UNKNOWN
    return ExecutionHandoff(
        execution_id=outcome.execution_id,
        authorization_id=authorization_id,
        proposal_hash=proposal_hash,
        proposal_version=proposal_version,
        company_id=outcome.company_id,
        situation_id=record.situation_id,
        batch_id=outcome.batch_id,
        s3_outbound_key=receipt.key,
        outbound_sha256=artifact.outbound_sha256,
        control_total=artifact.control_total,
        record_count=artifact.record_count,
        accepted_count=outcome.accepted_count,
        rejected_count=outcome.rejected_count,
        accepted_total=None if unknown else outcome.accepted_total,
        rejected_total=None if unknown else outcome.rejected_total,
        per_record=tuple(
            PerRecordEntry(
                sequence=entry.sequence, code=entry.code, detail=entry.detail
            )
            for entry in outcome.per_record
        ),
        result_key=outcome.result_key,
        result_sha256=outcome.result_sha256,
        outcome=outcome.outcome.value,
        unknown_flag=unknown,
        recorded_at=recorded_at,
    )
