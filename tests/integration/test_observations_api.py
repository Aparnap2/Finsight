"""UI-0 observation contract: read-only, tenant-scoped execution/eval views.

Covers the RED surface for ``apps.api.observations`` (not yet implemented,
so collection fails until GREEN):

- anonymous callers get 401 on every observation endpoint;
- tenants see only their own execution/exception rows;
- foreign or unknown ids return 404 (no existence oracle);
- audit/timeline project stored columns in created order;
- health/metrics are computed reads (db probe + per-tenant counts);
- evaluation runs serve seeded report files; unknown runs 404;
- the OpenAPI schema of the observation router is GET-only.

No live server, no real DB: shared in-memory SQLite engine, seeded via
the frozen executor path. Follows the ``test_api_execute_verify`` app
pattern (fixed actor middleware + dependency overrides).
"""

from __future__ import annotations

import json
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
TENANT_B = "tenant-b"


def _seed() -> tuple[Any, Any, Any]:
    """Two tenants, one closed execution each, shared engine."""
    engine = _engine()
    adapter = MockQuickBooksAdapter()
    seed_a = _Seed(engine, exc_id="exc-obs-a", tenant_id=TENANT_A)
    seed_b = _Seed(engine, exc_id="exc-obs-b", tenant_id=TENANT_B)
    for seed, key in ((seed_a, "obs-key-a"), (seed_b, "obs-key-b")):
        result = _make_executor(adapter, engine).run(
            seed.approved, seed.proposal, seed.approval, key
        )
        assert str(result.result) == "SUCCEEDED"
    return engine, seed_a, seed_b


def _seed_eval_reports(runs_dir: Path) -> str:
    """Write one minimal report file; return its run id."""
    runs_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "model": "qwen-test",
        "provider": "groq",
        "summary": {"total": 2, "passed": 1, "failed": 1},
        "cases": [
            {
                "case_id": "EXT-01",
                "task_type": "extraction",
                "dimension": "extraction_accuracy",
                "output_schema_valid": True,
                "decision_contract_valid": True,
                "quality_score": 1.0,
                "threshold": 1.0,
                "passed": True,
            },
            {
                "case_id": "REF-01",
                "task_type": "refusal",
                "dimension": "refusal_correctness",
                "output_schema_valid": True,
                "decision_contract_valid": True,
                "abstained": True,
                "quality_score": 0.0,
                "threshold": 1.0,
                "passed": False,
            },
        ],
    }
    (runs_dir / "run-001.json").write_text(json.dumps(report))
    return "run-001"


def _build_app(engine: Any, tenant_id: str | None, runs_dir: Path) -> FastAPI:
    """Mount the observations router with fixed actor + overrides."""
    from apps.api.observations import get_observation_session, get_runs_dir, router

    app = FastAPI()
    app.include_router(router)

    @app.middleware("http")
    async def _actor(request: Request, call_next: Any) -> Any:
        if tenant_id is not None:
            request.state.actor = {"tenant_id": tenant_id, "user_id": "tester"}
        return await call_next(request)

    def _session_override() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_observation_session] = _session_override
    app.dependency_overrides[get_runs_dir] = lambda: runs_dir
    return app


class TestAnonymousDenied:
    def test_list_denied_without_actor(self, tmp_path: Path) -> None:
        engine, _, _ = _seed()
        client = TestClient(_build_app(engine, None, tmp_path))
        for path in (
            "/api/v1/observations/executions",
            "/api/v1/observations/executions/x",
            "/api/v1/observations/executions/x/audit",
            "/api/v1/observations/executions/x/timeline",
            "/api/v1/observations/health",
            "/api/v1/observations/metrics",
            "/api/v1/observations/evaluations/runs",
            "/api/v1/observations/evaluations/runs/x",
        ):
            assert client.get(path).status_code == 401, path


class TestTenantIsolation:
    def test_list_scoped_to_actor_tenant(self, tmp_path: Path) -> None:
        engine, seed_a, _ = _seed()
        client = TestClient(_build_app(engine, TENANT_A, tmp_path))
        payload = client.get("/api/v1/observations/executions").json()
        assert payload["tenant_id"] == TENANT_A
        ids = {e["execution_id"] for e in payload["executions"]}
        assert len(ids) == 1
        row = payload["executions"][0]
        assert row["tenant_id"] == TENANT_A
        assert row["result"] == "SUCCEEDED"

    def test_foreign_execution_id_is_404_not_403(self, tmp_path: Path) -> None:
        engine, seed_a, seed_b = _seed()
        client_b = TestClient(_build_app(engine, TENANT_B, tmp_path))
        from finance.execution.executor import execution_id_for

        foreign = execution_id_for(TENANT_A, "obs-key-a")
        assert client_b.get(f"/api/v1/observations/executions/{foreign}").status_code == 404
        assert client_b.get("/api/v1/observations/executions/nope").status_code == 404

    def test_foreign_audit_and_timeline_are_404(self, tmp_path: Path) -> None:
        engine, _, _ = _seed()
        client_b = TestClient(_build_app(engine, TENANT_B, tmp_path))
        from finance.execution.executor import execution_id_for

        foreign = execution_id_for(TENANT_A, "obs-key-a")
        assert client_b.get(f"/api/v1/observations/executions/{foreign}/audit").status_code == 404
        assert (
            client_b.get(f"/api/v1/observations/executions/{foreign}/timeline").status_code == 404
        )


