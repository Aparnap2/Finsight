"""Tests for the Cost Center domain model.

Covers ``finance/domain/cost_center.py``: the sub-unit for detailed cost
tracking. Tests cover construction, the budget-owner responsibility, and
company/department scoping.
"""

import pytest
from pydantic import ValidationError

from finance.domain.cost_center import CostCenter


def _cost_center(**overrides: object) -> CostCenter:
    """Build a default cost centre."""
    defaults: dict[str, object] = {
        "id": "CC-100",
        "code": "ENG-CLOUD",
        "name": "Cloud Engineering",
        "department_id": "DEPT-ENG",
        "company_id": "CF001",
    }
    defaults.update(overrides)
    return CostCenter(**defaults)


class TestCostCenter:
    """Cost centre construction."""

    def test_constructs_with_required_fields(self) -> None:
        """A cost centre builds with required fields."""
        cc = _cost_center()
        assert cc.id == "CC-100"
        assert cc.code == "ENG-CLOUD"
        assert cc.name == "Cloud Engineering"
        assert cc.department_id == "DEPT-ENG"
        assert cc.company_id == "CF001"

    def test_manager_defaults_to_none(self) -> None:
        """manager defaults to None."""
        assert _cost_center().manager is None

    def test_budget_owner_defaults_to_none(self) -> None:
        """budget_owner defaults to None."""
        assert _cost_center().budget_owner is None

    def test_is_active_defaults_to_true(self) -> None:
        """Cost centres default to active."""
        assert _cost_center().is_active is True

    def test_manager_settable(self) -> None:
        """The manager is settable."""
        assert _cost_center(manager="Grace Hopper").manager == "Grace Hopper"

    def test_budget_owner_settable(self) -> None:
        """The budget owner is settable."""
        assert _cost_center(budget_owner="CFO").budget_owner == "CFO"

    def test_inactive_cost_center_representable(self) -> None:
        """An inactive cost centre is representable."""
        assert _cost_center(is_active=False).is_active is False

    def test_id_required(self) -> None:
        """A cost centre requires an id."""
        with pytest.raises(ValidationError):
            _cost_center(id=None)

    def test_code_required(self) -> None:
        """A cost centre requires a code."""
        with pytest.raises(ValidationError):
            _cost_center(code=None)

    def test_name_required(self) -> None:
        """A cost centre requires a name."""
        with pytest.raises(ValidationError):
            _cost_center(name=None)

    def test_department_id_required(self) -> None:
        """A cost centre requires a department id."""
        with pytest.raises(ValidationError):
            _cost_center(department_id=None)

    def test_company_id_required(self) -> None:
        """A cost centre requires a company id."""
        with pytest.raises(ValidationError):
            _cost_center(company_id=None)

    def test_round_trip_serialization(self) -> None:
        """A cost centre round-trips through model_dump."""
        cc = _cost_center(budget_owner="CFO")
        dumped = cc.model_dump()
        rebuilt = CostCenter(**dumped)
        assert rebuilt == cc