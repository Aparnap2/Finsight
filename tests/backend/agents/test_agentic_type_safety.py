"""Agentic capability tests: Type Safety dimension.

Tests that Pydantic models enforce Decimal for monetary fields,
accept appropriate types for non-monetary fields, and properly
validate PipelineState structure.
"""

import pytest
from decimal import Decimal
from pydantic import ValidationError

from backend.models.state import Variance, EvidenceItem, Scenario, PipelineState
from backend.models.assertions import Assertion, AssertionType, SupportLevel


# ── Variance type safety ──────────────────────────────────────────────────────


class TestVarianceTypeSafety:
    def test_decimal_amounts_accepted(self):
        """Variance must accept Decimal for all monetary fields."""
        v = Variance(
            account_id="4010",
            account_name="Test",
            department="Eng",
            actual_amount=Decimal("100000.50"),
            budget_amount=Decimal("120000.00"),
            variance_amount=Decimal("-19999.50"),
            variance_pct=Decimal("-16.67"),
        )
        assert isinstance(v.actual_amount, Decimal)
        assert isinstance(v.budget_amount, Decimal)
        assert isinstance(v.variance_amount, Decimal)
        assert isinstance(v.variance_pct, Decimal)

    def test_confidence_score_is_float(self):
        """confidence_score is not money — must be float."""
        v = Variance(
            account_id="4010",
            account_name="Test",
            department="Eng",
            actual_amount=Decimal("100000"),
            budget_amount=Decimal("120000"),
            variance_amount=Decimal("-20000"),
            variance_pct=Decimal("-16.67"),
            confidence_score=0.85,
        )
        assert isinstance(v.confidence_score, float)

    def test_is_material_defaults_false(self):
        """is_material must default to False when not provided."""
        v = Variance(
            account_id="4010",
            account_name="Test",
            department="Eng",
            actual_amount=Decimal("100000"),
            budget_amount=Decimal("100000"),
            variance_amount=Decimal("0"),
            variance_pct=Decimal("0"),
        )
        assert v.is_material is False

    def test_large_decimal_amounts(self):
        """Variance must handle large monetary values."""
        v = Variance(
            account_id="9999",
            account_name="Big Revenue",
            department="Sales",
            actual_amount=Decimal("9999999999.99"),
            budget_amount=Decimal("8888888888.88"),
            variance_amount=Decimal("1111111111.11"),
            variance_pct=Decimal("12.50"),
        )
        assert v.variance_amount == Decimal("1111111111.11")


# ── EvidenceItem type safety ──────────────────────────────────────────────────


class TestEvidenceItemTypeSafety:
    def test_decimal_value_accepted(self):
        """EvidenceItem must accept Decimal for value."""
        e = EvidenceItem(
            source_table="actuals",
            record_id="rec-1",
            field="amount",
            value=Decimal("50000.00"),
            period="2026-06",
        )
        assert isinstance(e.value, Decimal)
        assert e.value == Decimal("50000.00")

    def test_string_description_accepted(self):
        """Non-monetary fields must accept string values."""
        e = EvidenceItem(
            source_table="test",
            record_id="r1",
            field="description",
            value=Decimal("0"),
            period="2026-06",
            description="Some descriptive text about the evidence",
        )
        assert e.description == "Some descriptive text about the evidence"

    def test_empty_description_default(self):
        """description must default to empty string."""
        e = EvidenceItem(
            source_table="test",
            record_id="r1",
            field="amount",
            value=Decimal("50000"),
            period="2026-06",
        )
        assert e.description == ""


# ── Scenario type safety ──────────────────────────────────────────────────────


class TestScenarioTypeSafety:
    def test_decimal_impacts_accepted(self):
        """Scenario must accept Decimal for all impact fields."""
        s = Scenario(
            name="Test Scenario",
            description="A test scenario",
            assumptions={"growth_rate": "5%"},
            revenue_impact=Decimal("50000"),
            ebitda_impact=Decimal("30000"),
            cash_impact=Decimal("10000"),
            probability_assessment="medium",
        )
        assert isinstance(s.revenue_impact, Decimal)
        assert isinstance(s.ebitda_impact, Decimal)
        assert isinstance(s.cash_impact, Decimal)

    def test_probability_must_be_string(self):
        """probability_assessment must accept string values."""
        s = Scenario(
            name="Pessimistic",
            description="Downturn scenario",
            assumptions={},
            revenue_impact=Decimal("-50000"),
            ebitda_impact=Decimal("-30000"),
            cash_impact=Decimal("-10000"),
            probability_assessment="low",
        )
        assert s.probability_assessment == "low"

    def test_assumptions_dict_accepted(self):
        """assumptions must accept dict with various value types."""
        s = Scenario(
            name="Growth",
            description="Growth scenario",
            assumptions={"rate": 0.05, "headcount": 10, "reason": "expansion"},
            revenue_impact=Decimal("100000"),
            ebitda_impact=Decimal("50000"),
            cash_impact=Decimal("25000"),
            probability_assessment="high",
        )
        assert s.assumptions["rate"] == 0.05
        assert s.assumptions["headcount"] == 10


# ── Assertion type safety ─────────────────────────────────────────────────────


class TestAssertionTypeSafety:
    def test_assertion_value_optional(self):
        """Assertion.value must be optional (None allowed)."""
        a = Assertion(
            id="a1",
            type=AssertionType.ACTION,
            text="Review the report",
        )
        assert a.value is None

    def test_assertion_with_decimal_value(self):
        """Assertion.value must accept Decimal."""
        a = Assertion(
            id="a2",
            type=AssertionType.NUMERIC,
            text="Revenue was $100K",
            value=Decimal("100000"),
        )
        assert a.value == Decimal("100000")

    def test_assertion_enum_types(self):
        """AssertionType enum must have expected values."""
        assert AssertionType.NUMERIC.value == "numeric"
        assert AssertionType.COMPARATIVE.value == "comparative"
        assert AssertionType.CAUSAL.value == "causal"
        assert AssertionType.HYPOTHESIS.value == "hypothesis"
        assert AssertionType.ACTION.value == "action"

    def test_support_level_default(self):
        """Default support_level must be INSUFFICIENT."""
        a = Assertion(
            id="a3",
            type=AssertionType.NUMERIC,
            text="Test",
        )
        assert a.support_level == SupportLevel.INSUFFICIENT


# ── PipelineState type safety ─────────────────────────────────────────────────


class TestPipelineStateTypeSafety:
    def test_pipeline_state_minimal(self):
        """PipelineState must accept minimal valid state."""
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
        assert state["period"] == "2026-06"
        assert state["current_step"] == "start"
        assert state["variances"] == []
        assert state["error"] is None

    def test_pipeline_state_with_variance(self):
        """PipelineState must contain Variance objects in variances list."""
        v = Variance(
            account_id="4000",
            account_name="Revenue",
            department="Sales",
            actual_amount=Decimal("100000"),
            budget_amount=Decimal("120000"),
            variance_amount=Decimal("-20000"),
            variance_pct=Decimal("-16.67"),
        )
        state: PipelineState = {
            "period": "2026-06",
            "entity_id": "CF001",
            "actuals": {},
            "budget": {},
            "forecast": {},
            "variances": [v],
            "root_causes": [],
            "commentary_draft": None,
            "scenarios": [],
            "review_decisions": [],
            "error": None,
            "current_step": "variance_complete",
        }
        assert len(state["variances"]) == 1
        assert state["variances"][0].account_id == "4000"
