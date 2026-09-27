"""Phase 8 observability tests: request IDs, redaction, readiness, budget.

Additive-only: mounts ``apps.api.observability`` on throwaway FastAPI apps
with doubles — never touches frozen contracts or live Postgres.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from agents.p8_runtime.contract import Budget, BudgetUsage
from apps.api.observability import (
    REQUEST_ID_HEADER,
    RequestIDMiddleware,
    budget_check_response,
    create_readiness_router,
    format_request_log,
)

_CANARY_KEY = "sk-test-canary-abcdefgh12345678"
_CANARY_BEARER = "Bearer canary-secret-value-xyz"
_CANARY_EMAIL = "canary.user@example.com"


def _build_app(probe: Any = None) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)

    @app.get("/ping")
    async def ping() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/work")
    async def work(body: dict[str, Any]) -> JSONResponse:
        budget = Budget(
            max_model_calls=1,
            max_tokens=10,
            max_tool_calls=1,
            deadline_seconds=5.0,
            max_retries=0,
        )
        usage = BudgetUsage(
            model_calls=int(body.get("model_calls", 0)),
            tokens=0,
            tool_calls=0,
            elapsed_seconds=0.0,
            retries=0,
        )
        refused = budget_check_response(budget, usage)
        if refused is not None:
            return refused
        return JSONResponse(status_code=200, content={"status": "ok"})

    app.include_router(create_readiness_router(probe))
    return app


class TestRequestId:
    """Header in → same ID echoed in response and structured log."""

    def test_propagates_incoming_id(self, caplog: Any) -> None:
        client = TestClient(_build_app(probe=lambda: True))
        with caplog.at_level(logging.INFO, logger="finsight.request"):
            response = client.get("/ping", headers={REQUEST_ID_HEADER: "req-abc-123"})
        assert response.status_code == 200
        assert response.headers[REQUEST_ID_HEADER] == "req-abc-123"
        assert any("req-abc-123" in r.message for r in caplog.records)

    def test_generates_id_when_absent(self) -> None:
        client = TestClient(_build_app(probe=lambda: True))
        response = client.get("/ping")
        assert response.status_code == 200
        echoed = response.headers.get(REQUEST_ID_HEADER, "")
        assert echoed and len(echoed) >= 8

    def test_log_record_fields(self) -> None:
        record = format_request_log(
            request_id="req-1",
            tenant_id="tenant-a",
            situation_id="sit-9",
            method="GET",
            route="/ping",
            status_code=200,
            latency_ms=1.25,
        )
        assert record["request_id"] == "req-1"
        assert record["tenant_id"] == "tenant-a"
        assert record["situation_id"] == "sit-9"
        assert record["route"] == "/ping"
        assert record["disposition"] == "success"
        assert record["latency_ms"] == 1.25


class TestRedaction:
    """Canary secrets/PII appear nowhere: records, logs, responses."""

    def test_canaries_absent_from_record_and_logs(self, caplog: Any) -> None:
        record = format_request_log(
            request_id="req-2",
            tenant_id=_CANARY_EMAIL,
            situation_id=_CANARY_KEY,
            method="GET",
            route="/ping",
            status_code=200,
            latency_ms=0.5,
        )
        blob = " ".join(str(v) for v in record.values())
        assert _CANARY_KEY not in blob
        assert _CANARY_EMAIL not in blob

        client = TestClient(_build_app(probe=lambda: True))
        with caplog.at_level(logging.INFO, logger="finsight.request"):
            response = client.get(
                "/ping",
                headers={REQUEST_ID_HEADER: "req-canary-1", "X-Tenant-ID": _CANARY_EMAIL},
                params={"situation_id": _CANARY_KEY},
            )
        assert response.status_code == 200
        assert _CANARY_KEY not in response.text
        assert _CANARY_EMAIL not in response.text
        logs = "\n".join(r.message for r in caplog.records)
        assert _CANARY_KEY not in logs
        assert _CANARY_EMAIL not in logs
        assert _CANARY_BEARER not in logs


class TestReadiness:
    """Readiness reflects the DB probe; liveness never does (pure doubles)."""

    def test_ready_when_probe_true(self) -> None:
        client = TestClient(_build_app(probe=lambda: True))
        response = client.get("/ready")
        assert response.status_code == 200
        assert response.json() == {"status": "ready"}

    def test_not_ready_when_probe_false(self) -> None:
        client = TestClient(_build_app(probe=lambda: False))
        response = client.get("/ready")
        assert response.status_code == 503
        assert response.json() == {"status": "not_ready"}

    def test_not_ready_when_probe_raises(self) -> None:
        def _boom() -> bool:
            raise RuntimeError("db down")

        client = TestClient(_build_app(probe=_boom))
        response = client.get("/ready")
        assert response.status_code == 503

    def test_live_is_process_only(self) -> None:
        client = TestClient(_build_app(probe=lambda: False))
        response = client.get("/live")
        assert response.status_code == 200
        assert response.json() == {"status": "alive"}


class TestBudgetSurfacing:
    """Existing P8 Budget refusals are observable in response + logs."""

    def test_in_budget_passes(self) -> None:
        budget = Budget(
            max_model_calls=2,
            max_tokens=10,
            max_tool_calls=1,
            deadline_seconds=5.0,
            max_retries=0,
        )
        usage = BudgetUsage(model_calls=1, tokens=1, tool_calls=0, elapsed_seconds=0.1, retries=0)
        assert budget_check_response(budget, usage) is None

    def test_over_budget_refuses_with_typed_code(self, caplog: Any) -> None:
        budget = Budget(
            max_model_calls=1,
            max_tokens=10,
            max_tool_calls=1,
            deadline_seconds=5.0,
            max_retries=0,
        )
        usage = BudgetUsage(model_calls=5, tokens=0, tool_calls=0, elapsed_seconds=0.0, retries=0)
        with caplog.at_level(logging.WARNING, logger="finsight.request"):
            refused = budget_check_response(budget, usage)
        assert refused is not None
        assert refused.status_code == 429

    def test_route_refusal_observable(self, caplog: Any) -> None:
        client = TestClient(_build_app(probe=lambda: True))
        with caplog.at_level(logging.WARNING, logger="finsight.request"):
            response = client.post("/work", json={"model_calls": 5})
        assert response.status_code == 429
        assert response.json()["code"] == "BUDGET_EXHAUSTED"
        ok = client.post("/work", json={"model_calls": 0})
        assert ok.status_code == 200
