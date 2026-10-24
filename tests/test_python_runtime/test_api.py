"""End-to-end integration tests for the Compute Runtime API."""

import asyncio
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.main import app

#: The tenant boundary (apps/api/middleware.py) requires these headers on
#: every non-health, non-webhook request.  Requests without them are
#: rejected with 401 before any handler runs.
TENANT_HEADERS = {"X-Tenant-ID": "TENANT_A", "X-User-ID": "user_1", "X-Role": "analyst"}


@pytest.fixture
def sample_csv(tmp_path: Path) -> str:
    df = pl.DataFrame(
        {
            "account_id": ["A100", "A101"],
            "period": ["2026-Q1", "2026-Q1"],
            "amount": [1000.0, 2500.0],
            "department": ["Sales", "Engineering"],
            "currency": ["USD", "USD"],
        }
    )
    path = tmp_path / "test.csv"
    df.write_csv(path)
    return str(path)


async def test_submit_and_poll_job(sample_csv: str, fake_rls_session: Any) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/jobs/submit",
            json={
                "pipeline": "analytics",
                "source_type": "csv",
                "source_uri": sample_csv,
                "params": {
                    "query": (
                        "SELECT account_id, SUM(amount) as total FROM data GROUP BY account_id"
                    ),
                },
            },
            headers=TENANT_HEADERS,
        )
    assert resp.status_code == 202
    data = resp.json()
    job_id = data["job_id"]
    # The job may be queued or already running by the time we get the response
    assert data["status"] in ("queued", "running")
    assert "poll_url" in data

    # Poll until complete
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        status_resp = await client.get(data["poll_url"], headers=TENANT_HEADERS)
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["job_id"] == job_id


async def test_submit_invalid_job(fake_rls_session: Any) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/jobs/submit",
            json={"pipeline": "unknown", "source_type": "csv", "source_uri": "/nonexistent.csv"},
            headers=TENANT_HEADERS,
        )
    assert resp.status_code == 202
    data = resp.json()

    # Poll with retry — the thread pool may take a moment to pick up the job
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for _ in range(10):
            await asyncio.sleep(0.05)
            status_resp = await client.get(data["poll_url"], headers=TENANT_HEADERS)
            assert status_resp.status_code == 200
            status_data = status_resp.json()
            if status_data["status"] == "failed":
                break
        else:
            # Last attempt without loop to get clean assertion error
            status_resp = await client.get(data["poll_url"], headers=TENANT_HEADERS)
            status_data = status_resp.json()
        assert status_data["status"] == "failed"


async def test_get_nonexistent_job(fake_rls_session: Any) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/jobs/00000000-0000-0000-0000-000000000000/status",
            headers=TENANT_HEADERS,
        )
    assert resp.status_code == 404


async def test_cancel_queued_job(sample_csv: str, fake_rls_session: Any) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/jobs/submit",
            json={
                "pipeline": "analytics",
                "source_type": "csv",
                "source_uri": sample_csv,
                "params": {"query": "SELECT COUNT(*) FROM data"},
            },
            headers=TENANT_HEADERS,
        )
    job_id = resp.json()["job_id"]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cancel_resp = await client.post(f"/api/v1/jobs/{job_id}/cancel", headers=TENANT_HEADERS)
    assert cancel_resp.status_code in (200, 400)
    if cancel_resp.status_code == 200:
        assert cancel_resp.json()["status"] == "cancelled"


class TestTenantBoundary:
    """The 401 path: the tenant boundary rejects callers without an actor.

    These assertions were previously invisible because no workflow executed
    this file (APA-94 G1).  The rejection must happen before any handler
    runs, and the response must not leak protected data.
    """

    @pytest.mark.parametrize(
        "headers",
        [
            {},
            {"X-Tenant-ID": "TENANT_A"},
            {"X-Role": "analyst"},
        ],
        ids=["no-headers", "tenant-only", "role-only"],
    )
    async def test_missing_actor_headers_are_rejected(self, headers: dict[str, str]) -> None:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/jobs/00000000-0000-0000-0000-000000000000/status",
                headers=headers,
            )
        assert resp.status_code == 401
        assert resp.json() == {"detail": "Missing X-Tenant-ID or X-Role header"}

    async def test_rejection_does_not_leak_job_data(self) -> None:
        """A rejected request must not disclose whether the job exists."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/jobs/00000000-0000-0000-0000-000000000000/status",
            )
        assert resp.status_code == 401
        # The body may name the missing headers, but it must not carry any
        # job data: no identifiers, no pipeline, no state.
        body = resp.json()
        assert set(body) == {"detail"}
        detail = body["detail"].lower()
        for leak in ("job_id", "job id", "pipeline", "account", "amount", "queued", "failed"):
            assert leak not in detail

    async def test_unknown_role_is_rejected_with_403(self) -> None:
        """A known tenant with an unknown role is 403, not 401."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/jobs/00000000-0000-0000-0000-000000000000/status",
                headers={"X-Tenant-ID": "TENANT_A", "X-Role": "not-a-role"},
            )
        assert resp.status_code == 403
        assert "not-a-role" in resp.json()["detail"]
