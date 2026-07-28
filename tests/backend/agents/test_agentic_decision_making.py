"""Agentic capability tests: Decision Making & Routing dimensions.

Tests materiality computation, threshold boundaries, variance calculations,
and routing decisions based on materiality flags.
"""

import pytest
from decimal import Decimal

from backend.agents.variance_agent import compute_variances, apply_materiality
from backend.agents.orchestrator import _route_after_variance
from backend.models.state import Variance, PipelineState


# ── Variance computation ──────────────────────────────────────────────────────


class TestVarianceComputation:
    def test_simple_positive_variance(self):
        """Actual > Budget must produce positive variance."""
        actuals = [{"account_id": "A1", "amount": Decimal("1000"), "account_name": "Rev", "department": "Sales"}]
        budget = [{"account_id": "A1", "amount": Decimal("800"), "account_name": "Rev", "department": "Sales"}]
        variances = compute_variances(actuals, budget)
        assert len(variances) == 1
        assert variances[0].variance_amount == Decimal("200")
        assert variances[0].variance_pct == Decimal("25.00")

    def test_negative_variance(self):
        """Actual < Budget must produce negative variance."""
        actuals = [{"account_id": "A1", "amount": Decimal("500"), "account_name": "Rev", "department": "Sales"}]
        budget = [{"account_id": "A1", "amount": Decimal("1000"), "account_name": "Rev", "department": "Sales"}]
        variances = compute_variances(actuals, budget)
        assert len(variances) == 1
        assert variances[0].variance_amount == Decimal("-500")

    def test_zero_variance(self):
        """Actual == Budget must produce zero variance."""
        actuals = [{"account_id": "A1", "amount": Decimal("1000"), "account_name": "Rev", "department": "Sales"}]
        budget = [{"account_id": "A1", "amount": Decimal("1000"), "account_name": "Rev", "department": "Sales"}]
        variances = compute_variances(actuals, budget)
        assert variances[0].variance_amount == Decimal("0")
        assert variances[0].variance_pct == Decimal("0.00")

    def test_zero_budget_no_division_error(self):
        """Zero budget must not cause division-by-zero — variance_pct must be 0."""
        actuals = [{"account_id": "A1", "amount": Decimal("500"), "account_name": "Rev", "department": "Sales"}]
        budget = [{"account_id": "A1", "amount": Decimal("0"), "account_name": "Rev", "department": "Sales"}]
        variances = compute_variances(actuals, budget)
        assert variances[0].variance_pct == Decimal("0")

    def test_missing_budget_account(self):
        """Missing budget for an account must treat budget as 0."""
        actuals = [{"account_id": "A1", "amount": Decimal("500"), "account_name": "Rev", "department": "Sales"}]
        budget = []  # No matching budget
        variances = compute_variances(actuals, budget)
        assert variances[0].variance_amount == Decimal("500")

    def test_multiple_accounts(self):
        """Multiple accounts must each produce a Variance."""
        actuals = [
            {"account_id": "A1", "amount": Decimal("1000"), "account_name": "Rev", "department": "Sales"},
            {"account_id": "A2", "amount": Decimal("500"), "account_name": "Cost", "department": "Eng"},
        ]
        budget = [
            {"account_id": "A1", "amount": Decimal("800"), "account_name": "Rev", "department": "Sales"},
            {"account_id": "A2", "amount": Decimal("600"), "account_name": "Cost", "department": "Eng"},
        ]
        variances = compute_variances(actuals, budget)
        assert len(variances) == 2
        assert variances[0].account_id == "A1"
        assert variances[1].account_id == "A2"

    def test_variance_pct_quantized(self):
        """Variance percentage must be quantized to 2 decimal places."""
        actuals = [{"account_id": "A1", "amount": Decimal("1000"), "account_name": "Rev", "department": "Sales"}]
        budget = [{"account_id": "A1", "amount": Decimal("333"), "account_name": "Rev", "department": "Sales"}]
        variances = compute_variances(actuals, budget)
        # (1000-333)/333 * 100 = 200.300300... → quantized to 200.30
        assert variances[0].variance_pct == Decimal("200.30")


