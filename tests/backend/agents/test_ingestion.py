from backend.agents.ingestion_agent import ingestion_node
from backend.models.state import PipelineState


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
