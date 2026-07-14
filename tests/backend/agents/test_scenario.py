from backend.agents.scenario_agent import generate_scenarios, scenario_node
from backend.models.state import Scenario, RootCauseFinding, PipelineState


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


def test_generate_scenarios_returns_list():
    scenarios = generate_scenarios([])
    assert isinstance(scenarios, list)
    assert len(scenarios) >= 1


def test_scenario_has_financial_impacts():
    scenarios = generate_scenarios([])
    s = scenarios[0]
    assert hasattr(s, "revenue_impact")
    assert hasattr(s, "ebitda_impact")
    assert hasattr(s, "cash_impact")


def test_scenario_has_probability():
    scenarios = generate_scenarios([])
    assert scenarios[0].probability_assessment in ("high", "medium", "low")


def test_scenario_node_returns_scenarios():
    state = _make_state(
        root_causes=[
            RootCauseFinding(
                variance_id="4001", summary="Test",
                confidence_score=0.8,
            )
        ]
    )
    result = scenario_node(state)
    assert len(result["scenarios"]) >= 1
    assert result["current_step"] == "scenario_complete"
