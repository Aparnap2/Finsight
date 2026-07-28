import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from backend.agents.ingestion_agent import ingestion_node
from backend.models.database import Base
from backend.models.state import PipelineState
from backend.data.seed import seed_database


@pytest.fixture()
def seeded_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_database(session)
    return engine


def _make_state(**overrides) -> PipelineState:
    base: PipelineState = {
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
    base.update(overrides)
    return base


def test_ingestion_returns_actuals():
    state = _make_state()
    result = ingestion_node(state)
    assert "actuals" in result
    assert "budget" in result
    assert result["current_step"] == "ingestion_complete"


def test_ingestion_captures_period():
    state = _make_state(period="2025-12")
    result = ingestion_node(state)
    assert result["actuals"]["period"] == "2025-12"


def test_ingestion_detects_anomalies():
    state = _make_state()
    result = ingestion_node(state)
    assert isinstance(result["actuals"]["anomalies"], list)


def test_ingestion_reconciliation_flag():
    state = _make_state()
    result = ingestion_node(state)
    assert isinstance(result["actuals"]["is_reconciled"], bool)


def test_ingestion_fetches_real_actuals(seeded_db):
    state = _make_state()
    result = ingestion_node(state, engine=seeded_db)
    accounts = result["actuals"]["accounts"]
    assert len(accounts) > 0
    assert all("account_id" in a and "amount" in a for a in accounts)


def test_ingestion_fetches_real_budget(seeded_db):
    state = _make_state()
    result = ingestion_node(state, engine=seeded_db)
    accounts = result["budget"]["accounts"]
    assert len(accounts) > 0
    assert all("account_id" in b and "amount" in b for b in accounts)


def test_ingestion_detects_known_variance(seeded_db):
    state = _make_state(period="2026-06")
    result = ingestion_node(state, engine=seeded_db)
    actuals = result["actuals"]["accounts"]
    budget = result["budget"]["accounts"]
    actual_map = {a["account_id"]: a["amount"] for a in actuals}
    budget_map = {b["account_id"]: b["amount"] for b in budget}
    has_variance = any(
        abs(actual_map.get(aid, 0) - budget_map.get(aid, 0)) > 1000
        for aid in actual_map
        if aid in budget_map
    )
    assert has_variance, "Seeded data should contain at least one variance > $1000"


def test_ingestion_reconciles_debits_credits(seeded_db):
    state = _make_state()
    result = ingestion_node(state, engine=seeded_db)
    assert isinstance(result["actuals"]["is_reconciled"], bool)
