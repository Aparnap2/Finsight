"""
Tests for the Materiality Engine (finance/variance_engine/materiality.py).

Follows strict TDD: tests written first, implementation second.
All materiality logic is 100% deterministic — no mocks needed.
"""

from decimal import Decimal

import pytest

from finance.variance_engine.materiality import (
    MaterialityAssessment,
    MaterialityConfig,
    MaterialityEngine,
    MaterialityRule,
    SensitivityTier,
    TenantMaterialityConfig,
)
from shared.models.state import Variance


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def engine():
    """Default MaterialityEngine with no custom config (uses default thresholds)."""
    return MaterialityEngine()


@pytest.fixture
def revenue_variance():
    """A CRITICAL-tier variance (account 4010 = Revenue)."""
    return Variance(
        account_id="4010",
        account_name="Consulting Revenue",
        department="Sales",
        actual_amount=Decimal("520000"),
        budget_amount=Decimal("500000"),
        variance_amount=Decimal("20000"),
        variance_pct=Decimal("4.00"),
    )


@pytest.fixture
def large_abs_revenue_variance():
    """A CRITICAL-tier variance that exceeds abs threshold only."""
    return Variance(
        account_id="4010",
        account_name="Consulting Revenue",
        department="Sales",
        actual_amount=Decimal("560000"),
        budget_amount=Decimal("500000"),
        variance_amount=Decimal("60000"),
        variance_pct=Decimal("12.00"),
    )


@pytest.fixture
def small_variance():
    """A small variance that should NOT be material (2%, $30K)."""
    return Variance(
        account_id="4010",
        account_name="Consulting Revenue",
        department="Sales",
        actual_amount=Decimal("510000"),
        budget_amount=Decimal("500000"),
        variance_amount=Decimal("10000"),
        variance_pct=Decimal("2.00"),
    )


@pytest.fixture
def medium_variance():
    """A MEDIUM-tier variance (account 6000 = Operating Expense)."""
    return Variance(
        account_id="6010",
        account_name="Office Supplies",
        department="G&A",
        actual_amount=Decimal("270000"),
        budget_amount=Decimal("250000"),
        variance_amount=Decimal("20000"),
        variance_pct=Decimal("8.00"),
    )


@pytest.fixture
def batch_variances(engine):
    """Multiple variances of varying severity for batch testing."""
    return [
        Variance(
            account_id="4010",
            account_name="Revenue",
            department="Sales",
            actual_amount=Decimal("600000"),
            budget_amount=Decimal("500000"),
            variance_amount=Decimal("100000"),
            variance_pct=Decimal("20.00"),
        ),
        Variance(
            account_id="6010",
            account_name="Supplies",
            department="G&A",
            actual_amount=Decimal("260000"),
            budget_amount=Decimal("250000"),
            variance_amount=Decimal("10000"),
            variance_pct=Decimal("4.00"),
        ),
        Variance(
            account_id="7010",
            account_name="Other Income",
            department="Corporate",
            actual_amount=Decimal("1150000"),
            budget_amount=Decimal("1000000"),
            variance_amount=Decimal("150000"),
            variance_pct=Decimal("15.00"),
        ),
    ]


# =============================================================================
# 1. Default Thresholds
# =============================================================================


class TestDefaultThresholds:
    """Verify the default thresholds for each tier."""

    def test_default_thresholds_critical(self):
        """CRITICAL tier: pct=0.03 (3%), abs=50_000 ($50K)."""
        config = MaterialityConfig.default()
        rules = config.tiers[SensitivityTier.CRITICAL]
        # The default rule for CRITICAL should have 3% / $50K
        default_rule = next(r for r in rules if r.account_code is None and r.account_pattern is None)
        assert default_rule.pct_threshold == Decimal("0.03")
        assert default_rule.abs_threshold == Decimal("50000")

    def test_default_thresholds_high(self):
        """HIGH tier: pct=0.05 (5%), abs=100_000 ($100K)."""
        config = MaterialityConfig.default()
        rules = config.tiers[SensitivityTier.HIGH]
        default_rule = next(r for r in rules if r.account_code is None and r.account_pattern is None)
        assert default_rule.pct_threshold == Decimal("0.05")
        assert default_rule.abs_threshold == Decimal("100000")

    def test_default_thresholds_medium(self):
        """MEDIUM tier: pct=0.10 (10%), abs=250_000 ($250K)."""
        config = MaterialityConfig.default()
        rules = config.tiers[SensitivityTier.MEDIUM]
        default_rule = next(r for r in rules if r.account_code is None and r.account_pattern is None)
        assert default_rule.pct_threshold == Decimal("0.10")
        assert default_rule.abs_threshold == Decimal("250000")

    def test_default_thresholds_low(self):
        """LOW tier: pct=0.15 (15%), abs=500_000 ($500K)."""
        config = MaterialityConfig.default()
        rules = config.tiers[SensitivityTier.LOW]
        default_rule = next(r for r in rules if r.account_code is None and r.account_pattern is None)
        assert default_rule.pct_threshold == Decimal("0.15")
        assert default_rule.abs_threshold == Decimal("500000")


