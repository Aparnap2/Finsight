"""Tests for deterministic bridge analysis engine."""

from decimal import Decimal
import pytest

from backend.engine.bridge_analysis import (
    BridgeAnalysis,
    BridgeComponent,
    BridgeDecomposition,
    BridgeType,
    build_bridge_assertions,
    decompose_bridge,
    decompose_cost_bridge,
    decompose_revenue_bridge,
)
from backend.models.assertions import Assertion, AssertionType, SupportLevel


# ---------------------------------------------------------------------------
# Revenue bridge tests
# ---------------------------------------------------------------------------


class TestRevenueBridgeWithVolumeData:
    def test_exact_decomposition(self):
        """With volume data, price/volume/mix should sum to total variance."""
        result = decompose_revenue_bridge(
            account_id="4000",
            account_name="Revenue - Product X",
            current_actual=Decimal("500000"),
            prior_actual=Decimal("450000"),
            budget=Decimal("480000"),
            volume_current=Decimal("1000"),
            volume_prior=Decimal("900"),
        )
        assert result.bridge_type == BridgeType.REVENUE
        assert result.total_variance == Decimal("20000")
        assert result.reconciles is True
        assert result.reconciliation_diff == Decimal("0")
        # Should have price, volume, mix components
        comp_names = [c.component.value for c in result.components]
        assert "price" in comp_names
        assert "volume" in comp_names
        assert "mix" in comp_names

    def test_with_zero_volume_prior(self):
        """Budget price should be 0 when volume_prior is 0."""
        result = decompose_revenue_bridge(
            account_id="4001",
            account_name="Revenue - Product Y",
            current_actual=Decimal("100000"),
            prior_actual=Decimal("0"),
            budget=Decimal("100000"),
            volume_current=Decimal("500"),
            volume_prior=Decimal("0"),
        )
        assert result.total_variance == Decimal("0")
        assert result.components == []
        assert result.confidence == 1.0


class TestRevenueBridgeWithoutVolumeHeuristic:
    def test_heuristic_split(self):
        """Without volume data, heuristic split should apply 60/25/15."""
        result = decompose_revenue_bridge(
            account_id="4002",
            account_name="Revenue - Services",
            current_actual=Decimal("300000"),
            prior_actual=Decimal("280000"),
            budget=Decimal("250000"),
        )
        assert result.total_variance == Decimal("50000")
        # Heuristic: 60% price, 25% volume, 15% mix
        prices = [c for c in result.components if c.component == BridgeComponent.PRICE]
        assert len(prices) == 1
        assert prices[0].amount == Decimal("30000.00")
        assert prices[0].confidence == 0.6  # no volume data

    def test_reconciles(self):
        """Heuristic split should reconcile (sum of parts = total)."""
        result = decompose_revenue_bridge(
            account_id="4002",
            account_name="Revenue - Services",
            current_actual=Decimal("300000"),
            prior_actual=Decimal("280000"),
            budget=Decimal("250000"),
        )
        assert result.reconciles is True


class TestRevenueBridgeWithFx:
    def test_fx_effect(self):
        """FX effect should be computed when rates differ."""
        result = decompose_revenue_bridge(
            account_id="4000",
            account_name="Revenue - Product X",
            current_actual=Decimal("500000"),
            prior_actual=Decimal("450000"),
            budget=Decimal("480000"),
            fx_rate_current=Decimal("1.10"),
            fx_rate_prior=Decimal("1.05"),
        )
        fx_comps = [c for c in result.components if c.component == BridgeComponent.FX]
        assert len(fx_comps) == 1
        assert fx_comps[0].confidence == 0.9
        assert result.reconciles is True

    def test_same_fx_rate_no_effect(self):
        """Same FX rate should produce no FX component."""
        result = decompose_revenue_bridge(
            account_id="4000",
            account_name="Revenue - Product X",
            current_actual=Decimal("500000"),
            prior_actual=Decimal("450000"),
            budget=Decimal("480000"),
            fx_rate_current=Decimal("1.05"),
            fx_rate_prior=Decimal("1.05"),
        )
        fx_comps = [c for c in result.components if c.component == BridgeComponent.FX]
        assert len(fx_comps) == 0


class TestRevenueBridgeZeroVariance:
    def test_zero_variance(self):
        """Zero variance should return empty components with confidence 1.0."""
        result = decompose_revenue_bridge(
            account_id="4000",
            account_name="Revenue - Product X",
            current_actual=Decimal("500000"),
            prior_actual=Decimal("450000"),
            budget=Decimal("500000"),
        )
        assert result.total_variance == Decimal("0")
        assert result.components == []
        assert result.confidence == 1.0
        assert result.reconciles is True


