"""Trajectory models — INPUT→OUTPUT→VERIFIER→TOOL→RESULT→FINAL ledger.

Frozen, tenant-safe, Pydantic strict. No secrets, no raw evidence bodies,
no PII beyond correlation/tenant/case identifiers. Every step carries
``correlation_id`` propagated from webhook fingerprint → S3 key → LLM
context → execution (observability boundary).
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

TrajectoryMode = Literal["fake", "replay", "live", "e2e"]
TrajectoryStepKind = Literal[
    "INPUT",
    "MODEL_OUTPUT",
    "VERIFIER",
    "TOOL",
    "TOOL_RESULT",
    "NEXT_OUTPUT",
    "FINAL",
]

_CORRELATION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,127}$")
_TENANT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,127}$")
_MAX_EVIDENCE_IDS = 32


class TrajectoryStep(BaseModel):
    """One immutable journal entry in the trajectory.

    Tenant-safe: only correlation/tenant/case ids, evidence ids, capability
    names and bounded reason codes are retained. Raw Gmail/Sheets bodies,
    provider JSON, and secrets are never stored.
    """

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    kind: TrajectoryStepKind
    correlation_id: str = Field(min_length=1, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=128)
    timestamp: datetime
    latency_ms: float | None = Field(default=None, ge=0)
    status: str = Field(default="", max_length=64)
    evidence_ids: tuple[str, ...] = Field(default_factory=tuple)
    capability: str | None = Field(default=None, max_length=64)
    args: dict[str, str] | None = None
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    attempt: int = Field(default=0, ge=0)
    payload_ref: str | None = Field(default=None, max_length=256)

    @field_validator("correlation_id")
    @classmethod
    def _check_correlation(cls, value: str) -> str:
        if not _CORRELATION_RE.match(value):
            raise ValueError(f"correlation_id {value!r} violates tenant-safe pattern.")
        return value

    @field_validator("tenant_id")
    @classmethod
    def _check_tenant(cls, value: str) -> str:
        if not _TENANT_RE.match(value):
            raise ValueError(f"tenant_id {value!r} violates tenant-safe pattern.")
        return value

    @field_validator("timestamp")
    @classmethod
    def _check_ts(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be tz-aware.")
        return value

    @field_validator("evidence_ids")
    @classmethod
    def _check_evidence(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) > _MAX_EVIDENCE_IDS:
            raise ValueError(f"evidence_ids holds {len(value)} > {_MAX_EVIDENCE_IDS}.")
        seen: set[str] = set()
        for eid in value:
            if not eid.strip():
                raise ValueError("evidence id must be non-blank.")
            if eid in seen:
                raise ValueError(f"duplicate evidence id {eid!r}.")
            seen.add(eid)
        return value


class Trajectory(BaseModel):
    """Full INPUT→...→FINAL ledger for one investigation.

    Immutable, JSON-serializable fixture. ``steps`` is ordered and always
    starts with INPUT and ends with FINAL. ``correlation_id`` is propagated
    uniformly across every step for observability reconstruction.
    """

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    trajectory_id: str = Field(min_length=1, max_length=128)
    correlation_id: str = Field(min_length=1, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=128)
    exception_id: str = Field(min_length=1, max_length=128)
    mode: TrajectoryMode
    created_at: datetime
    steps: tuple[TrajectoryStep, ...]
    final_status: str = Field(min_length=1, max_length=64)
    provider_journal: tuple[dict[str, Any], ...] = Field(default_factory=tuple)
    tenant_safe: bool = True

    @field_validator("trajectory_id", "correlation_id", "tenant_id", "exception_id")
    @classmethod
    def _check_ids(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("id must be non-blank.")
        return value

    @field_validator("created_at")
    @classmethod
    def _check_created(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be tz-aware.")
        return value

    @field_validator("steps")
    @classmethod
    def _check_steps(
        cls, value: tuple[TrajectoryStep, ...]
    ) -> tuple[TrajectoryStep, ...]:
        if len(value) == 0:
            raise ValueError("steps must be non-empty.")
        if value[0].kind != "INPUT":
            raise ValueError("first step must be INPUT.")
        if value[-1].kind != "FINAL":
            raise ValueError("last step must be FINAL.")
        return value

    def to_fixture(self) -> dict[str, Any]:
        """Return JSON-serializable fixture dict (no secrets)."""
        return self.model_dump(mode="json")

    @classmethod
    def from_fixture(cls, data: dict[str, Any]) -> Trajectory:
        """Hydrate from a JSON fixture dict (lax: datetimes/lists coerced).

        Construction stays strict elsewhere; fixtures are JSON text where
        datetimes serialize to strings and tuples to lists, so hydration
        explicitly opts into lax coercion for those wire types only.
        """
        return cls.model_validate(data, strict=False)


class TenantSafeId(StrEnum):
    """Published tenant-safe id kinds (audit allowlist)."""

    CORRELATION = "correlation_id"
    TENANT = "tenant_id"
    EXCEPTION = "exception_id"
    TRAJECTORY = "trajectory_id"


def generate_correlation_id(exception_id: str | None = None) -> str:
    """Generate a tenant-safe correlation_id (no PII).

    Uses ``exception_id`` prefix when provided, otherwise random suffix.
    Always matches ``_CORRELATION_RE``.
    """
    suffix = uuid.uuid4().hex[:8]
    if exception_id and _CORRELATION_RE.match(exception_id):
        # keep tenant-safe prefix, truncate to fit 128
        prefix = exception_id[:100]
        return f"{prefix}-{suffix}"
    if exception_id:
        safe = re.sub(r"[^A-Za-z0-9._\-]", "-", exception_id)[:100].strip("-_")
        safe = safe or "corr"
        return f"{safe}-{suffix}"
    return f"corr-{suffix}"


def now_utc() -> datetime:
    """Return tz-aware UTC now."""
    return datetime.now(UTC)
