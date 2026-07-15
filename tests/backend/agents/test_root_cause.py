from backend.agents.root_cause_agent import investigate_root_causes, root_cause_node
from backend.models.state import Variance, RootCauseFinding, PipelineState


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


def test_investigate_returns_findings():
    variances = [
        Variance(
            account_id="4001", account_name="Revenue - Product Y", department="Sales",
            actual_amount=100000, budget_amount=120000,
            variance_amount=-20000, variance_pct=-16.67, is_material=True,
        )
    ]
    findings = investigate_root_causes(variances)
    assert len(findings) == 1
    assert findings[0].variance_id == "4001"
    assert findings[0].confidence_score > 0


def test_investigate_empty_returns_empty():
    findings = investigate_root_causes([])
    assert findings == []


def test_root_cause_node_only_material():
    variances = [
        Variance(
            account_id="4000", account_name="Test", department="Sales",
            actual_amount=100000, budget_amount=103000,
            variance_amount=-3000, variance_pct=-2.91, is_material=False,
        ),
        Variance(
            account_id="4001", account_name="Test2", department="Sales",
            actual_amount=100000, budget_amount=200000,
            variance_amount=-100000, variance_pct=-50.0, is_material=True,
        ),
    ]
    state = _make_state(variances=variances)
    result = root_cause_node(state)
    assert len(result["root_causes"]) == 1
    assert result["root_causes"][0].variance_id == "4001"
    assert result["current_step"] == "root_cause_complete"


def test_root_cause_node_no_material():
    state = _make_state(variances=[
        Variance(
            account_id="4000", account_name="Test", department="Sales",
            actual_amount=100000, budget_amount=103000,
            variance_amount=-3000, variance_pct=-2.91, is_material=False,
        )
    ])
    result = root_cause_node(state)
    assert result["root_causes"] == []
