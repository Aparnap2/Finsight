"""Tests for the demo tenant configurations (``tenants/demo/*/tenant.yaml``).

Asserts the currency, fiscal year start, materiality, SOX, and feature-flag
differences across acme-corp, globex, and initech as loaded by
``TenantConfig.load_all``.
"""

from decimal import Decimal

from finplatform.config.features import FEATURE_REGISTRY
from finplatform.config.tenant_schema import TenantConfig


class TestCurrenciesAndFiscalCalendars:
    """Each demo tenant uses a distinct currency and fiscal calendar."""

    def test_currencies(self) -> None:
        configs = TenantConfig.load_all()
        assert configs["acme-corp"].currency == "USD"
        assert configs["globex"].currency == "EUR"
        assert configs["initech"].currency == "GBP"

    def test_fiscal_year_start_months(self) -> None:
        configs = TenantConfig.load_all()
        assert configs["acme-corp"].fiscal_year_start_month == 1  # January
        assert configs["globex"].fiscal_year_start_month == 7  # July
        assert configs["initech"].fiscal_year_start_month == 4  # April


class TestMateriality:
    """Materiality thresholds differ per tenant."""

    def test_amounts(self) -> None:
        configs = TenantConfig.load_all()
        assert configs["acme-corp"].materiality.amount == Decimal("5000")
        assert configs["globex"].materiality.amount == Decimal("25000")
        assert configs["initech"].materiality.amount == Decimal("10000")

    def test_percentages(self) -> None:
        configs = TenantConfig.load_all()
        assert configs["acme-corp"].materiality.pct == Decimal("5")
        assert configs["globex"].materiality.pct == Decimal("8")
        assert configs["initech"].materiality.pct == Decimal("6")


class TestSoxAndFeatures:
    """SOX compliance and feature flags differ across tenants."""

    def test_sox_enabled(self) -> None:
        configs = TenantConfig.load_all()
        assert configs["acme-corp"].sox_enabled is True
        assert configs["globex"].sox_enabled is False
        assert configs["initech"].sox_enabled is False

    def test_feature_flags(self) -> None:
        configs = TenantConfig.load_all()
        assert FEATURE_REGISTRY.enabled_features(configs["acme-corp"]) == [
            "forecasting",
            "ml",
            "rag",
        ]
        assert FEATURE_REGISTRY.enabled_features(configs["globex"]) == ["forecasting"]
        assert FEATURE_REGISTRY.enabled_features(configs["initech"]) == []
