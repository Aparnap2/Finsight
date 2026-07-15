import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient
from backend.main import app
from backend.models.database import Base
from backend.data.seed import seed_database
from backend.agents.ingestion_agent import ingestion_node
from backend.agents.variance_agent import variance_node
from backend.models.state import PipelineState

client = TestClient(app)


@pytest.fixture()
def seeded_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_database(session)
    return engine


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


def test_pipeline_e2e_with_real_db(seeded_db):
    state: PipelineState = {
        "period": "2026-06",
        "entity_id": "CF001",
        "actuals": {},
        "budget": {},
        "forecast": {},
        "variances": [],
        "root_causes": [],
        "commentary_draft": None,
        "scenarios": [],
        "review_decisions": [],
        "error": None,
        "current_step": "start",
    }
    ingestion_result = ingestion_node(state, engine=seeded_db)
    state.update(ingestion_result)

    actuals_count = len(state["actuals"]["accounts"])
    budget_count = len(state["budget"]["accounts"])
    assert actuals_count > 0, f"Expected real actuals, got {actuals_count}"
    assert budget_count > 0, f"Expected real budget, got {budget_count}"

    variance_result = variance_node(state)
    state["variances"] = variance_result["variances"]

    material = [v for v in state["variances"] if v.is_material]
    assert len(material) > 0, "Seeded data should produce material variances"
    assert any(
        abs(v.variance_amount) > 10000 for v in material
    ), "At least one material variance should exceed $10K"


def test_api_trigger_returns_run_id():
    response = client.post(
        "/api/v1/pipeline/run",
        json={"period": "2026-06", "entity_id": "CF001"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "run_id" in data
    assert data["status"] == "started"


def test_api_pipeline_result_has_variances():
    response = client.post(
        "/api/v1/pipeline/run",
        json={"period": "2026-06", "entity_id": "CF001", "run_sync": True},
    )
    assert response.status_code == 200
    data = response.json()
    assert "variances" in data
    assert len(data["variances"]) > 0
    material = [v for v in data["variances"] if v.get("is_material")]
    assert len(material) > 0, "Should have material variances"


def test_import_csv_basic():
    csv_content = "account_id,period,amount,department,type\nc3da4e42,2026-06,50000,Sales,actual\nc3da4e42,2026-06,45000,Sales,budget"
    response = client.post(
        "/api/v1/import/csv",
        files={"file": ("test.csv", csv_content.encode(), "text/csv")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "imported"
    assert data["actuals_imported"] == 1
    assert data["budget_imported"] == 1


def test_import_csv_empty():
    response = client.post(
        "/api/v1/import/csv",
        files={"file": ("empty.csv", b"", "text/csv")},
    )
    assert response.status_code == 400


def test_import_csv_bad_columns():
    csv_content = "wrong,columns\na,b"
    response = client.post(
        "/api/v1/import/csv",
        files={"file": ("bad.csv", csv_content.encode(), "text/csv")},
    )
    assert response.status_code == 400
