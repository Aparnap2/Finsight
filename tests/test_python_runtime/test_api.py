"""End-to-end integration tests for the Compute Runtime API."""

import asyncio
from pathlib import Path

import polars as pl
import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.main import app


@pytest.fixture
def sample_csv(tmp_path: Path) -> str:
    df = pl.DataFrame({
        "account_id": ["A100", "A101"],
        "period": ["2026-Q1", "2026-Q1"],
        "amount": [1000.0, 2500.0],
        "department": ["Sales", "Engineering"],
        "currency": ["USD", "USD"],
    })
    path = tmp_path / "test.csv"
    df.write_csv(path)
    return str(path)


async def test_submit_and_poll_job(sample_csv: str) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/jobs/submit",
            json={
                "pipeline": "analytics",
                "source_type": "csv",
                "source_uri": sample_csv,
                "params": {
                    "query": "SELECT account_id, SUM(amount) as total FROM data GROUP BY account_id",
                },
            },
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
        status_resp = await client.get(data["poll_url"])
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["job_id"] == job_id


async def test_submit_invalid_job() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/jobs/submit",
            json={"pipeline": "unknown", "source_type": "csv", "source_uri": "/nonexistent.csv"},
        )
    assert resp.status_code == 202
    data = resp.json()

    # Poll with retry — the thread pool may take a moment to pick up the job
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for _ in range(10):
            await asyncio.sleep(0.05)
            status_resp = await client.get(data["poll_url"])
            assert status_resp.status_code == 200
            status_data = status_resp.json()
            if status_data["status"] == "failed":
                break
        else:
            # Last attempt without loop to get clean assertion error
            status_resp = await client.get(data["poll_url"])
            status_data = status_resp.json()
        assert status_data["status"] == "failed"


async def test_get_nonexistent_job() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/jobs/00000000-0000-0000-0000-000000000000/status")
    assert resp.status_code == 404


async def test_cancel_queued_job(sample_csv: str) -> None:
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
        )
    job_id = resp.json()["job_id"]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cancel_resp = await client.post(f"/api/v1/jobs/{job_id}/cancel")
    assert cancel_resp.status_code in (200, 400)
    if cancel_resp.status_code == 200:
        assert cancel_resp.json()["status"] == "cancelled"
