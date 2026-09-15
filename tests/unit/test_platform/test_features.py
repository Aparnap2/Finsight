"""Tests for the feature flag registry (``finplatform.config.features``).

Verifies per-tenant feature enablement, the sorted ``enabled_features``
output, ``validate`` warnings for features enabled without their
dependencies, and the ``rag`` → ``ml`` dependency resolution (``rag`` can
only be enabled when ``ml`` is also enabled).
"""

from decimal import Decimal

from finplatform.config.features import FEATURE_REGISTRY, KNOWN_FEATURES
from finplatform.config.tenant_schema import (
    ApprovalLimits,
    CompanyInfo,
    FeatureFlags,
    Materiality,
    TenantConfig,
)


def _tenant(features: dict[str, bool]) -> TenantConfig:
    """Build a minimal tenant config carrying only the given feature flags."""
    return TenantConfig(
        tenant_id="test",
        company=CompanyInfo(name="Test", legal_name="Test Ltd"),
        currency="USD",
        fiscal_year_start_month=1,
        materiality=Materiality(amount=Decimal("5000"), pct=Decimal("5")),
        approval_limits=ApprovalLimits(
            manager=Decimal("10000"),
            director=Decimal("50000"),
            cfo=Decimal("250000"),
        ),
        sox_enabled=False,
        connectors=[],
        features=FeatureFlags(**features),
    )


class TestIsEnabled:
    """Per-tenant feature enablement."""

    def test_acme_corp_enables_forecasting_rag_ml(self) -> None:
        cfg = TenantConfig.load("acme-corp")
        assert FEATURE_REGISTRY.is_enabled(cfg, "forecasting") is True
        assert FEATURE_REGISTRY.is_enabled(cfg, "rag") is True
        assert FEATURE_REGISTRY.is_enabled(cfg, "ml") is True

    def test_acme_corp_recommendations_disabled(self) -> None:
        cfg = TenantConfig.load("acme-corp")
        assert FEATURE_REGISTRY.is_enabled(cfg, "recommendations") is False

    def test_globex_only_forecasting(self) -> None:
        cfg = TenantConfig.load("globex")
        assert FEATURE_REGISTRY.is_enabled(cfg, "forecasting") is True
        assert FEATURE_REGISTRY.is_enabled(cfg, "ml") is False
        assert FEATURE_REGISTRY.is_enabled(cfg, "rag") is False

    def test_initech_nothing_enabled(self) -> None:
        cfg = TenantConfig.load("initech")
        for feature in KNOWN_FEATURES:
            assert FEATURE_REGISTRY.is_enabled(cfg, feature) is False

    def test_unknown_feature_never_enabled(self) -> None:
        cfg = TenantConfig.load("acme-corp")
        assert FEATURE_REGISTRY.is_enabled(cfg, "time-travel") is False


class TestEnabledFeatures:
    """``enabled_features`` returns the sorted set of enabled features."""

    def test_acme_corp_enabled_features(self) -> None:
        cfg = TenantConfig.load("acme-corp")
        assert FEATURE_REGISTRY.enabled_features(cfg) == ["forecasting", "ml", "rag"]

    def test_globex_enabled_features(self) -> None:
        cfg = TenantConfig.load("globex")
        assert FEATURE_REGISTRY.enabled_features(cfg) == ["forecasting"]

    def test_initech_enabled_features_empty(self) -> None:
        cfg = TenantConfig.load("initech")
        assert FEATURE_REGISTRY.enabled_features(cfg) == []


class TestValidate:
    """``validate`` warns when a feature is enabled without its dependency."""

    def test_acme_corp_valid(self) -> None:
        cfg = TenantConfig.load("acme-corp")
        assert FEATURE_REGISTRY.validate(cfg) == []

    def test_globex_valid(self) -> None:
        cfg = TenantConfig.load("globex")
        assert FEATURE_REGISTRY.validate(cfg) == []

    def test_rag_without_ml_warns(self) -> None:
        cfg = _tenant({"rag": True})
        warnings = FEATURE_REGISTRY.validate(cfg)
        assert len(warnings) == 1
        assert "rag" in warnings[0]
        assert "ml" in warnings[0]


class TestRagMlDependency:
    """``rag`` is only enabled when ``ml`` is also enabled."""

    def test_rag_requires_ml(self) -> None:
        cfg = _tenant({"rag": True})
        assert FEATURE_REGISTRY.is_enabled(cfg, "rag") is False

    def test_rag_enabled_with_ml(self) -> None:
        cfg = _tenant({"rag": True, "ml": True})
        assert FEATURE_REGISTRY.is_enabled(cfg, "rag") is True

    def test_ml_without_rag_stays_enabled(self) -> None:
        cfg = _tenant({"ml": True})
        assert FEATURE_REGISTRY.is_enabled(cfg, "ml") is True
        assert FEATURE_REGISTRY.is_enabled(cfg, "rag") is False