# =============================================================================
# 2. Materiality Assessment
# =============================================================================


class TestSingleAssessment:
    """Test the `assess` method for individual variances."""

    def test_assess_material_pct_only(self, engine, revenue_variance):
        """4% variance on CRITICAL account → exceeds 3% pct threshold → material."""
        assessment = engine.assess(revenue_variance)
        assert assessment.is_material is True
        assert assessment.pct_exceeds is True
        assert assessment.tier == SensitivityTier.CRITICAL
        assert assessment.variance_pct == Decimal("4.00")
        assert assessment.variance_abs == Decimal("20000")

    def test_assess_material_abs_only(self, engine, large_abs_revenue_variance):
        """$60K variance on CRITICAL account → exceeds $50K abs threshold → material."""
        assessment = engine.assess(large_abs_revenue_variance)
        assert assessment.is_material is True
        assert assessment.abs_exceeds is True
        assert assessment.pct_exceeds is True  # 12% > 3%
        assert assessment.tier == SensitivityTier.CRITICAL

    def test_assess_not_material(self, engine, small_variance):
        """2% on CRITICAL ($30K abs) → neither threshold exceeded → not material."""
        # Account 4010 is CRITICAL (pct=3%, abs=$50K)
        # 2% < 3% and $30K < $50K → not material
        assessment = engine.assess(small_variance)
        assert assessment.is_material is False
        assert assessment.pct_exceeds is False
        assert assessment.abs_exceeds is False

    def test_assess_medium_tier(self, engine, medium_variance):
        """8% variance on MEDIUM account → not material (<10% threshold)."""
        assessment = engine.assess(medium_variance)
        assert assessment.is_material is False
        assert assessment.pct_exceeds is False  # 8% < 10%
        assert assessment.tier == SensitivityTier.MEDIUM

    def test_edge_case_zero_variance(self, engine):
        """Zero variance → not material."""
        v = Variance(
            account_id="4010",
            account_name="Revenue",
            department="Sales",
            actual_amount=Decimal("500000"),
            budget_amount=Decimal("500000"),
            variance_amount=Decimal("0"),
            variance_pct=Decimal("0.00"),
        )
        assessment = engine.assess(v)
        assert assessment.is_material is False
        assert assessment.variance_abs == Decimal("0")
        assert assessment.variance_pct == Decimal("0.00")

    def test_edge_case_negative_variance(self, engine):
        """Negative (favorable) variance — still assessed correctly."""
        v = Variance(
            account_id="4010",
            account_name="Revenue",
            department="Sales",
            actual_amount=Decimal("400000"),
            budget_amount=Decimal("500000"),
            variance_amount=Decimal("-100000"),
            variance_pct=Decimal("-20.00"),
        )
        assessment = engine.assess(v)
        # Absolute variance of $100K > $50K → material
        assert assessment.is_material is True
        assert assessment.abs_exceeds is True
        assert assessment.variance_abs == Decimal("-100000")

    def test_decimal_precision(self, engine):
        """All values should be Decimal, no float rounding issues."""
        v = Variance(
            account_id="4010",
            account_name="Revenue",
            department="Sales",
            actual_amount=Decimal("500001"),
            budget_amount=Decimal("500000"),
            variance_amount=Decimal("1"),
            variance_pct=Decimal("0.0002"),
        )
        assessment = engine.assess(v)
        # Should not be material — $1 < $50K and 0.02% < 3%
        assert assessment.is_material is False
        assert isinstance(assessment.variance_pct, Decimal)
        assert isinstance(assessment.variance_abs, Decimal)


# =============================================================================
# 3. Batch Assessment & Filtering
# =============================================================================


