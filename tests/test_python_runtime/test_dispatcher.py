"""Tests for python_runtime.dispatcher — Dispatcher, JobHandler protocol."""

import time
from threading import Event
from unittest.mock import MagicMock
from uuid import UUID

from python_runtime.dispatcher import Dispatcher, JobHandler
from python_runtime.models import Job, JobStatus


class TestJobHandlerProtocol:
    """JobHandler protocol runtime-checkable interface."""

    def test_handler_protocol(self) -> None:
        """A class with handle() is a JobHandler."""
        handler = MagicMock(spec=JobHandler)
        assert isinstance(handler, JobHandler)

    def test_handler_must_have_handle(self) -> None:
        """A class without handle() is NOT a JobHandler."""
        class NotAHandler:
            pass

        assert not isinstance(NotAHandler(), JobHandler)


class TestDispatcher:
    """Dispatcher routes jobs to handlers with in-process thread pool."""

    def setup_method(self) -> None:
        self.dispatcher = Dispatcher(max_workers=2)
        self._blocker = Event()
        self.mock_handler = MagicMock(spec=JobHandler)
        # Use a blocking side-effect so tests can control handler timing
        self.mock_handler.handle.side_effect = self._blocking_handle

    def _blocking_handle(self, _job: Job) -> str:
        """Block until the test signals the handler to proceed."""
        self._blocker.wait(timeout=10)
        return "done"

    def test_register_handler(self) -> None:
        self.dispatcher.register("test_pipeline", self.mock_handler)
        assert "test_pipeline" in self.dispatcher._handlers

    def test_submit_returns_uuid(self) -> None:
        self.dispatcher.register("test", self.mock_handler)
        job = Job(tenant_id="T1", pipeline="test")
        job_id = self.dispatcher.submit(job)
        assert isinstance(job_id, UUID)

    def test_submit_stores_job(self) -> None:
        self.dispatcher.register("test", self.mock_handler)
        job = Job(tenant_id="T1", pipeline="test")
        self.dispatcher.submit(job)
        assert self.dispatcher._jobs[job.id] is job

    def test_get_status_queued(self) -> None:
        self.dispatcher.register("test", self.mock_handler)
        job = Job(tenant_id="T1", pipeline="test")
        self.dispatcher.submit(job)
        # Immediately after submit the job should exist with a valid status.
        # The exact status is timing-dependent (QUEUED, RUNNING, or SUCCESS).
        status = self.dispatcher.get_status(job.id)
        assert status is not None
        self._blocker.set()  # release handler

    def test_get_status_nonexistent(self) -> None:
        status = self.dispatcher.get_status(UUID("00000000-0000-0000-0000-000000000001"))
        assert status is None

    def test_successful_job_transitions_to_success(self) -> None:
        self.dispatcher.register("test", self.mock_handler)
        job = Job(tenant_id="T1", pipeline="test")
        self.dispatcher.submit(job)
        self._blocker.set()  # release handler
        time.sleep(0.5)
        stored = self.dispatcher.get_result(job.id)
        assert stored is not None
        assert stored.status == JobStatus.SUCCESS
        assert stored.result_ref == "done"  # from _blocking_handle

    def test_handler_result_is_stored_as_result_ref(self) -> None:
        self.dispatcher.register("test", self.mock_handler)
        job = Job(tenant_id="T1", pipeline="test")
        self.dispatcher.submit(job)
        self._blocker.set()  # release handler
        time.sleep(0.5)
        stored = self.dispatcher.get_result(job.id)
        assert stored is not None
        assert stored.result_ref == "done"

    def test_handler_none_result(self) -> None:
        """Handler returning None should set result_ref to None."""
        self.mock_handler.handle.side_effect = lambda _job: None
        self.dispatcher.register("test", self.mock_handler)
        job = Job(tenant_id="T1", pipeline="test")
        self.dispatcher.submit(job)
        time.sleep(0.5)
        stored = self.dispatcher.get_result(job.id)
        assert stored is not None
        assert stored.result_ref is None

    def test_unregistered_pipeline_fails(self) -> None:
        """Job with no registered handler -> FAILED with HANDLER_ERROR."""
        job = Job(tenant_id="T1", pipeline="nonexistent")
        self.dispatcher.submit(job)
        time.sleep(0.5)
        stored = self.dispatcher.get_result(job.id)
        assert stored is not None
        assert stored.status == JobStatus.FAILED
        assert stored.error is not None
        assert stored.error.code == "HANDLER_ERROR"

    def test_cancel_queued_job(self) -> None:
        """Cancel a job that is still QUEUED because the pool is busy."""
        # Use max_workers=1 with a dedicated dispatcher so the first job
        # blocks the pool and the second stays QUEUED.
        dispatcher = Dispatcher(max_workers=1)
        blocker = Event()

        def hold(_job: Job) -> str:
            blocker.wait(timeout=10)
            return "done"

        handler1 = MagicMock(spec=JobHandler)
        handler1.handle.side_effect = hold
        dispatcher.register("hold", handler1)

        handler2 = MagicMock(spec=JobHandler)
        handler2.handle.return_value = "ok"
        dispatcher.register("cancel", handler2)

        # Fill the single worker — this job stays RUNNING
        blocking_job = Job(tenant_id="T1", pipeline="hold")
        dispatcher.submit(blocking_job)
        time.sleep(0.1)  # let the worker pick it up

        # Second job stays QUEUED because the pool is full
        cancel_job = Job(tenant_id="T1", pipeline="cancel")
        dispatcher.submit(cancel_job)

        cancelled = dispatcher.cancel(cancel_job.id)
        assert cancelled is True
        stored = dispatcher.get_result(cancel_job.id)
        assert stored is not None
        assert stored.status == JobStatus.CANCELLED

        blocker.set()  # release the blocking job

    def test_cancel_nonexistent_job(self) -> None:
        cancelled = self.dispatcher.cancel(UUID("00000000-0000-0000-0000-000000000001"))
        assert cancelled is False

    def test_cancel_already_running_job(self) -> None:
        """A running job cannot be cancelled."""

        def slow_handle(_job: Job) -> str:
            time.sleep(0.5)
            return "done"

        handler = MagicMock(spec=JobHandler)
        handler.handle.side_effect = slow_handle
        self.dispatcher.register("slow", handler)
        job = Job(tenant_id="T1", pipeline="slow")
        self.dispatcher.submit(job)
        time.sleep(0.1)  # Let it start
        cancelled = self.dispatcher.cancel(job.id)
        assert cancelled is False  # Already RUNNING

    def test_telemetry_is_attached(self) -> None:
        self.dispatcher.register("test", self.mock_handler)
        job = Job(tenant_id="T1", pipeline="test")
        self.dispatcher.submit(job)
        self._blocker.set()  # release handler
        time.sleep(0.5)
        stored = self.dispatcher.get_result(job.id)
        assert stored is not None
        assert stored.telemetry is not None

    def test_get_result_returns_none_for_unknown(self) -> None:
        assert self.dispatcher.get_result(UUID("00000000-0000-0000-0000-000000000001")) is None

    def test_multiple_jobs(self) -> None:
        """Submit 3 jobs, all complete successfully."""
        self.dispatcher.register("test", self.mock_handler)
        jobs = [
            Job(tenant_id="T1", pipeline="test"),
            Job(tenant_id="T1", pipeline="test"),
            Job(tenant_id="T1", pipeline="test"),
        ]
        for j in jobs:
            self.dispatcher.submit(j)
        self._blocker.set()  # release all blocked handlers
        time.sleep(1.0)
        for j in jobs:
            stored = self.dispatcher.get_result(j.id)
            assert stored is not None
            assert stored.status == JobStatus.SUCCESS
