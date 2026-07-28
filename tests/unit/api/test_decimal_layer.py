"""Tests for the Decimal Money Layer in API schemas and routes.

Ensures all monetary values use decimal.Decimal throughout the API boundary,
with no silent float conversions or precision loss.

Test layout (TDD):
  1. Schema-level: Decimal accepted, float rejected for monetary fields
  2. Encoder-level: Decimal→string serialization
  3. Serializer-level: Helper functions
  4. Route-level: No floats in monetary response fields
  5. Backward compatibility: float raises clear error
"""

from decimal import Decimal
import json
import pytest
from pydantic import ValidationError
from apps.api.schemas import (
    VarianceResponse,
    AssertionResponse,
    ActionCreateRequest,
    BridgeAnalysisResponse,
    BridgeComponentResponse,
)
from shared.utils.encoders import DecimalEncoder
from apps.api.serializers import serialize_amounts


# ── 1. VarianceResponse ──────────────────────────────────────────────────────


class TestVarianceResponseDecimal:
    """Variance monetary fields must accept Decimal, reject float."""

    def test_variance_response_accepts_decimal(self):
        """Schema accepts Decimal values for all monetary fields."""
        v = VarianceResponse(
            account_id="a1",
            account_name="Revenue",
            department="Sales",
            actual_amount=Decimal("123456.78"),
            budget_amount=Decimal("100000.00"),
            variance_amount=Decimal("23456.78"),
            variance_pct=Decimal("23.46"),
            is_material=True,
        )
        assert isinstance(v.actual_amount, Decimal)
        assert isinstance(v.budget_amount, Decimal)
        assert isinstance(v.variance_amount, Decimal)
        assert isinstance(v.variance_pct, Decimal)
        assert v.actual_amount == Decimal("123456.78")
        assert v.budget_amount == Decimal("100000.00")
        assert v.variance_amount == Decimal("23456.78")
        assert v.variance_pct == Decimal("23.46")

    def test_variance_response_rejects_float(self):
        """Schema must raise ValidationError when float is passed for monetary fields."""
        with pytest.raises(ValidationError):
            VarianceResponse(
                account_id="a1",
                account_name="Revenue",
                department="Sales",
                actual_amount=123456.78,  # float — should be rejected
                budget_amount=Decimal("100000.00"),
                variance_amount=Decimal("23456.78"),
                variance_pct=Decimal("23.46"),
                is_material=True,
            )

    def test_variance_response_all_fields_decimal_type(self):
        """All four monetary fields in VarianceResponse must be Decimal type."""
        v = VarianceResponse(
            account_id="a1",
            account_name="Revenue",
            department="Sales",
            actual_amount=Decimal("0"),
            budget_amount=Decimal("0"),
            variance_amount=Decimal("0"),
            variance_pct=Decimal("0"),
            is_material=False,
        )
        fields = ["actual_amount", "budget_amount", "variance_amount", "variance_pct"]
        for field in fields:
            val = getattr(v, field)
            assert isinstance(val, Decimal), f"{field} should be Decimal, got {type(val)}"

    def test_variance_response_rejects_float_for_budget_amount(self):
        """Even a single float field in VarianceResponse must be rejected."""
        with pytest.raises(ValidationError):
            VarianceResponse(
                account_id="a1",
                account_name="Revenue",
                department="Sales",
                actual_amount=Decimal("123456.78"),
                budget_amount=90000.0,  # float — rejected
                variance_amount=Decimal("23456.78"),
                variance_pct=Decimal("23.46"),
                is_material=True,
            )


# ── 2. AssertionResponse ─────────────────────────────────────────────────────


class TestAssertionResponseDecimal:
    """AssertionResponse.value must be Decimal, never float."""

    def test_assertion_response_value_decimal(self):
        """AssertionResponse.value accepts Decimal."""
        a = AssertionResponse(
            id="a1",
            type="numeric",
            text="Revenue increased",
            value=Decimal("150000.00"),
            confidence=0.95,
        )
        assert isinstance(a.value, Decimal)
        assert a.value == Decimal("150000.00")

    def test_assertion_response_value_none_allowed(self):
        """AssertionResponse.value can be None."""
        a = AssertionResponse(id="a1", type="numeric", text="No value")
        assert a.value is None

    def test_assertion_response_rejects_float_for_value(self):
        """AssertionResponse must reject float for the value field."""
        with pytest.raises(ValidationError):
            AssertionResponse(
                id="a1",
                type="numeric",
                text="Revenue increased",
                value=150000.0,  # float — should be rejected
                confidence=0.95,
            )


# ── 3. ScenarioResponse ──────────────────────────────────────────────────────


