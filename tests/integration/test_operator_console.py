"""UI-1 operator console contract (RED): logic-free /gui over observation API.

Failing until GREEN (``apps.api.operator_console`` does not exist):

- console pages mount under ``/gui`` and render without tenant headers
  (page chrome only; data calls carry server-side demo headers);
- ``GET /api/v1/observations/health`` without headers stays 401
  (middleware bypasses ``/health`` but the handler denies anonymous);
- eval report rendering caps at 256 KiB with explicit truncation;
- the console adds no non-GET API routes and no new auth semantics.

No live server, no real DB: seeded SQLite engine + dependency overrides,
mirroring ``test_observations_api.py``.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from finance.accounting.mock import MockQuickBooksAdapter
from tests.unit.execution.test_execution_boundary import _Seed
from tests.unit.execution.test_executor import _engine, _make_executor

TENANT_A = "tenant-a"

#: H-4: eval report render cap (bytes).
EVAL_RENDER_CAP_BYTES = 256 * 1024


def _seed() -> Any:
    """One closed execution for the demo tenant, shared engine."""
    engine = _engine()
    seed = _Seed(engine, exc_id="exc-console-a", tenant_id=TENANT_A)
    result = _make_executor(MockQuickBooksAdapter(), engine).run(
        seed.approved, seed.proposal, seed.approval, "console-key-a"
    )
    assert str(result.result) == "SUCCEEDED"
    return engine


def _build_app(engine: Any, runs_dir: Path) -> FastAPI:
    """Full app surface under test: observations router + console pages."""
    from apps.api.observations import get_observation_session, get_runs_dir, router
    from apps.api.operator_console import mount_console

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
    mount_console(app)
    return app


class TestConsoleMount:
    def test_gui_index_renders_without_headers(self, tmp_path: Path) -> None:
        client = TestClient(_build_app(_seed(), tmp_path))
        response = client.get("/gui")
        assert response.status_code == 200

    def test_gui_executions_view_lists_demo_rows(self, tmp_path: Path) -> None:
        client = TestClient(_build_app(_seed(), tmp_path))
        response = client.get("/gui/executions")
        assert response.status_code == 200
        assert TENANT_A in response.text


class TestConsoleAuthBoundary:
    def test_observation_health_without_headers_is_401(self, tmp_path: Path) -> None:
        from apps.api.observations import router

        bare = FastAPI()
        bare.include_router(router)
        client = TestClient(bare)
        assert client.get("/api/v1/observations/health").status_code == 401

    def test_console_adds_no_non_get_api_routes(self, tmp_path: Path) -> None:
        app = _build_app(_seed(), tmp_path)
        api_routes = [
            route
            for route in app.routes
            if getattr(route, "path", "").startswith("/api/")
        ]
        assert api_routes, "observation routes must remain mounted"
        for route in api_routes:
            methods = getattr(route, "methods", set()) or set()
            assert methods <= {"GET"}, f"{route.path} allows {methods}"


class TestEvalRenderCap:
    def test_cap_is_256kib(self) -> None:
        from apps.api import operator_console

        assert operator_console.EVAL_RENDER_CAP_BYTES == EVAL_RENDER_CAP_BYTES

    def test_oversize_report_marks_truncation(self) -> None:
        from apps.api import operator_console

        big = {"model": "m", "summary": {}, "blob": "x" * (EVAL_RENDER_CAP_BYTES + 1)}
        rendered, truncated = operator_console.render_eval_report(big)
        assert truncated is True
        assert "truncated" in rendered.lower()
        assert len(rendered.encode("utf-8")) <= EVAL_RENDER_CAP_BYTES + 1024
