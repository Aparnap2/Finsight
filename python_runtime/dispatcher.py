"""Job dispatcher — routes jobs to handlers with in-process thread pool.

Phase 1 uses ThreadPoolExecutor for concurrent job execution. Phase 2 will
add Redis-backed distributed queues.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from python_runtime.models import ComputeError, Job, JobStatus, JobTelemetry

logger = logging.getLogger(__name__)


@runtime_checkable
class JobHandler(Protocol):
    """Protocol for pipeline handlers. Each handler implements one pipeline variant.

    Handlers are synchronous — the Dispatcher's thread pool manages concurrency.
    """

    def handle(self, job: Job) -> Any:
        """Execute the pipeline logic for a job.

        Args:
            job: The job to execute.

        Returns:
            Result that will be stored as the job's result_ref.
        """
        ...


class Dispatcher:
    """Routes jobs to handlers. Phase 1: in-process ThreadPoolExecutor.

    Owns the job state machine: QUEUED -> RUNNING -> SUCCESS | FAILED.
    Telemetry is attached to each job on completion.
    """

    def __init__(self, max_workers: int = 4):
        """Initialize the dispatcher.

        Args:
            max_workers: Maximum concurrent handler threads.
        """
        self._handlers: dict[str, JobHandler] = {}
        self._jobs: dict[UUID, Job] = {}
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

    def register(self, pipeline: str, handler: JobHandler) -> None:
        """Register a handler for a pipeline name.

        Args:
            pipeline: Pipeline identifier string.
            handler: Handler instance implementing JobHandler protocol.
        """
        self._handlers[pipeline] = handler

    def submit(self, job: Job) -> UUID:
        """Submit a job for execution.

        The job is enqueued in the thread pool and returns immediately.
        The caller polls get_status/get_result for completion.

        Args:
            job: Job to execute.

        Returns:
            The job's UUID for status polling.
        """
        self._jobs[job.id] = job
        self._executor.submit(self._run_job, job)
        return job.id

    def get_status(self, job_id: UUID) -> JobStatus | None:
        """Return the current status of a job, or None if not found.

        Args:
            job_id: UUID of the job.

        Returns:
            Current JobStatus or None.
        """
        job = self._jobs.get(job_id)
        return job.status if job else None

    def get_result(self, job_id: UUID) -> Job | None:
        """Return the full job object, or None if not found.

        Args:
            job_id: UUID of the job.

        Returns:
            Job instance or None.
        """
        return self._jobs.get(job_id)

    def cancel(self, job_id: UUID) -> bool:
        """Cancel a queued job. Jobs already running cannot be cancelled.

        Args:
            job_id: UUID of the job to cancel.

        Returns:
            True if the job was cancelled, False if not found or already running.
        """
        job = self._jobs.get(job_id)
        if job and job.status == JobStatus.QUEUED:
            job.status = JobStatus.CANCELLED
            return True
        return False

    def _run_job(self, job: Job) -> None:
        """Execute a job within the thread pool.

        Sets RUNNING status, invokes the handler, captures result or error,
        and attaches telemetry.

        Args:
            job: Job to execute.
        """
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now()
        job.telemetry = JobTelemetry()
        start = time.monotonic()

        try:
            handler = self._handlers.get(job.pipeline)
            if handler is None:
                raise ValueError(f"No handler registered for pipeline: {job.pipeline}")

            result = handler.handle(job)
            job.status = JobStatus.SUCCESS
            job.result_ref = str(result) if result is not None else None
        except Exception as exc:
            job.status = JobStatus.FAILED
            job.error = ComputeError(
                code="HANDLER_ERROR",
                message=str(exc),
                details={"pipeline": job.pipeline},
            )
            logger.exception("Job %s failed with %s", job.id, type(exc).__name__)
        finally:
            job.completed_at = datetime.now()
            elapsed_ms = int((time.monotonic() - start) * 1000)
            if job.telemetry:
                job.telemetry.duration_ms = elapsed_ms