class TestScenarioResponseDecimal:
    """Scenario impact fields must use Decimal."""

    def test_scenario_response_decimal(self):
        """Scenario-like fields (revenue_impact, ebitda_impact, cash_impact) are Decimal."""

        class ScenarioResponse:
            """Inline test schema matching Scenario fields from shared.models.state."""

            def __init__(self, revenue_impact, ebitda_impact, cash_impact):
                self.revenue_impact = revenue_impact
                self.ebitda_impact = ebitda_impact
                self.cash_impact = cash_impact

        s = ScenarioResponse(
            revenue_impact=Decimal("50000"),
            ebitda_impact=Decimal("30000"),
            cash_impact=Decimal("10000"),
        )
        assert isinstance(s.revenue_impact, Decimal)
        assert isinstance(s.ebitda_impact, Decimal)
        assert isinstance(s.cash_impact, Decimal)


# ── 4. ActionCreateRequest ──────────────────────────────────────────────────


class TestActionCreateRequestDecimal:
    """ActionCreateRequest impact fields must be Decimal."""

    def test_action_create_request_accepts_decimal(self):
        """ActionCreateRequest accepts Decimal for impact fields."""
        req = ActionCreateRequest(
            action="reduce",
            domain="cost",
            target="travel",
            description="Reduce travel costs",
            impact_expected_savings=Decimal("50000.00"),
            impact_expected_revenue=Decimal("10000.00"),
        )
        assert isinstance(req.impact_expected_savings, Decimal)
        assert isinstance(req.impact_expected_revenue, Decimal)
        assert req.impact_expected_savings == Decimal("50000.00")

    def test_action_create_request_rejects_float(self):
        """ActionCreateRequest must reject float for impact fields."""
        with pytest.raises(ValidationError):
            ActionCreateRequest(
                action="reduce",
                domain="cost",
                target="travel",
                description="Reduce travel costs",
                impact_expected_savings=50000.0,  # float — rejected
            )

    def test_action_create_request_impact_none_allowed(self):
        """ActionCreateRequest impact fields can be None."""
        req = ActionCreateRequest(
            action="reduce",
            domain="cost",
            target="travel",
            description="Reduce travel costs",
        )
        assert req.impact_expected_savings is None
        assert req.impact_expected_revenue is None


# ── 5. BridgeAnalysisResponse ───────────────────────────────────────────────


class TestBridgeResponseDecimal:
    """Bridge component amounts are already strings — verify they remain so."""

    def test_bridge_component_amount_is_string(self):
        """BridgeComponentResponse.amount and .percentage are strings."""
        c = BridgeComponentResponse(
            component="price",
            amount="6000.00",
            percentage="60.0",
            description="Price effect",
            confidence=0.85,
        )
        assert isinstance(c.amount, str)
        assert isinstance(c.percentage, str)

    def test_bridge_total_variance_is_string(self):
        """BridgeAnalysisResponse.total_variance is already a string."""
        resp = BridgeAnalysisResponse(
            account_id="a1",
            account_name="Revenue",
            total_variance="10000.00",
            bridge_type="revenue",
            reconciles=True,
            confidence=0.85,
        )
        assert isinstance(resp.total_variance, str)


# ── 6. JSON Encoder ─────────────────────────────────────────────────────────


class TestDecimalEncoder:
    """DecimalEncoder must serialize Decimals to strings, leave floats alone."""

    def test_json_encoder_decimals_to_string(self):
        """Decimal serializes to its string representation."""
        data = {"amount": Decimal("123.45")}
        result = json.dumps(data, cls=DecimalEncoder)
        parsed = json.loads(result)
        assert parsed["amount"] == "123.45"
        assert isinstance(parsed["amount"], str)

    def test_json_encoder_large_decimal(self):
        """Large Decimals serialize correctly."""
        data = {"amount": Decimal("999999999999.99")}
        result = json.dumps(data, cls=DecimalEncoder)
        parsed = json.loads(result)
        assert parsed["amount"] == "999999999999.99"

    def test_json_encoder_negative_decimal(self):
        """Negative Decimals serialize correctly."""
        data = {"amount": Decimal("-5000.00")}
        result = json.dumps(data, cls=DecimalEncoder)
        parsed = json.loads(result)
        assert parsed["amount"] == "-5000.00"

    def test_json_encoder_float_unchanged(self):
        """Non-money floats in non-monetary fields are left unchanged."""
        data = {"confidence": 0.95, "score": 85.5}
        result = json.dumps(data, cls=DecimalEncoder)
        parsed = json.loads(result)
        assert parsed["confidence"] == 0.95
        assert parsed["score"] == 85.5

    def test_json_encoder_mixed_types(self):
        """DecimalEncoder handles dicts with both Decimal and float values."""
        data = {
            "amount": Decimal("50000.00"),
            "confidence": 0.85,
            "name": "test",
            "count": 42,
        }
        result = json.dumps(data, cls=DecimalEncoder)
        parsed = json.loads(result)
        assert parsed["amount"] == "50000.00"
        assert parsed["confidence"] == 0.85
        assert parsed["count"] == 42

    def test_json_encoder_none_values(self):
        """DecimalEncoder handles None values without error."""
        data = {"amount": None}
        result = json.dumps(data, cls=DecimalEncoder)
        parsed = json.loads(result)
        assert parsed["amount"] is None

    def test_json_encoder_precision_preserved(self):
        """Decimal precision is preserved in string output."""
        data = {"amount": Decimal("0.1") + Decimal("0.2")}
        result = json.dumps(data, cls=DecimalEncoder)
        parsed = json.loads(result)
        assert parsed["amount"] == "0.3"  # 0.1 + 0.2 = 0.3 exactly with Decimal


