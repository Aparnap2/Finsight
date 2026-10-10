"""Slice 4 Gate 1: database-outage degradation at the API boundary.

Qualification (fails until proven): when storage is unavailable, the
API must degrade deterministically — liveness stays 200, readiness
goes 503, observation health reports ok:false with 200, and metrics
goes 503. No 500s, no hangs, no partial payloads.

No live server, no real DB: the session dependency raises on use.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient


def _build_app() -> FastAPI:
    """Observation + readiness surface with a dead storage backend."""
    from apps.api.observability import create_readiness_router
    from apps.api.observations import get_observation_session, get_runs_dir, router

    app = FastAPI()
    app.include_router(create_readiness_router(probe=lambda: False))
    app.include_router(router)

    @app.middleware("http")
    async def _actor(request: Request, call_next: Any) -> Any:
        request.state.actor = {"tenant_id": "tenant-a", "user_id": "tester"}
        return await call_next(request)

    def _dead_session() -> Iterator[Any]:
        # Faithful to production: Session creation is lazy; the failure
        # surfaces at first use inside the handler's guarded block.
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session as OrmSession

        dead = create_engine("postgresql+psycopg://finsight:finsight@localhost:5499/finsight")
        with OrmSession(dead) as session:
            yield session

    app.dependency_overrides[get_observation_session] = _dead_session
    app.dependency_overrides[get_runs_dir] = lambda: Path("/nonexistent")
    return app


class TestDatabaseOutageDegradation:
    def test_live_stays_200(self) -> None:
        assert TestClient(_build_app()).get("/live").status_code == 200

    def test_ready_goes_503(self) -> None:
        response = TestClient(_build_app()).get("/ready")
        assert response.status_code == 503
        assert response.json() == {"status": "not_ready"}

    def test_observation_health_reports_not_ok(self) -> None:
        response = TestClient(_build_app()).get("/api/v1/observations/health")
        assert response.status_code == 200
        body = response.json()
        assert body["db"]["ok"] is False
        assert "counts" not in body

    def test_observation_metrics_goes_503(self) -> None:
        response = TestClient(_build_app()).get("/api/v1/observations/metrics")
        assert response.status_code == 503

    def test_executions_list_goes_503(self) -> None:
        response = TestClient(_build_app()).get("/api/v1/observations/executions")
        assert response.status_code == 503
