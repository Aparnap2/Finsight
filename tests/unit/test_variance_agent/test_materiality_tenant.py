"""Tests for tenant-aware materiality (``finance.variance_engine.materiality``).

Verifies that ``MaterialityEngine(tenant_config=...)`` derives thresholds
from the tenant's materiality config, that ``config`` and ``tenant_config``
are mutually exclusive, the ``SensitivityTier`` enum values, and the OR
(``combined_rule="any"``) semantics where either threshold crossing makes a
variance material.
"""

from decimal import Decimal

import pytest

from finance.variance_engine.materiality import (
    MaterialityConfig,
    MaterialityEngine,
    SensitivityTier,
)
from finplatform.config.tenant_schema import TenantConfig
from shared.models.state import Variance


def _acme_cfg() -> TenantConfig:
    """Load the acme-corp tenant config (materiality 5000 / 5%)."""
    return TenantConfig.load("acme-corp")


class TestSensitivityTier:
    """``SensitivityTier`` is a StrEnum with stable values."""

    def test_values(self) -> None:
        assert SensitivityTier.CRITICAL.value == "critical"
        assert SensitivityTier.HIGH.value == "high"
        assert SensitivityTier.MEDIUM.value == "medium"
        assert SensitivityTier.LOW.value == "low"

    def test_str_enum_is_a_str(self) -> None:
        assert isinstance(SensitivityTier.CRITICAL, str)
        assert str(SensitivityTier.CRITICAL) == "critical"


class TestConstructor:
    """``MaterialityEngine`` accepts exactly one of config / tenant_config."""

    def test_tenant_config_alone_is_allowed(self) -> None:
        engine = MaterialityEngine(tenant_config=_acme_cfg())
        assert engine.config is not None

    def test_config_and_tenant_config_raises(self) -> None:
        default_config = MaterialityConfig.default()
        with pytest.raises(ValueError, match="not both"):
            MaterialityEngine(config=default_config, tenant_config=_acme_cfg())


class TestTenantThresholds:
    """Tenant materiality overrides every rule's thresholds."""

    def test_acme_thresholds(self) -> None:
        engine = MaterialityEngine(tenant_config=_acme_cfg())
        for tier in SensitivityTier:
            for rule in engine.config.tiers[tier]:
                assert rule.abs_threshold == Decimal("5000")
                assert rule.pct_threshold == Decimal("0.05")
                assert rule.combined_rule == "any"

    def test_globex_thresholds(self) -> None:
        engine = MaterialityEngine(tenant_config=TenantConfig.load("globex"))
        critical_rule = engine.config.tiers[SensitivityTier.CRITICAL][0]
        assert critical_rule.abs_threshold == Decimal("25000")
        assert critical_rule.pct_threshold == Decimal("0.08")

    def test_initech_thresholds(self) -> None:
        engine = MaterialityEngine(tenant_config=TenantConfig.load("initech"))
        critical_rule = engine.config.tiers[SensitivityTier.CRITICAL][0]
        assert critical_rule.abs_threshold == Decimal("10000")
        assert critical_rule.pct_threshold == Decimal("0.06")


class TestOrSemantics:
    """Any threshold crossed (pct OR abs) marks a variance material."""

    def _variance(self, amount: str, pct: str) -> Variance:
        """Build a CRITICAL-tier revenue variance with the given delta."""
        return Variance(
            account_id="4010",
            account_name="Revenue",
            department="Sales",
            actual_amount=Decimal("500000"),
            budget_amount=Decimal("500000"),
            variance_amount=Decimal(amount),
            variance_pct=Decimal(pct),
        )

    def test_abs_only_exceeds_is_material(self) -> None:
        # $6000 > $5000 abs threshold; 2% < 5% pct threshold.
        engine = MaterialityEngine(tenant_config=_acme_cfg())
        assessment = engine.assess(self._variance("6000", "2.00"))
        assert assessment.abs_exceeds is True
        assert assessment.pct_exceeds is False
        assert assessment.is_material is True

    def test_pct_only_exceeds_is_material(self) -> None:
        # 6% > 5% pct threshold; $4000 < $5000 abs threshold.
        engine = MaterialityEngine(tenant_config=_acme_cfg())
        assessment = engine.assess(self._variance("4000", "6.00"))
        assert assessment.pct_exceeds is True
        assert assessment.abs_exceeds is False
        assert assessment.is_material is True

    def test_no_threshold_exceeded_not_material(self) -> None:
        # 2% < 5% and $4000 < $5000 → not material.
        engine = MaterialityEngine(tenant_config=_acme_cfg())
        assessment = engine.assess(self._variance("4000", "2.00"))
        assert assessment.pct_exceeds is False
        assert assessment.abs_exceeds is False
        assert assessment.is_material is False