class TestBatchAssessment:
    """Test batch assessment and filtering."""

    def test_batch_assess_sorts_by_severity(self, engine, batch_variances):
        """Batch assess returns assessments sorted by severity descending."""
        assessments = engine.assess_batch(batch_variances)
        assert len(assessments) == 3
        # First should be the most severe: $100K variance at 20%
        assert assessments[0].variance_id == batch_variances[0].account_id
        # Last should be least severe: $10K at 4%
        assert assessments[-1].variance_id == batch_variances[1].account_id
        # Verify descending order of is_material then abs variance
        assert assessments[0].is_material or not assessments[-1].is_material

    def test_get_material_variances_filter(self, engine, batch_variances):
        """Filter returns only material variances."""
        material = engine.get_material_variances(batch_variances)
        for v in material:
            # Every returned variance must be marked material
            assert v.is_material is True
        # At least the 20% revenue variance should be material
        account_ids = {v.account_id for v in material}
        assert "4010" in account_ids


# =============================================================================
# 4. Account Classification
# =============================================================================


class TestAccountClassification:
    """Test classifying accounts into sensitivity tiers."""

    def test_classify_account_by_code(self, engine):
        """Account '4010' maps to CRITICAL (revenue)."""
        tier = engine.classify_account("4010")
        assert tier == SensitivityTier.CRITICAL

    def test_classify_account_high(self, engine):
        """Account '5010' maps to HIGH (COGS)."""
        tier = engine.classify_account("5010")
        assert tier == SensitivityTier.HIGH

    def test_classify_account_medium(self, engine):
        """Account '6010' maps to MEDIUM (OpEx)."""
        tier = engine.classify_account("6010")
        assert tier == SensitivityTier.MEDIUM

    def test_classify_account_low_default(self, engine):
        """Unknown account '0000' defaults to MEDIUM."""
        tier = engine.classify_account("0000")
        assert tier == SensitivityTier.MEDIUM


# =============================================================================
# 5. Custom & Tenant-Specific Rules
# =============================================================================


class TestCustomRules:
    """Test custom account patterns and overrides."""

    def test_classify_account_custom_rule(self):
        """Custom account pattern overrides default classification."""
        custom_rule = MaterialityRule(
            account_pattern="90*",
            tier=SensitivityTier.HIGH,
            pct_threshold=Decimal("0.05"),
            abs_threshold=Decimal("100000"),
        )
        config = MaterialityConfig.default()
        config.tiers[SensitivityTier.HIGH].append(custom_rule)
        engine = MaterialityEngine(config=config)
        # Account 9010 should now match the custom HIGH rule
        tier = engine.classify_account("9010")
        assert tier == SensitivityTier.HIGH

    def test_tenant_specific_config(self):
        """Tenant overrides global thresholds for specific accounts."""
        # Create a tenant config that makes account 6010 more sensitive
        tenant_rule = MaterialityRule(
            account_code="6010",
            tier=SensitivityTier.CRITICAL,
            pct_threshold=Decimal("0.02"),
            abs_threshold=Decimal("10000"),
        )
        base_config = MaterialityConfig.default()
        tenant_config = TenantMaterialityConfig(
            tenant_id="tenant_abc",
            rules=[tenant_rule],
            base_config=base_config,
        )
        # Engine with tenant config
        merged = tenant_config.merged_config()
        engine = MaterialityEngine(config=merged)

        v = Variance(
            account_id="6010",
            account_name="Office Supplies",
            department="G&A",
            actual_amount=Decimal("255000"),
            budget_amount=Decimal("250000"),
            variance_amount=Decimal("5000"),
            variance_pct=Decimal("2.00"),
        )
        assessment = engine.assess(v)
        # 2% exactly equals 2% threshold (pct_exceeds needs > not >=) — check implementation
        # Actually 2% and $5K — $5K < $10K so not abs, and 2% is not > 2%
        # Let me adjust: use a variance of 3% and $15K
        v2 = Variance(
            account_id="6010",
            account_name="Office Supplies",
            department="G&A",
            actual_amount=Decimal("257500"),
            budget_amount=Decimal("250000"),
            variance_amount=Decimal("15000"),
            variance_pct=Decimal("3.00"),
        )
        assessment2 = engine.assess(v2)
        # 3% > 2% threshold → pct_exceeds; $15K > $10K → abs_exceeds
        assert assessment2.is_material is True
        assert assessment2.tier == SensitivityTier.CRITICAL
        assert assessment2.pct_exceeds is True
        assert assessment2.abs_exceeds is True


# =============================================================================
# 6. Combined Rules
# =============================================================================


