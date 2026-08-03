"""Tests for the tenant configuration schema (``finplatform.config.tenant_schema``).

Verifies that ``TenantConfig.load`` and ``TenantConfig.load_all`` produce
frozen models with the expected demo values (acme-corp: USD, materiality
5000 / 5%), that per-tenant values are distinct, that unknown tenant codes
raise ``TenantConfigError``, that models are immutable, and that all
monetary fields are ``decimal.Decimal``.
"""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from finplatform.config.tenant_schema import TenantConfig, TenantConfigError


class TestLoad:
    """``TenantConfig.load`` resolves and validates a single tenant."""

    def test_load_acme_corp_returns_model(self) -> None:
        cfg = TenantConfig.load("acme-corp")
        assert cfg.tenant_id == "acme-corp"
        assert cfg.currency == "USD"
        assert cfg.fiscal_year_start_month == 1

    def test_load_acme_corp_materiality(self) -> None:
        cfg = TenantConfig.load("acme-corp")
        assert cfg.materiality.amount == Decimal("5000")
        assert cfg.materiality.pct == Decimal("5")

    def test_load_acme_corp_approval_limits_are_decimal(self) -> None:
        cfg = TenantConfig.load("acme-corp")
        assert cfg.approval_limits.manager == Decimal("10000")
        assert cfg.approval_limits.director == Decimal("50000")
        assert cfg.approval_limits.cfo == Decimal("250000")
        assert isinstance(cfg.approval_limits.manager, Decimal)

    def test_load_unknown_tenant_raises(self) -> None:
        with pytest.raises(TenantConfigError):
            TenantConfig.load("no-such-tenant")


class TestLoadAll:
    """``TenantConfig.load_all`` loads every demo tenant."""

    def test_load_all_keys(self) -> None:
        configs = TenantConfig.load_all()
        assert sorted(configs) == ["acme-corp", "globex", "initech"]

    def test_load_all_currencies_differ_per_tenant(self) -> None:
        configs = TenantConfig.load_all()
        assert configs["acme-corp"].currency == "USD"
        assert configs["globex"].currency == "EUR"
        assert configs["initech"].currency == "GBP"

    def test_load_all_materiality_amounts_differ_per_tenant(self) -> None:
        configs = TenantConfig.load_all()
        assert configs["acme-corp"].materiality.amount == Decimal("5000")
        assert configs["globex"].materiality.amount == Decimal("25000")
        assert configs["initech"].materiality.amount == Decimal("10000")

    def test_load_all_materiality_pcts_differ_per_tenant(self) -> None:
        configs = TenantConfig.load_all()
        assert configs["acme-corp"].materiality.pct == Decimal("5")
        assert configs["globex"].materiality.pct == Decimal("8")
        assert configs["initech"].materiality.pct == Decimal("6")


class TestFrozenModel:
    """``TenantConfig`` models are immutable (``ConfigDict(frozen=True)``)."""

    def test_model_config_is_frozen(self) -> None:
        assert TenantConfig.model_config.get("frozen") is True

    def test_attribute_assignment_raises(self) -> None:
        cfg = TenantConfig.load("acme-corp")
        with pytest.raises(ValidationError):
            cfg.currency = "XXX"

    def test_money_fields_are_decimal(self) -> None:
        cfg = TenantConfig.load("acme-corp")
        assert isinstance(cfg.materiality.amount, Decimal)
        assert isinstance(cfg.materiality.pct, Decimal)
        assert isinstance(cfg.approval_limits.cfo, Decimal)
