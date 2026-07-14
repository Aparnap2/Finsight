from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_api_docs():
    response = client.get("/docs")
    assert response.status_code == 200


def test_trigger_pipeline():
    response = client.post(
        "/api/v1/pipeline/run",
        json={"period": "2026-06", "entity_id": "CF001"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "run_id" in data
    assert data["status"] == "started"


def test_trigger_pipeline_default_entity():
    response = client.post(
        "/api/v1/pipeline/run",
        json={"period": "2026-06"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "started"


def test_get_pipeline_status():
    trigger = client.post(
        "/api/v1/pipeline/run",
        json={"period": "2026-06"},
    )
    run_id = trigger.json()["run_id"]
    response = client.get(f"/api/v1/pipeline/{run_id}/status")
    assert response.status_code == 200
    assert response.json()["status"] == "started"


def test_get_pipeline_status_not_found():
    response = client.get("/api/v1/pipeline/nonexistent/status")
    assert response.status_code == 404