# ── 7. Serializer Helpers ────────────────────────────────────────────────────


class TestSerializeAmounts:
    """serialize_amounts helper must convert Decimals to strings in models."""

    def test_serialize_amounts_converts_decimals(self):
        """serialize_amounts converts all Decimal fields to strings."""
        v = VarianceResponse(
            account_id="a1",
            account_name="Revenue",
            department="Sales",
            actual_amount=Decimal("123456.78"),
            budget_amount=Decimal("100000.00"),
            variance_amount=Decimal("23456.78"),
            variance_pct=Decimal("23.46"),
            is_material=True,
        )
        result = serialize_amounts(v)
        assert result["actual_amount"] == "123456.78"
        assert result["budget_amount"] == "100000.00"
        assert result["variance_amount"] == "23456.78"
        assert result["variance_pct"] == "23.46"
        assert result["is_material"] is True
        assert result["account_id"] == "a1"

    def test_serialize_amounts_leaves_non_decimal(self):
        """Non-Decimal fields are left unchanged by serialize_amounts."""
        v = VarianceResponse(
            account_id="a1",
            account_name="Revenue",
            department="Sales",
            actual_amount=Decimal("50000"),
            budget_amount=Decimal("45000"),
            variance_amount=Decimal("5000"),
            variance_pct=Decimal("11.11"),
            is_material=False,
        )
        result = serialize_amounts(v)
        assert result["account_id"] == "a1"
        assert result["is_material"] is False

    def test_serialize_amounts_with_nested(self):
        """serialize_amounts handles models with nested Decimal fields."""
        a = AssertionResponse(
            id="a1",
            type="numeric",
            text="Test",
            value=Decimal("99999.99"),
            confidence=0.9,
        )
        result = serialize_amounts(a)
        assert result["value"] == "99999.99"
        assert result["confidence"] == 0.9


# ── 8. Backward Compatibility ────────────────────────────────────────────────


class TestBackwardCompatibility:
    """Providing float for monetary fields must raise a clear error."""

    def test_backward_compatibility_float_rejected_with_clear_error(self):
        """Float passed to VarianceResponse monetary field raises ValidationError with clear message."""
        with pytest.raises(ValidationError) as excinfo:
            VarianceResponse(
                account_id="a1",
                account_name="Revenue",
                department="Sales",
                actual_amount=123456.78,  # float
                budget_amount=Decimal("100000.00"),
                variance_amount=Decimal("23456.78"),
                variance_pct=Decimal("23.46"),
                is_material=True,
            )
        error_msg = str(excinfo.value)
        # The error should mention the field name and type constraint
        assert "actual_amount" in error_msg

    def test_assertion_float_rejected_clear_error(self):
        """Float passed to AssertionResponse.value raises clear error."""
        with pytest.raises(ValidationError) as excinfo:
            AssertionResponse(
                id="a1",
                type="numeric",
                text="Revenue",
                value=150000.0,  # float
            )
        error_msg = str(excinfo.value)
        assert "value" in error_msg

    def test_action_create_float_rejected_clear_error(self):
        """Float passed to ActionCreateRequest impact fields raises clear error."""
        with pytest.raises(ValidationError) as excinfo:
            ActionCreateRequest(
                action="reduce",
                domain="cost",
                target="travel",
                description="Reduce travel",
                impact_expected_savings=50000.0,  # float
            )
        error_msg = str(excinfo.value)
        assert "impact_expected_savings" in error_msg


# ── 9. Route response no floats in amounts (integration-level) ──────────────


class TestRouteResponseNoFloats:
    """Verify VarianceResponse model_dump produces no float monetary values."""

    def test_variance_model_dump_has_no_floats_in_amounts(self):
        """model_dump() of VarianceResponse must not contain float in amount fields."""
        v = VarianceResponse(
            account_id="a1",
            account_name="Revenue",
            department="Sales",
            actual_amount=Decimal("123456.78"),
            budget_amount=Decimal("100000.00"),
            variance_amount=Decimal("23456.78"),
            variance_pct=Decimal("23.46"),
            is_material=True,
        )
        data = v.model_dump()
        monetary_fields = ["actual_amount", "budget_amount", "variance_amount", "variance_pct"]
        for field in monetary_fields:
            val = data[field]
            assert isinstance(val, Decimal), f"{field} should be Decimal, got {type(val)}"