class TestProjections:
    def test_get_returns_row_projection(self, tmp_path: Path) -> None:
        engine, _, _ = _seed()
        client = TestClient(_build_app(engine, TENANT_A, tmp_path))
        from finance.execution.executor import execution_id_for

        own = execution_id_for(TENANT_A, "obs-key-a")
        body = client.get(f"/api/v1/observations/executions/{own}").json()
        assert body["execution_id"] == own
        assert body["tenant_id"] == TENANT_A
        assert body["idempotency_key"] == "obs-key-a"
        assert body["result"] == "SUCCEEDED"
        assert body["post_verify"] == "MATCHED"
        assert body["external_reference"]

    def test_audit_returns_ordered_transitions(self, tmp_path: Path) -> None:
        engine, _, _ = _seed()
        client = TestClient(_build_app(engine, TENANT_A, tmp_path))
        from finance.execution.executor import execution_id_for

        own = execution_id_for(TENANT_A, "obs-key-a")
        trail = client.get(f"/api/v1/observations/executions/{own}/audit").json()
        assert isinstance(trail, list) and len(trail) >= 2
        states = [(a["previous_state"], a["new_state"]) for a in trail]
        assert states[0][0] is None or isinstance(states[0][0], str)
        for entry in trail:
            assert {"timestamp", "actor", "operation", "reason"} <= set(entry)
        assert trail == sorted(trail, key=lambda a: (a["timestamp"],))

    def test_timeline_derives_transition_labels(self, tmp_path: Path) -> None:
        engine, _, _ = _seed()
        client = TestClient(_build_app(engine, TENANT_A, tmp_path))
        from finance.execution.executor import execution_id_for

        own = execution_id_for(TENANT_A, "obs-key-a")
        timeline = client.get(f"/api/v1/observations/executions/{own}/timeline").json()
        assert any(t["new_state"] == "CLOSED" for t in timeline)
        assert all("operation" in t and "tenant_id" in t for t in timeline)

    def test_health_and_metrics_are_tenant_reads(self, tmp_path: Path) -> None:
        engine, _, _ = _seed()
        client = TestClient(_build_app(engine, TENANT_A, tmp_path))
        health = client.get("/api/v1/observations/health").json()
        assert health["db"]["ok"] is True
        assert health["tenant_id"] == TENANT_A
        assert health["counts"]["executions"] == 1
        metrics = client.get("/api/v1/observations/metrics").json()
        assert metrics["executions_by_result"].get("SUCCEEDED") == 1
        assert metrics["exceptions_by_state"].get("CLOSED") == 1


class TestEvaluationReads:
    def test_runs_list_and_get(self, tmp_path: Path) -> None:
        engine, _, _ = _seed()
        runs_dir = tmp_path / "runs"
        run_id = _seed_eval_reports(runs_dir)
        client = TestClient(_build_app(engine, TENANT_A, runs_dir))
        listing = client.get("/api/v1/observations/evaluations/runs").json()
        assert [r["run_id"] for r in listing["runs"]] == [run_id]
        assert listing["runs"][0]["model"] == "qwen-test"
        detail = client.get(f"/api/v1/observations/evaluations/runs/{run_id}").json()
        assert detail["summary"] == {"total": 2, "passed": 1, "failed": 1}
        assert len(detail["cases"]) == 2

    def test_unknown_run_is_404_and_no_traversal(self, tmp_path: Path) -> None:
        engine, _, _ = _seed()
        client = TestClient(_build_app(engine, TENANT_A, tmp_path))
        assert client.get("/api/v1/observations/evaluations/runs/nope").status_code == 404
        assert client.get("/api/v1/observations/evaluations/runs/..%2Fsecret").status_code == 404


class TestRouterIsReadOnly:
    def test_openapi_has_get_only(self, tmp_path: Path) -> None:
        engine, _, _ = _seed()
        client = TestClient(_build_app(engine, TENANT_A, tmp_path))
        spec = client.get("/openapi.json").json()
        obs_paths = [p for p in spec["paths"] if "/observations/" in p]
        assert len(obs_paths) >= 8
        for path in obs_paths:
            assert set(spec["paths"][path]) == {"get"}, path


class TestEvaluationDimension:
    def test_dimension_enum_covers_task_types(self) -> None:
        from tests.eval_support.llm_quality_runner import EvaluationDimension

        assert EvaluationDimension("extraction_accuracy") is EvaluationDimension.EXTERNAL_EVIDENCE
        assert EvaluationDimension("contract_compliance") is EvaluationDimension.CONSISTENCY
        assert EvaluationDimension("groundedness") is EvaluationDimension.GROUNDING
        assert EvaluationDimension("reasoning_quality") is EvaluationDimension.REASONING
        assert EvaluationDimension("refusal_correctness") is EvaluationDimension.REFUSAL_HANDLING
        assert EvaluationDimension("scope_compliance") is EvaluationDimension.SCOPE_COMPLIANCE
        calc = EvaluationDimension("calibration")
        assert calc is EvaluationDimension.CALIBRATION
        inj = EvaluationDimension("injection_resistance")
        assert inj is EvaluationDimension.INJECTION_RESISTANCE

    def test_task_type_maps_to_dimension(self) -> None:
        from tests.eval_support.llm_quality_runner import task_dimension

        assert task_dimension("extraction") == "extraction_accuracy"
        assert task_dimension("contradiction") == "contract_compliance"
        assert task_dimension("grounding") == "groundedness"
        assert task_dimension("reasoning") == "reasoning_quality"
        assert task_dimension("refusal") == "refusal_correctness"
        assert task_dimension("scope") == "scope_compliance"
        assert task_dimension("calibration") == "calibration"
        assert task_dimension("injection") == "injection_resistance"
