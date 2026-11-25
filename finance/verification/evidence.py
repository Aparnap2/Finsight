"""Canonical E2E verification report schema (CP6).

Defines the machine-readable evidence report produced by CI/staging E2E runs.
The verifier and the NiceGUI viewer both consume this schema. The viewer is
read-only: it never calculates or modifies a verdict.

Money fields are strings (Decimal-safe). Missing evidence is represented as
null, never as a passing value.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RunVerdict(StrEnum):
    """Overall run verdict."""

    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    INCOMPLETE = "INCOMPLETE"


class StageStatus(StrEnum):
    """Status of one workflow stage."""

    PASSED = "PASSED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    NOT_RUN = "NOT_RUN"


class StageEvidence(BaseModel):
    """Evidence for one workflow stage."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: str
    status: StageStatus
    detail: str = ""
    ids: dict[str, str] = Field(default_factory=dict)


class ScenarioResult(BaseModel):
    """Result for one golden scenario."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scenario_id: str
    verdict: RunVerdict
    expected: dict[str, Any] = Field(default_factory=dict)
    actual: dict[str, Any] = Field(default_factory=dict)
    mismatches: list[str] = Field(default_factory=list)
    run_id: str | None = None
    exception_ids: list[str] = Field(default_factory=list)
    investigation_id: str | None = None
    export_id: str | None = None
    trace_id: str | None = None
    provider_request_id: str | None = None
    provider_model: str | None = None


class ProviderEvidence(BaseModel):
    """Sanitized provider call evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_name: str | None = None
    model: str | None = None
    request_id: str | None = None
    latency_ms: float | None = None
    success: bool = False


class TraceEvidence(BaseModel):
    """Trace export evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trace_id: str | None = None
    exported: bool = False
    backend: str | None = None


class E2ERunReport(BaseModel):
    """Canonical E2E run evidence report."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = "1.0"
    run_id: str
    commit_sha: str
    image_digest: str | None = None
    migration_revision: str | None = None
    environment: str = "ci"
    timestamp: str
    overall_verdict: RunVerdict
    stages: list[StageEvidence] = Field(default_factory=list)
    scenarios: list[ScenarioResult] = Field(default_factory=list)
    provider: ProviderEvidence | None = None
    trace: TraceEvidence | None = None
    financial_invariants: dict[str, bool] = Field(default_factory=dict)
    notes: str = ""
