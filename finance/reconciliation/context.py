"""Deterministic reconciliation context models for CP1-A.

This module defines the immutable Pydantic contracts that describe a
reconciliation run's prepared context: per-exception packets
(:class:`ExceptionContext`) and the aggregate run packet
(:class:`ReconciliationRunContext`). These are pure data shapes used to
hand deterministic reconciliation output to downstream investigation
agents without letting the LLM mutate financial outcomes.

Only the Python standard library and ``pydantic`` are used. Money fields
are stored as strings (Decimal-safe) so precision is preserved across
serialization; callers must serialize ``Decimal`` values via ``str()``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RuleStatus(StrEnum):
    """Outcome of a deterministic reconciliation rule check."""

    PASS = "PASS"
    FAIL = "FAIL"
    WARNING = "WARNING"
    BLOCKED = "BLOCKED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class RuleResult(BaseModel):
    """Result of evaluating a single deterministic reconciliation rule."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: str = Field(min_length=1)
    status: RuleStatus
    severity: str = "MEDIUM"
    message: str = ""
    expected: str | None = None
    actual: str | None = None
    difference: str | None = None
    currency: str | None = None
    evidence_refs: list[str] = []


class SourceSummary(BaseModel):
    """Summary of one ingested source (invoice/stripe/bank)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_type: str
    status: str = "validated"
    rows: int = Field(ge=0)
    invalid_rows: int = Field(ge=0)
    content_digest: str | None = None


class ExceptionContext(BaseModel):
    """Per-exception packet handed to investigation agents."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    exception_id: str
    exception_code: str
    severity: str
    title: str
    description: str
    currency: str
    expected_net: str
    actual_deposit: str
    variance: str
    tolerance: str
    calculations: dict[str, str]
    evidence_refs: list[str]
    evidence: list[dict[str, Any]]
    match_summary: str = ""
    allocation_summary: str = ""
    rule_results: list[RuleResult] = []
    investigation_eligible: bool
    ineligibility_reason: str | None = None


class ReconciliationRunContext(BaseModel):
    """Aggregate context for a reconciliation run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = "1.0"
    run_id: str
    snapshot_id: str
    engine_version: str
    rule_version: str = "1.0"
    status: str
    sources: dict[str, SourceSummary]
    validation_summary: dict[str, int]
    exception_ids: list[str]
    exceptions: list[ExceptionContext] = []
    fingerprint: str


def context_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Return the JSON schema for a Pydantic model.

    Args:
        model: A Pydantic ``BaseModel`` subclass.

    Returns:
        The model's JSON schema as a dictionary.
    """
    return model.model_json_schema()


RECONCILIATION_RUN_CONTEXT_SCHEMA: dict[str, Any] = ReconciliationRunContext.model_json_schema()
EXCEPTION_CONTEXT_SCHEMA: dict[str, Any] = ExceptionContext.model_json_schema()