# ── Materiality ───────────────────────────────────────────────────────────────


class TestMateriality:
    def test_large_variance_is_material(self):
        """Variance exceeding both amount and pct thresholds must be material."""
        v = Variance(
            account_id="A1",
            account_name="Rev",
            department="Sales",
            actual_amount=Decimal("200000"),
            budget_amount=Decimal("100000"),
            variance_amount=Decimal("100000"),
            variance_pct=Decimal("100.0"),
        )
        result = apply_materiality([v], threshold_amount=5000, threshold_pct=5.0)
        assert result[0].is_material is True

    def test_small_variance_is_immaterial(self):
        """Variance below both thresholds must be immaterial."""
        v = Variance(
            account_id="A1",
            account_name="Rev",
            department="Sales",
            actual_amount=Decimal("101"),
            budget_amount=Decimal("100"),
            variance_amount=Decimal("1"),
            variance_pct=Decimal("1.0"),
        )
        result = apply_materiality([v], threshold_amount=5000, threshold_pct=5.0)
        assert result[0].is_material is False

    def test_exactly_at_amount_threshold_is_material(self):
        """Variance exactly at the amount threshold AND above pct threshold must be material."""
        v = Variance(
            account_id="A1",
            account_name="Rev",
            department="Sales",
            actual_amount=Decimal("105000"),
            budget_amount=Decimal("100000"),
            variance_amount=Decimal("5000"),
            variance_pct=Decimal("5.0"),
        )
        result = apply_materiality([v], threshold_amount=5000, threshold_pct=5.0)
        assert result[0].is_material is True

    def test_above_amount_but_below_pct_is_immaterial(self):
        """Variance above amount threshold but below pct threshold must be immaterial."""
        v = Variance(
            account_id="A1",
            account_name="Rev",
            department="Sales",
            actual_amount=Decimal("106000"),
            budget_amount=Decimal("100000"),
            variance_amount=Decimal("6000"),
            variance_pct=Decimal("6.0"),
        )
        # Set pct threshold high so pct is below it
        result = apply_materiality([v], threshold_amount=5000, threshold_pct=10.0)
        assert result[0].is_material is False

    def test_above_pct_but_below_amount_is_immaterial(self):
        """Variance above pct threshold but below amount threshold must be immaterial."""
        v = Variance(
            account_id="A1",
            account_name="Rev",
            department="Sales",
            actual_amount=Decimal("103000"),
            budget_amount=Decimal("100000"),
            variance_amount=Decimal("3000"),
            variance_pct=Decimal("3.0"),
        )
        # Set amount threshold high so amount is below it
        result = apply_materiality([v], threshold_amount=5000, threshold_pct=2.0)
        assert result[0].is_material is False

    def test_zero_variance_is_immaterial(self):
        """Zero variance must be immaterial."""
        v = Variance(
            account_id="A1",
            account_name="Rev",
            department="Sales",
            actual_amount=Decimal("100000"),
            budget_amount=Decimal("100000"),
            variance_amount=Decimal("0"),
            variance_pct=Decimal("0"),
        )
        result = apply_materiality([v], threshold_amount=1, threshold_pct=1.0)
        assert result[0].is_material is False

    def test_negative_variance_materiality(self):
        """Negative variance meeting thresholds must be material."""
        v = Variance(
            account_id="A1",
            account_name="Rev",
            department="Sales",
            actual_amount=Decimal("50000"),
            budget_amount=Decimal("100000"),
            variance_amount=Decimal("-50000"),
            variance_pct=Decimal("-50.0"),
        )
        result = apply_materiality([v], threshold_amount=5000, threshold_pct=5.0)
        assert result[0].is_material is True

    def test_multiple_variances_independent_materiality(self):
        """Multiple variances must each get independent materiality flags."""
        variances = [
            Variance(
                account_id="A1", account_name="Big", department="Sales",
                actual_amount=Decimal("200000"), budget_amount=Decimal("100000"),
                variance_amount=Decimal("100000"), variance_pct=Decimal("100.0"),
            ),
            Variance(
                account_id="A2", account_name="Small", department="Eng",
                actual_amount=Decimal("101"), budget_amount=Decimal("100"),
                variance_amount=Decimal("1"), variance_pct=Decimal("1.0"),
            ),
        ]
        result = apply_materiality(variances, threshold_amount=5000, threshold_pct=5.0)
        assert result[0].is_material is True
        assert result[1].is_material is False

    def test_custom_thresholds(self):
        """Materiality must respect custom threshold values."""
        v = Variance(
            account_id="A1",
            account_name="Rev",
            department="Sales",
            actual_amount=Decimal("2000"),
            budget_amount=Decimal("1000"),
            variance_amount=Decimal("1000"),
            variance_pct=Decimal("100.0"),
        )
        # Low thresholds — this is material
        result = apply_materiality([v], threshold_amount=100, threshold_pct=2.0)
        assert result[0].is_material is True

        # High thresholds — this is not material
        result = apply_materiality([v], threshold_amount=5000, threshold_pct=200.0)
        assert result[0].is_material is False


