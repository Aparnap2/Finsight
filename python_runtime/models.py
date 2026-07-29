"""Central data models for all compute jobs.

Provides Job, JobStatus, ComputeError, and JobTelemetry — the core types
that flow through the compute runtime lifecycle.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class JobStatus(StrEnum):
    """Lifecycle status of a compute job."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ComputeError(Exception):
    """Structured error — never a raw traceback.

    This is an Exception subclass so it can be raised and caught by
    ``raise`` / ``except`` / ``pytest.raises`` throughout the runtime.
    It is NOT a Pydantic model — the ``Job`` model uses
    ``arbitrary_types_allowed`` to store it.

    Attributes:
        code: Machine-readable error code (e.g. "IMPORT_ERROR", "VALIDATION_ERROR").
        message: Human-readable summary of the error.
        details: Optional structured context (paths, values, etc.).
    """

    def __init__(
        self,
        code: str = "",
        message: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialise the structured error.

        Args:
            code: Machine-readable error code.
            message: Human-readable summary.
            details: Optional structured context.
        """
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)

    def model_dump(self) -> dict[str, Any]:
        """Return a dict representation (compatible with Pydantic ``model_dump``).

        Returns:
            Dict with ``code``, ``message``, and ``details`` keys.
        """
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


class JobTelemetry(BaseModel):  # type: ignore[misc]
    """Captured at job completion for observability and billing."""

    duration_ms: int = 0
    peak_memory_mb: float = 0.0
    input_rows: int = 0
    output_rows: int = 0
    cache_hit: bool = False
    pipeline_version: str = "1.0"
    stages: dict[str, int] = Field(default_factory=dict)


class Job(BaseModel):  # type: ignore[misc]
    """A single compute job with full lifecycle tracking.

    Attributes:
        id: Unique job identifier (UUID v4).
        status: Current lifecycle status.
        created_at: Timestamp of job creation.
        started_at: Timestamp when execution began.
        completed_at: Timestamp when execution finished.
        tenant_id: Tenant owning this job.
        pipeline: Pipeline variant to execute.
        params: Runtime parameters for the pipeline.
        dataset_ref: Reference to stored input dataset.
        result_ref: Reference to stored output artifact.
        error: Structured error if job failed.
        telemetry: Performance telemetry at completion.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: UUID = Field(default_factory=uuid4)
    status: JobStatus = JobStatus.QUEUED
    created_at: datetime = Field(default_factory=datetime.now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    tenant_id: str
    pipeline: str
    params: dict[str, Any] = Field(default_factory=dict)
    dataset_ref: str | None = None
    result_ref: str | None = None
    error: ComputeError | None = None
    telemetry: JobTelemetry | None = None
