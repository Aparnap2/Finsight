"""Tests for the Driver domain models.

Covers ``finance/domain/driver.py``: the ``DriverType`` enum, the ``Driver``
record, and the recursive ``DriverTree``. Key invariants: driver values use
``MoneyDecimal`` (float rejected), trees recursively nest children, and
contribution weights default to 1.0.
"""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from finance.domain.driver import Driver, DriverTree, DriverType


def _driver(**overrides: object) -> Driver:
    """Build a default driver."""
    defaults: dict[str, object] = {
        "id": "DRV-001",
        "name": "Headcount",
        "type": DriverType.COST,
        "description": "Employee headcount during the period.",
        "unit": "headcount",
        "value": "120",
    }
    defaults.update(overrides)
    return Driver(**defaults)


# =============================================================================
# DriverType enum
# =============================================================================


class TestDriverType:
    """DriverType enum values."""

    def test_revenue_value(self) -> None:
        """REVENUE serializes to 'revenue'."""
        assert DriverType.REVENUE.value == "revenue"

    def test_cost_value(self) -> None:
        """COST serializes to 'cost'."""
        assert DriverType.COST.value == "cost"

    def test_operational_value(self) -> None:
        """OPERATIONAL serializes to 'operational'."""
        assert DriverType.OPERATIONAL.value == "operational"

    def test_macro_value(self) -> None:
        """MACRO serializes to 'macro'."""
        assert DriverType.MACRO.value == "macro"


# =============================================================================
# Driver
# =============================================================================


class TestDriver:
    """Driver construction."""

    def test_constructs_with_required_fields(self) -> None:
        """A driver builds with required fields."""
        driver = _driver()
        assert driver.id == "DRV-001"
        assert driver.name == "Headcount"
        assert driver.type == DriverType.COST
        assert driver.unit == "headcount"

    def test_value_is_decimal(self) -> None:
        """The current value is stored as Decimal."""
        assert str(_driver().value) == "120"

    def test_float_value_rejected(self) -> None:
        """A float driver value is rejected."""
        with pytest.raises(ValidationError):
            _driver(value=120.0)

    def test_string_value_coerced(self) -> None:
        """A string driver value is coerced to Decimal."""
        assert str(_driver(value="120.5").value) == "120.5"

    def test_previous_value_defaults_to_none(self) -> None:
        """previous_value defaults to None."""
        assert _driver().previous_value is None

    def test_change_pct_defaults_to_none(self) -> None:
        """change_pct defaults to None."""
        assert _driver().change_pct is None

    def test_correlation_defaults_to_none(self) -> None:
        """correlation defaults to None."""
        assert _driver().correlation is None

    def test_related_account_codes_default_to_empty(self) -> None:
        """related_account_codes defaults to an empty list."""
        assert _driver().related_account_codes == []

    def test_prior_comparison_stored(self) -> None:
        """Prior value and change are preserved."""
        driver = _driver(
            previous_value="110",
            change_pct="9.09",
            correlation="0.87",
            related_account_codes=["6400", "6410"],
        )
        assert str(driver.previous_value) == "110"
        assert str(driver.change_pct) == "9.09"
        assert str(driver.correlation) == "0.87"
        assert driver.related_account_codes == ["6400", "6410"]

    def test_all_driver_types_representable(self) -> None:
        """Every driver type constructs a driver."""
        for driver_type in DriverType:
            driver = _driver(type=driver_type)
            assert driver.type == driver_type

    def test_id_required(self) -> None:
        """A driver requires an id."""
        with pytest.raises(ValidationError):
            _driver(id=None)

    def test_value_required(self) -> None:
        """A driver requires a value."""
        with pytest.raises(ValidationError):
            _driver(value=None)

    def test_name_required(self) -> None:
        """A driver requires a name."""
        with pytest.raises(ValidationError):
            _driver(name=None)

    def test_unit_required(self) -> None:
        """A driver requires a unit."""
        with pytest.raises(ValidationError):
            _driver(unit=None)


# =============================================================================
# DriverTree
# =============================================================================


class TestDriverTree:
    """Driver tree construction."""

    def _tree(self) -> DriverTree:
        """A root driver with one child."""
        return DriverTree(
            root_driver=_driver(),
            children=[
                DriverTree(
                    root_driver=_driver(id="DRV-002", name="Airfare"),
                    weight=Decimal("0.6"),
                )
            ],
        )

    def test_constructs_with_root(self) -> None:
        """A tree builds with a root driver."""
        tree = self._tree()
        assert tree.root_driver.id == "DRV-001"

    def test_children_default_to_empty(self) -> None:
        """children defaults to an empty list."""
        tree = DriverTree(root_driver=_driver())
        assert tree.children == []

    def test_weight_defaults_to_one(self) -> None:
        """The contribution weight defaults to 1.0."""
        assert DriverTree(root_driver=_driver()).weight == Decimal("1.0")

    def test_children_stored(self) -> None:
        """Child trees are preserved."""
        tree = self._tree()
        assert len(tree.children) == 1
        assert tree.children[0].root_driver.name == "Airfare"
        assert tree.children[0].weight == Decimal("0.6")

    def test_nested_children(self) -> None:
        """Trees nest recursively."""
        tree = DriverTree(
            root_driver=_driver(),
            children=[
                DriverTree(
                    root_driver=_driver(id="DRV-002"),
                    children=[
                        DriverTree(root_driver=_driver(id="DRV-003"), weight=Decimal("0.3"))
                    ],
                )
            ],
        )
        assert tree.children[0].children[0].root_driver.id == "DRV-003"

    def test_weight_settable(self) -> None:
        """The root weight is settable."""
        assert DriverTree(root_driver=_driver(), weight=Decimal("0.5")).weight == Decimal("0.5")

    def test_root_driver_required(self) -> None:
        """A tree requires a root driver."""
        with pytest.raises(ValidationError):
            DriverTree(weight=Decimal("0.5"))  # type: ignore[call-arg]

    def test_round_trip_serialization(self) -> None:
        """A tree round-trips through model_dump."""
        tree = self._tree()
        dumped = tree.model_dump()
        rebuilt = DriverTree(**dumped)
        assert rebuilt == tree