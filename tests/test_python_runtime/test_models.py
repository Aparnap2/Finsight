"""Tests for python_runtime.models — Job, JobStatus, ComputeError, JobTelemetry."""

from datetime import datetime
from uuid import UUID

from python_runtime.models import ComputeError, Job, JobStatus, JobTelemetry


class TestJobStatus:
    """JobStatus enum values and properties."""

    def test_enum_values(self) -> None:
        assert JobStatus.QUEUED.value == "queued"
        assert JobStatus.RUNNING.value == "running"
        assert JobStatus.SUCCESS.value == "success"
        assert JobStatus.FAILED.value == "failed"
        assert JobStatus.CANCELLED.value == "cancelled"

    def test_enum_membership(self) -> None:
        assert "queued" in set(item.value for item in JobStatus)

    def test_str_serialization(self) -> None:
        """StrEnum can be serialized with .value for JSON."""
        assert JobStatus.QUEUED.value == "queued"


class TestComputeError:
    """ComputeError structured error model."""

    def test_minimal_construction(self) -> None:
        err = ComputeError(code="TEST_ERROR", message="Something broke")
        assert err.code == "TEST_ERROR"
        assert err.message == "Something broke"
        assert err.details is None

    def test_with_details(self) -> None:
        err = ComputeError(
            code="IMPORT_ERROR",
            message="File not found",
            details={"path": "/data/file.csv", "error": "No such file"},
        )
        assert err.details is not None
        assert err.details["path"] == "/data/file.csv"

    def test_serialization(self) -> None:
        err = ComputeError(code="ERR", message="msg", details={"key": "val"})
        d = err.model_dump()
        assert d["code"] == "ERR"
        assert d["message"] == "msg"
        assert d["details"] == {"key": "val"}

    def test_default_details_is_none(self) -> None:
        err = ComputeError(code="ERR", message="msg")
        assert err.model_dump()["details"] is None


class TestJobTelemetry:
    """JobTelemetry default values and construction."""

    def test_defaults(self) -> None:
        t = JobTelemetry()
        assert t.duration_ms == 0
        assert t.peak_memory_mb == 0.0
        assert t.input_rows == 0
        assert t.output_rows == 0
        assert t.cache_hit is False
        assert t.pipeline_version == "1.0"
        assert t.stages == {}

    def test_custom_values(self) -> None:
        t = JobTelemetry(
            duration_ms=1500,
            input_rows=100,
            output_rows=50,
            cache_hit=True,
            pipeline_version="2.0",
            stages={"import": 200, "validate": 300, "query": 1000},
        )
        assert t.duration_ms == 1500
        assert t.input_rows == 100
        assert t.cache_hit is True
        assert t.pipeline_version == "2.0"
        assert t.stages["query"] == 1000

    def test_serialization(self) -> None:
        t = JobTelemetry(duration_ms=500)
        d = t.model_dump()
        assert d["duration_ms"] == 500
        assert d["cache_hit"] is False


class TestJob:
    """Job model lifecycle and construction."""

    def test_default_construction(self) -> None:
        job = Job(tenant_id="CF001", pipeline="analytics")
        assert isinstance(job.id, UUID)
        assert job.status == JobStatus.QUEUED
        assert job.tenant_id == "CF001"
        assert job.pipeline == "analytics"
        assert job.params == {}
        assert job.dataset_ref is None
        assert job.result_ref is None
        assert job.error is None
        assert job.telemetry is None
        assert isinstance(job.created_at, datetime)

    def test_custom_id(self) -> None:
        uid = UUID("00000000-0000-0000-0000-000000000001")
        job = Job(id=uid, tenant_id="T1", pipeline="test")
        assert job.id == uid

    def test_status_transition(self) -> None:
        job = Job(tenant_id="T1", pipeline="test")
        assert job.status == JobStatus.QUEUED
        job.status = JobStatus.RUNNING
        assert job.status == JobStatus.RUNNING
        job.status = JobStatus.SUCCESS
        assert job.status == JobStatus.SUCCESS

    def test_with_error(self) -> None:
        err = ComputeError(code="ERR", message="fail")
        job = Job(tenant_id="T1", pipeline="test", error=err)
        assert job.error is not None
        assert job.error.code == "ERR"

    def test_with_telemetry(self) -> None:
        tel = JobTelemetry(duration_ms=100)
        job = Job(tenant_id="T1", pipeline="test", telemetry=tel)
        assert job.telemetry is not None
        assert job.telemetry.duration_ms == 100

    def test_serialization_roundtrip(self) -> None:
        job = Job(tenant_id="T1", pipeline="analytics", params={"query": "SELECT 1"})
        d = job.model_dump()
        assert d["tenant_id"] == "T1"
        assert d["pipeline"] == "analytics"
        assert d["params"] == {"query": "SELECT 1"}
        assert d["status"] == JobStatus.QUEUED.value
        assert d["error"] is None
        assert d["telemetry"] is None
        assert "id" in d
        assert "created_at" in d

    def test_params_accepts_various_types(self) -> None:
        job = Job(
            tenant_id="T1",
            pipeline="test",
            params={"int_val": 42, "float_val": 3.14, "str_val": "hello", "list_val": [1, 2, 3]},
        )
        assert job.params["int_val"] == 42
        assert job.params["str_val"] == "hello"