# ---------------------------------------------------------------------------
# Cost bridge tests
# ---------------------------------------------------------------------------


class TestCostBridgeOneTime:
    def test_one_time_flag(self):
        """When is_one_time is True, 100% goes to ONE_TIME."""
        result = decompose_cost_bridge(
            account_id="8002",
            account_name="Legal & Accounting",
            current_actual=Decimal("150000"),
            prior_actual=Decimal("50000"),
            budget=Decimal("60000"),
            is_one_time=True,
        )
        assert result.bridge_type == BridgeType.COST
        assert result.total_variance == Decimal("90000")
        assert len(result.components) == 1
        assert result.components[0].component == BridgeComponent.ONE_TIME
        assert result.components[0].amount == Decimal("90000")
        assert result.components[0].confidence == 0.85
        assert result.reconciles is True


class TestCostBridgeTiming:
    def test_timing_flag(self):
        """When timing_shift is True, 100% goes to TIMING."""
        result = decompose_cost_bridge(
            account_id="7002",
            account_name="Marketing Campaigns",
            current_actual=Decimal("80000"),
            prior_actual=Decimal("70000"),
            budget=Decimal("75000"),
            timing_shift=True,
        )
        assert result.total_variance == Decimal("5000")
        assert len(result.components) == 1
        assert result.components[0].component == BridgeComponent.TIMING
        assert result.reconciles is True


class TestCostBridgeScope:
    def test_scope_flag(self):
        """When scope_changed is True, 100% goes to SCOPE."""
        result = decompose_cost_bridge(
            account_id="6002",
            account_name="Engineering Salaries",
            current_actual=Decimal("200000"),
            prior_actual=Decimal("180000"),
            budget=Decimal("170000"),
            scope_changed=True,
        )
        assert result.total_variance == Decimal("30000")
        assert len(result.components) == 1
        assert result.components[0].component == BridgeComponent.SCOPE
        assert result.reconciles is True


class TestCostBridgeHeuristic:
    def test_heuristic_split(self):
        """Without flags, heuristic split 20/20/30/30 applies."""
        result = decompose_cost_bridge(
            account_id="7000",
            account_name="Cloud Infrastructure",
            current_actual=Decimal("135000"),
            prior_actual=Decimal("100000"),
            budget=Decimal("100000"),
        )
        assert result.total_variance == Decimal("35000")
        comp_map = {c.component.value: c.amount for c in result.components}
        assert comp_map["one_time"] == Decimal("7000.00")
        assert comp_map["timing"] == Decimal("7000.00")
        assert comp_map["scope"] == Decimal("10500.00")
        assert comp_map["rate"] == Decimal("10500.00")
        assert result.reconciles is True

    def test_degraded_mode_when_no_flags(self):
        """Heuristic mode should include INSUFFICIENT_CAUSAL_EVIDENCE."""
        result = decompose_cost_bridge(
            account_id="7000",
            account_name="Cloud Infrastructure",
            current_actual=Decimal("135000"),
            prior_actual=Decimal("100000"),
            budget=Decimal("100000"),
        )
        assert "insufficient_causal_evidence" in (result.degraded_modes or [])


class TestCostBridgeZeroVariance:
    def test_zero_variance(self):
        """Zero variance should return empty components."""
        result = decompose_cost_bridge(
            account_id="7000",
            account_name="Cloud Infrastructure",
            current_actual=Decimal("100000"),
            prior_actual=Decimal("100000"),
            budget=Decimal("100000"),
        )
        assert result.total_variance == Decimal("0")
        assert result.components == []
        assert result.confidence == 1.0


# ---------------------------------------------------------------------------
# Routing tests
# ---------------------------------------------------------------------------


class TestDecomposeBridgeRouting:
    def test_routes_to_revenue(self):
        """'revenue' account_type should use revenue decomposition."""
        result = decompose_bridge(
            account_id="4000",
            account_name="Revenue - Product X",
            current_actual=Decimal("500000"),
            prior_actual=Decimal("450000"),
            budget=Decimal("480000"),
            account_type="revenue",
        )
        assert result.bridge_type == BridgeType.REVENUE

    def test_routes_to_cost(self):
        """'expense' account_type should use cost decomposition."""
        result = decompose_bridge(
            account_id="7000",
            account_name="Cloud Infrastructure",
            current_actual=Decimal("135000"),
            prior_actual=Decimal("100000"),
            budget=Decimal("100000"),
            account_type="expense",
        )
        assert result.bridge_type == BridgeType.COST

    def test_routes_sales_to_revenue(self):
        """'sales' should also route to revenue."""
        result = decompose_bridge(
            account_id="4000",
            account_name="Revenue",
            current_actual=Decimal("500000"),
            prior_actual=Decimal("450000"),
            budget=Decimal("480000"),
            account_type="sales",
        )
        assert result.bridge_type == BridgeType.REVENUE


