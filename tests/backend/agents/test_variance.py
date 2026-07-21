from decimal import Decimal
from backend.agents.variance_agent import compute_variances, apply_materiality, variance_node
from backend.models.state import Variance, PipelineState


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


def test_compute_variances():
    actuals = [{"account_id": "4000", "amount": 100000}]
    budget = [{"account_id": "4000", "amount": 120000}]
    variances = compute_variances(actuals, budget)
    assert len(variances) == 1
    assert variances[0].variance_amount == Decimal("-20000")


def test_compute_variances_missing_budget():
    actuals = [{"account_id": "4000", "amount": 100000}]
    budget = []
    variances = compute_variances(actuals, budget)
    assert variances[0].variance_amount == Decimal("100000")


def test_materiality_flag():
    v = Variance(
        account_id="4000", account_name="Test", department="Sales",
        actual_amount=Decimal("100000"), budget_amount=Decimal("120000"),
        variance_amount=Decimal("-20000"), variance_pct=Decimal("-16.67"),
    )
    result = apply_materiality([v], threshold_amount=5000, threshold_pct=5.0)
    assert result[0].is_material is True


def test_non_material_variance():
    v = Variance(
        account_id="4000", account_name="Test", department="Sales",
        actual_amount=Decimal("100000"), budget_amount=Decimal("103000"),
        variance_amount=Decimal("-3000"), variance_pct=Decimal("-2.91"),
    )
    result = apply_materiality([v], threshold_amount=5000, threshold_pct=5.0)
    assert result[0].is_material is False


def test_variance_node_material_flagged():
    state = _make_state(
        actuals={"accounts": [{"account_id": "4000", "amount": 100000}]},
        budget={"accounts": [{"account_id": "4000", "amount": 200000}]},
    )
    result = variance_node(state)
    assert len(result["variances"]) == 1
    assert result["variances"][0].is_material is True
    assert result["current_step"] == "variance_complete"


def test_variance_node_no_material():
    state = _make_state(
        actuals={"accounts": [{"account_id": "4000", "amount": 100000}]},
        budget={"accounts": [{"account_id": "4000", "amount": 102000}]},
    )
    result = variance_node(state)
    assert result["variances"][0].is_material is False