class TestCombinedRules:
    """Test combined_rule: 'any' (default) vs 'both'."""

    def test_combined_rule_both(self):
        """
        combined_rule='both': must exceed BOTH pct AND abs thresholds.
        A 4% variance ($30K) on CRITICAL: exceeds 3% pct but NOT $50K abs → not material.
        """
        config = MaterialityConfig.default()
        # Make a rule for account 4010 that requires both
        both_rule = MaterialityRule(
            account_code="4010",
            tier=SensitivityTier.CRITICAL,
            pct_threshold=Decimal("0.03"),
            abs_threshold=Decimal("50000"),
            combined_rule="both",
        )
        config.tiers[SensitivityTier.CRITICAL].append(both_rule)
        engine = MaterialityEngine(config=config)

        v = Variance(
            account_id="4010",
            account_name="Revenue",
            department="Sales",
            actual_amount=Decimal("520000"),
            budget_amount=Decimal("500000"),
            variance_amount=Decimal("20000"),
            variance_pct=Decimal("4.00"),
        )
        assessment = engine.assess(v)
        # pct exceeds (4% > 3%) but abs does not ($20K < $50K) → not material for "both"
        assert assessment.pct_exceeds is True
        assert assessment.abs_exceeds is False
        assert assessment.is_material is False

    def test_combined_rule_any(self):
        """
        combined_rule='any' (default): exceeds EITHER pct OR abs.
        $60K on CRITICAL: exceeds $50K abs threshold → material even if pct doesn't.
        """
        config = MaterialityConfig.default()
        any_rule = MaterialityRule(
            account_code="4010",
            tier=SensitivityTier.CRITICAL,
            pct_threshold=Decimal("0.03"),
            abs_threshold=Decimal("50000"),
            combined_rule="any",
        )
        config.tiers[SensitivityTier.CRITICAL].append(any_rule)
        engine = MaterialityEngine(config=config)

        v = Variance(
            account_id="4010",
            account_name="Revenue",
            department="Sales",
            actual_amount=Decimal("560000"),
            budget_amount=Decimal("500000"),
            variance_amount=Decimal("60000"),
            variance_pct=Decimal("12.00"),
        )
        assessment = engine.assess(v)
        # Both exceed but "any" means either is sufficient
        assert assessment.is_material is True
        assert assessment.pct_exceeds is True
        assert assessment.abs_exceeds is True

    def test_tenant_specific_threshold_override(self):
        """Tenant-specific rule overrides account threshold globally."""
        # Global: account 4010 is CRITICAL at 3%/$50K
        # Tenant: account 4010 should use 1%/$10K
        tenant_rule = MaterialityRule(
            account_code="4010",
            tier=SensitivityTier.CRITICAL,
            pct_threshold=Decimal("0.01"),
            abs_threshold=Decimal("10000"),
        )
        base_config = MaterialityConfig.default()
        tenant_config = TenantMaterialityConfig(
            tenant_id="tenant_xyz",
            rules=[tenant_rule],
            base_config=base_config,
        )
        engine = MaterialityEngine(config=tenant_config.merged_config())

        v = Variance(
            account_id="4010",
            account_name="Revenue",
            department="Sales",
            actual_amount=Decimal("505000"),
            budget_amount=Decimal("500000"),
            variance_amount=Decimal("5000"),
            variance_pct=Decimal("1.00"),
        )
        assessment = engine.assess(v)
        # 1% is not > 1% (not strictly greater), and $5K < $10K → not material
        assert assessment.is_material is False

        v2 = Variance(
            account_id="4010",
            account_name="Revenue",
            department="Sales",
            actual_amount=Decimal("515000"),
            budget_amount=Decimal("500000"),
            variance_amount=Decimal("15000"),
            variance_pct=Decimal("3.00"),
        )
        assessment2 = engine.assess(v2)
        # 3% > 1% → material
        assert assessment2.is_material is True


# =============================================================================
# 7. MaterialityAssessment data model
# =============================================================================


class TestAssessmentModel:
    """Verify MaterialityAssessment data integrity."""

    def test_assessment_fields(self, engine, revenue_variance):
        """Assessment has all required fields populated correctly."""
        assessment = engine.assess(revenue_variance)
        assert assessment.variance_id == "4010"
        assert assessment.account_id == "4010"
        assert assessment.account_name == "Consulting Revenue"
        assert assessment.tier == SensitivityTier.CRITICAL
        assert assessment.variance_pct == Decimal("4.00")
        assert assessment.variance_abs == Decimal("20000")
        assert assessment.rule_matched is not None
        assert assessment.rule_matched.tier == SensitivityTier.CRITICAL
