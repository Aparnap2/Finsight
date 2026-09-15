"""Tests for the identity model layer (``shared.models.identity``).

Verifies that every identity model (Organization, Tenant, User, Role,
UserRole) constructs and validates; that the local ``MoneyDecimal`` boundary
accepts ``Decimal``/``str`` and rejects ``float``/``int``; that
``currency_code`` enforces the ``[A-Z]{3}`` pattern and
``fiscal_year_start_month`` stays within 1..12; and that all models are frozen
(attribute assignment raises ``pydantic.ValidationError``).
"""

from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError

from shared.models.identity import (
    Organization,
    Role,
    Tenant,
    User,
    UserRole,
)


def _tenant_kwargs(**overrides: Any) -> dict[str, Any]:
    """Return valid ``Tenant`` constructor kwargs with ``overrides`` applied."""
    kwargs: dict[str, Any] = {
        "organization_id": uuid4(),
        "slug": "acme",
        "name": "Acme Corp",
        "currency_code": "USD",
        "fiscal_year_start_month": 1,
        "approval_limits": {
            "manager": Decimal("10000"),
            "director": Decimal("50000"),
            "cfo": Decimal("100000"),
        },
    }
    kwargs.update(overrides)
    return kwargs


class TestIdentityModelConstruction:
    """Each identity model constructs and validates."""

    def test_organization(self) -> None:
        org = Organization(code="ORG1", name="Org One")
        assert org.code == "ORG1"
        assert org.name == "Org One"

    def test_tenant(self) -> None:
        tenant = Tenant(**_tenant_kwargs())
        assert tenant.currency_code == "USD"
        assert tenant.fiscal_year_start_month == 1
        assert tenant.default_materiality_amount == Decimal("0")
        assert tenant.default_materiality_pct == Decimal("0")
        assert tenant.approval_limits == {
            "manager": Decimal("10000"),
            "director": Decimal("50000"),
            "cfo": Decimal("100000"),
        }

    def test_user(self) -> None:
        user = User(name="Ada Lovelace", email="ada@example.com", tenant_id=uuid4())
        assert user.active is True
        assert user.email == "ada@example.com"

    def test_role(self) -> None:
        role = Role(name="analyst", description="Read-only access")
        assert role.name == "analyst"
        assert role.description == "Read-only access"

    def test_user_role(self) -> None:
        user_role = UserRole(user_id=uuid4(), role_id=uuid4())
        assert user_role.user_id is not None
        assert user_role.role_id is not None


class TestMoneyDecimalBoundary:
    """Monetary fields accept Decimal/str and reject float/int."""

    def test_accepts_decimal(self) -> None:
        tenant = Tenant(**_tenant_kwargs(default_materiality_amount=Decimal("50000.00")))
        assert isinstance(tenant.default_materiality_amount, Decimal)
        assert tenant.default_materiality_amount == Decimal("50000.00")

    def test_accepts_str(self) -> None:
        tenant = Tenant(**_tenant_kwargs(default_materiality_pct="2.5"))
        assert tenant.default_materiality_pct == Decimal("2.5")

    @pytest.mark.parametrize("bad", [100.5, 100])
    def test_rejects_float_and_int(self, bad: float | int) -> None:
        with pytest.raises(ValidationError):
            Tenant(**_tenant_kwargs(default_materiality_amount=bad))

    def test_rejects_float_in_approval_limits(self) -> None:
        with pytest.raises(ValidationError):
            Tenant(**_tenant_kwargs(approval_limits={"manager": 10000.0}))

    def test_rejects_int_in_approval_limits(self) -> None:
        with pytest.raises(ValidationError):
            Tenant(**_tenant_kwargs(approval_limits={"manager": 10000}))

    def test_approval_limits_reject_unknown_role(self) -> None:
        with pytest.raises(ValidationError):
            Tenant(**_tenant_kwargs(approval_limits={"ceo": Decimal("1000")}))


class TestTenantConstraints:
    """currency_code pattern and fiscal-month bounds."""

    @pytest.mark.parametrize("bad_currency", ["usd", "US", "Usd"])
    def test_currency_code_rejects_non_uppercase_triplet(self, bad_currency: str) -> None:
        with pytest.raises(ValidationError):
            Tenant(**_tenant_kwargs(currency_code=bad_currency))

    def test_currency_code_accepts_uppercase_triplet(self) -> None:
        tenant = Tenant(**_tenant_kwargs(currency_code="EUR"))
        assert tenant.currency_code == "EUR"

    @pytest.mark.parametrize("month", [0, 13, -1])
    def test_fiscal_month_rejects_out_of_bounds(self, month: int) -> None:
        with pytest.raises(ValidationError):
            Tenant(**_tenant_kwargs(fiscal_year_start_month=month))


class TestFrozenModels:
    """Identity models are frozen — assignment raises ValidationError."""

    @staticmethod
    def _assert_frozen(model: BaseModel) -> None:
        with pytest.raises(ValidationError):
            setattr(model, "id", uuid4())  # noqa: B010 — runtime frozen validation

    def test_all_identity_models_are_frozen(self) -> None:
        models: list[BaseModel] = [
            Organization(code="O1", name="One"),
            Tenant(**_tenant_kwargs()),
            User(name="Ada", email="a@b.co", tenant_id=uuid4()),
            Role(name="analyst"),
            UserRole(user_id=uuid4(), role_id=uuid4()),
        ]
        for model in models:
            self._assert_frozen(model)