# ---------------------------------------------------------------------------
# Reconciliation tests
# ---------------------------------------------------------------------------


class TestBridgeReconciliation:
    def test_reconciliation_diff(self):
        """Reconciliation diff should equal total_variance - sum(components)."""
        result = decompose_revenue_bridge(
            account_id="4000",
            account_name="Revenue - Product X",
            current_actual=Decimal("500000"),
            prior_actual=Decimal("450000"),
            budget=Decimal("480000"),
            volume_current=Decimal("1000"),
            volume_prior=Decimal("900"),
        )
        sum_components = sum(c.amount for c in result.components)
        expected_diff = (result.total_variance - sum_components).quantize(Decimal("0.01"))
        assert result.reconciliation_diff == expected_diff


# ---------------------------------------------------------------------------
# Assertion builder tests
# ---------------------------------------------------------------------------


class TestBuildBridgeAssertions:
    def test_builds_assertions(self):
        """Should produce one total + one per component assertion."""
        analysis = decompose_revenue_bridge(
            account_id="4000",
            account_name="Revenue - Product X",
            current_actual=Decimal("500000"),
            prior_actual=Decimal("450000"),
            budget=Decimal("480000"),
        )
        assertions = build_bridge_assertions(analysis)
        # 1 total + 3 components (price/volume/mix)
        assert len(assertions) == 4
        assert assertions[0].type == AssertionType.NUMERIC
        assert assertions[0].support_level == SupportLevel.VERIFIED

    def test_component_assertion_ids(self):
        """Component assertions should have predictable IDs."""
        analysis = decompose_cost_bridge(
            account_id="7000",
            account_name="Cloud Infrastructure",
            current_actual=Decimal("135000"),
            prior_actual=Decimal("100000"),
            budget=Decimal("100000"),
        )
        assertions = build_bridge_assertions(analysis)
        ids = [a.id for a in assertions]
        assert "bridge_7000_total" in ids
        assert "bridge_7000_one_time" in ids
        assert "bridge_7000_timing" in ids
        assert "bridge_7000_scope" in ids
        assert "bridge_7000_rate" in ids


# ---------------------------------------------------------------------------
# Property / utility tests
# ---------------------------------------------------------------------------


class TestLargestComponent:
    def test_largest_component(self):
        """largest_component should return the one with max abs(amount)."""
        analysis = decompose_cost_bridge(
            account_id="7000",
            account_name="Cloud Infrastructure",
            current_actual=Decimal("135000"),
            prior_actual=Decimal("100000"),
            budget=Decimal("100000"),
        )
        largest = analysis.largest_component
        assert largest is not None
        assert largest.component == BridgeComponent.SCOPE  # 30% = 10500, rate = 10500

    def test_largest_component_empty(self):
        """Empty components should return None."""
        analysis = decompose_cost_bridge(
            account_id="7000",
            account_name="Cloud Infrastructure",
            current_actual=Decimal("100000"),
            prior_actual=Decimal("100000"),
            budget=Decimal("100000"),
        )
        assert analysis.largest_component is None


class TestBridgeToDict:
    def test_to_dict_roundtrip(self):
        """to_dict should produce a serializable dict with all fields."""
        analysis = decompose_revenue_bridge(
            account_id="4000",
            account_name="Revenue - Product X",
            current_actual=Decimal("500000"),
            prior_actual=Decimal("450000"),
            budget=Decimal("480000"),
        )
        d = analysis.to_dict()
        assert d["account_id"] == "4000"
        assert d["bridge_type"] == "revenue"
        assert isinstance(d["components"], list)
        assert "reconciles" in d
        assert "confidence" in d
        assert "degraded_modes" in d

    def test_component_to_dict(self):
        """BridgeDecomposition.to_dict should serialize correctly."""
        comp = BridgeDecomposition(
            component=BridgeComponent.PRICE,
            amount=Decimal("10000.50"),
            percentage=Decimal("45.23"),
            description="Price effect",
            confidence=0.85,
        )
        d = comp.to_dict()
        assert d["component"] == "price"
        assert d["amount"] == "10000.50"
        assert d["percentage"] == "45.23"
        assert d["confidence"] == 0.85


class TestComponentAmounts:
    def test_component_amounts_property(self):
        """component_amounts should map component name -> amount."""
        analysis = decompose_cost_bridge(
            account_id="7000",
            account_name="Cloud Infrastructure",
            current_actual=Decimal("135000"),
            prior_actual=Decimal("100000"),
            budget=Decimal("100000"),
        )
        amounts = analysis.component_amounts
        assert "one_time" in amounts
        assert amounts["one_time"] == Decimal("7000.00")