# ── Routing logic ─────────────────────────────────────────────────────────────


class TestRouting:
    def test_material_variances_route_to_root_cause(self):
        """When material variances exist, route must be 'root_cause'."""
        state: PipelineState = {
            "period": "2026-06",
            "entity_id": "CF001",
            "actuals": {},
            "budget": {},
            "forecast": {},
            "variances": [
                Variance(
                    account_id="A1", account_name="Rev", department="Sales",
                    actual_amount=Decimal("200000"), budget_amount=Decimal("100000"),
                    variance_amount=Decimal("100000"), variance_pct=Decimal("100"),
                    is_material=True,
                )
            ],
            "root_causes": [],
            "commentary_draft": None,
            "scenarios": [],
            "review_decisions": [],
            "error": None,
            "current_step": "variance_complete",
        }
        route = _route_after_variance(state)
        assert route == "root_cause"

    def test_no_material_variances_route_to_commentary(self):
        """When no material variances exist, route must be 'commentary'."""
        state: PipelineState = {
            "period": "2026-06",
            "entity_id": "CF001",
            "actuals": {},
            "budget": {},
            "forecast": {},
            "variances": [
                Variance(
                    account_id="A1", account_name="Rev", department="Sales",
                    actual_amount=Decimal("101"), budget_amount=Decimal("100"),
                    variance_amount=Decimal("1"), variance_pct=Decimal("1"),
                    is_material=False,
                )
            ],
            "root_causes": [],
            "commentary_draft": None,
            "scenarios": [],
            "review_decisions": [],
            "error": None,
            "current_step": "variance_complete",
        }
        route = _route_after_variance(state)
        assert route == "commentary"

    def test_empty_variances_route_to_commentary(self):
        """When variances list is empty, route must be 'commentary'."""
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
            "current_step": "variance_complete",
        }
        route = _route_after_variance(state)
        assert route == "commentary"

    def test_mixed_materiality_routes_to_root_cause(self):
        """If any variance is material, route must be 'root_cause'."""
        state: PipelineState = {
            "period": "2026-06",
            "entity_id": "CF001",
            "actuals": {},
            "budget": {},
            "forecast": {},
            "variances": [
                Variance(
                    account_id="A1", account_name="Small", department="Sales",
                    actual_amount=Decimal("101"), budget_amount=Decimal("100"),
                    variance_amount=Decimal("1"), variance_pct=Decimal("1"),
                    is_material=False,
                ),
                Variance(
                    account_id="A2", account_name="Big", department="Sales",
                    actual_amount=Decimal("200000"), budget_amount=Decimal("100000"),
                    variance_amount=Decimal("100000"), variance_pct=Decimal("100"),
                    is_material=True,
                ),
            ],
            "root_causes": [],
            "commentary_draft": None,
            "scenarios": [],
            "review_decisions": [],
            "error": None,
            "current_step": "variance_complete",
        }
        route = _route_after_variance(state)
        assert route == "root_cause"
