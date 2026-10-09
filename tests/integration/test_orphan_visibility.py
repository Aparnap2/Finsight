"""Slice 4 Gate 2: orphan visibility through the observation interface.

Qualification:

- An interrupted execution (``result`` NULL) is visible to its tenant
  as in-progress: listed with null result, bucketed ``IN_PROGRESS`` in
  metrics. Operators can distinguish recoverable work from terminal
  failures.
- Legacy ``tenant_id=''`` orphan rows (Slice 2 known migration state)
  are NEVER tenant-visible: excluded from the execution list, the
  metrics buckets, and the audit/timeline lookups (which resolve
  tenant-scoped and 404 otherwise).

No live server, no real DB: seeded SQLite engine + overrides.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from finance.accounting.mock import MockQuickBooksAdapter
from finance.execution.models import ExecutionRow
from tests.unit.execution.test_execution_boundary import _Seed
from tests.unit.execution.test_executor import _engine, _make_executor

TENANT_A = "tenant-a"


def _seed() -> Any:
    """One closed execution, one interrupted (NULL result), one legacy orphan."""
    engine = _engine()
    seed = _Seed(engine, exc_id="exc-orphan-a", tenant_id=TENANT_A)
    result = _make_executor(MockQuickBooksAdapter(), engine).run(
        seed.approved, seed.proposal, seed.approval, "orphan-key-closed"
    )
    assert str(result.result) == "SUCCEEDED"
    with Session(engine) as session:
        session.add(
            ExecutionRow(
                tenant_id=TENANT_A,
                idempotency_key="orphan-key-open",
                execution_id="exec-open",
                exception_id="exc-orphan-a",
                proposal_id="prop-open",
                payload_hash="h",
                result=None,
            )
        )
        session.add(
            ExecutionRow(
                tenant_id="",
                idempotency_key="legacy-key-x",
                execution_id="exec-legacy",
                exception_id="exc-legacy",
                proposal_id="prop-legacy",
                payload_hash="h",
                result="SUCCEEDED",
            )
        )
        session.commit()
    return engine


def _build_app(engine: Any, runs_dir: Path) -> FastAPI:
    """Observations router with fixed actor + overrides."""
    from apps.api.observations import get_observation_session, get_runs_dir, router

    app = FastAPI()
    app.include_router(router)

    @app.middleware("http")
    async def _actor(request: Request, call_next: Any) -> Any:
        request.state.actor = {"tenant_id": TENANT_A, "user_id": "tester"}
        return await call_next(request)

    def _session_override() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_observation_session] = _session_override
    app.dependency_overrides[get_runs_dir] = lambda: runs_dir
    return app


class TestOrphanVisibility:
    def test_interrupted_execution_listed_with_null_result(self, tmp_path: Path) -> None:
        client = TestClient(_build_app(_seed(), tmp_path))
        rows = client.get("/api/v1/observations/executions").json()["executions"]
        open_rows = [r for r in rows if r["idempotency_key"] == "orphan-key-open"]
        assert len(open_rows) == 1
        assert open_rows[0]["result"] is None

    def test_metrics_buckets_interrupted_as_in_progress(self, tmp_path: Path) -> None:
        client = TestClient(_build_app(_seed(), tmp_path))
        buckets = client.get("/api/v1/observations/metrics").json()["executions_by_result"]
        assert buckets.get("IN_PROGRESS") == 1
        assert buckets.get("SUCCEEDED") == 1

    def test_legacy_orphan_excluded_from_list(self, tmp_path: Path) -> None:
        client = TestClient(_build_app(_seed(), tmp_path))
        rows = client.get("/api/v1/observations/executions").json()["executions"]
        assert all(r["tenant_id"] != "" for r in rows)
        assert "legacy-key-x" not in {r["idempotency_key"] for r in rows}

    def test_legacy_orphan_excluded_from_metrics(self, tmp_path: Path) -> None:
        client = TestClient(_build_app(_seed(), tmp_path))
        buckets = client.get("/api/v1/observations/metrics").json()["executions_by_result"]
        assert buckets.get("SUCCEEDED") == 1  # orphan must not inflate the count

    def test_legacy_orphan_detail_is_404(self, tmp_path: Path) -> None:
        client = TestClient(_build_app(_seed(), tmp_path))
        assert client.get("/api/v1/observations/executions/exec-legacy").status_code == 404
