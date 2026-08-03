"""Tests for python_runtime.telemetry — TelemetryStore."""

from python_runtime.models import ComputeError, Job, JobTelemetry
from python_runtime.telemetry import TelemetryStore


class TestTelemetryStore:
    """Structured per-job telemetry recording."""

    def setup_method(self) -> None:
        self.store = TelemetryStore()
        self.store.clear()

    def test_record_creates_entry(self) -> None:
        job = Job(tenant_id="CF001", pipeline="analytics")
        job.telemetry = JobTelemetry(duration_ms=500, input_rows=100, output_rows=50)
        self.store.record(job)
        records = self.store.get_records()
        assert len(records) == 1

    def test_record_includes_all_fields(self) -> None:
        job = Job(tenant_id="CF001", pipeline="analytics")
        job.telemetry = JobTelemetry(duration_ms=500, input_rows=100, output_rows=50)
        self.store.record(job)
        entry = self.store.get_records()[0]
        assert entry["event"] == "job.completed"
        assert entry["job_id"] == str(job.id)
        assert entry["tenant_id"] == "CF001"
        assert entry["pipeline"] == "analytics"
        assert entry["status"] == "queued"
        assert entry["duration_ms"] == 500
        assert entry["input_rows"] == 100
        assert entry["output_rows"] == 50
        assert entry["cache_hit"] is False
        assert entry["error_code"] is None

    def test_records_multiple_jobs(self) -> None:
        store = TelemetryStore()
        store.clear()
        j1 = Job(tenant_id="T1", pipeline="p1")
        j1.telemetry = JobTelemetry()
        j2 = Job(tenant_id="T2", pipeline="p2")
        j2.telemetry = JobTelemetry()
        store.record(j1)
        store.record(j2)
        assert len(store.get_records()) == 2

    def test_error_code_extraction(self) -> None:
        job = Job(
            tenant_id="T1",
            pipeline="test",
            error=ComputeError(code="VALIDATION_ERROR", message="Bad data"),
        )
        job.telemetry = JobTelemetry()
        self.store.record(job)
        entry = self.store.get_records()[0]
        assert entry["error_code"] == "VALIDATION_ERROR"
        # error details are NOT in telemetry (only code)
        assert "error_message" not in entry

    def test_no_telemetry_graceful(self) -> None:
        """record() works even if job.telemetry is None."""
        job = Job(tenant_id="T1", pipeline="test")
        self.store.record(job)
        entry = self.store.get_records()[0]
        assert entry["duration_ms"] is None
        assert entry["cache_hit"] is False
        assert entry["pipeline_version"] is None

    def test_get_records_returns_copy(self) -> None:
        self.store.record(Job(tenant_id="T1", pipeline="test", telemetry=JobTelemetry()))
        records = self.store.get_records()
        records.clear()
        assert len(self.store.get_records()) == 1  # original unchanged

    def test_clear_empties_records(self) -> None:
        self.store.record(Job(tenant_id="T1", pipeline="test", telemetry=JobTelemetry()))
        self.store.clear()
        assert len(self.store.get_records()) == 0

    def test_timestamps_isoformat(self) -> None:
        job = Job(tenant_id="T1", pipeline="test")
        job.telemetry = JobTelemetry()
        self.store.record(job)
        entry = self.store.get_records()[0]
        assert entry["created_at"] is not None
        assert "T" in entry["created_at"]  # ISO format contains T
        assert entry["started_at"] is None
        assert entry["completed_at"] is None
