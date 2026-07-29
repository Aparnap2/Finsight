"""Structured per-job telemetry recording.

Phase 1 writes structured JSON log lines and buffers them in memory for
test assertions. Production deployments will forward these to a log
aggregator (e.g., Loki, DataDog).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from python_runtime.models import Job

logger = logging.getLogger(__name__)

# Module-level in-memory buffer for telemetry records (testing/retrieval)
_TELEMETRY_LOG_RECORD: list[dict[str, Any]] = []


class TelemetryStore:
    """Phase 1: structured JSON log lines + in-memory buffer.

    Usage:
        store = TelemetryStore()
        store.record(job)
        records = store.get_records()
    """

    def record(self, job: Job) -> None:
        """Record telemetry for a completed job.

        Writes a structured JSON log line and appends to the in-memory buffer.

        Args:
            job: Completed job with optional telemetry and error data.
        """
        entry = self._build_entry(job)
        logger.info("JOB_TELEMETRY %s", json.dumps(entry))
        _TELEMETRY_LOG_RECORD.append(entry)

    @staticmethod
    def _build_entry(job: Job) -> dict[str, Any]:
        """Build a structured telemetry entry from a job."""
        telemetry = job.telemetry
        return {
            "event": "job.completed",
            "job_id": str(job.id),
            "tenant_id": job.tenant_id,
            "pipeline": job.pipeline,
            "status": job.status.value,
            "duration_ms": telemetry.duration_ms if telemetry else None,
            "cache_hit": telemetry.cache_hit if telemetry else False,
            "input_rows": telemetry.input_rows if telemetry else 0,
            "output_rows": telemetry.output_rows if telemetry else 0,
            "error_code": job.error.code if job.error else None,
            "pipeline_version": telemetry.pipeline_version if telemetry else None,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        }

    def get_records(self) -> list[dict[str, Any]]:
        """Return all telemetry records.

        Returns a shallow copy to protect the internal buffer.

        Returns:
            List of telemetry entry dicts.
        """
        return list(_TELEMETRY_LOG_RECORD)

    def clear(self) -> None:
        """Clear all telemetry records from the in-memory buffer."""
        _TELEMETRY_LOG_RECORD.clear()
