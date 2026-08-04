"""Tests for the KPI domain models.

Covers ``finance/domain/kpi.py``: ``KPIDefinition``, ``KPIValue``, and the
``KPI`` aggregate. Key invariants: KPI values use ``MoneyDecimal`` (float
rejected), definitions carry a formula and display metadata, and the
aggregate links a definition to its time-series values.
"""

import pytest
from pydantic import ValidationError

from finance.domain.kpi import KPI, KPIDefinition, KPIValue


def _definition(**overrides: object) -> KPIDefinition:
    """Build a default KPI definition."""
    defaults: dict[str, object] = {
        "id": "KPI-GM",
        "name": "gross_margin",
        "display_name": "Gross Margin",
        "category": "profitability",
        "formula": "(revenue - cogs) / revenue * 100",
    }
    defaults.update(overrides)
    return KPIDefinition(**defaults)


def _value(**overrides: object) -> KPIValue:
    """Build a default KPI value."""
    defaults: dict[str, object] = {
        "kpi_id": "KPI-GM",
        "kpi_name": "gross_margin",
        "value": "42.5",
        "period_id": "2026-06",
    }
    defaults.update(overrides)
    return KPIValue(**defaults)


def _kpi(**overrides: object) -> KPI:
    """Build a default KPI aggregate."""
    defaults: dict[str, object] = {
        "definition": _definition(),
        "values": [_value()],
        "company_id": "CF001",
    }
    defaults.update(overrides)
    return KPI(**defaults)


# =============================================================================
# KPIDefinition
# =============================================================================


class TestKPIDefinition:
    """KPI definition construction."""

    def test_constructs_with_required_fields(self) -> None:
        """A KPI definition builds with required fields."""
        definition = _definition()
        assert definition.id == "KPI-GM"
        assert definition.name == "gross_margin"
        assert definition.display_name == "Gross Margin"
        assert definition.category == "profitability"
        assert definition.formula == "(revenue - cogs) / revenue * 100"

    def test_unit_defaults_to_percent(self) -> None:
        """unit defaults to '%'."""
        assert _definition().unit == "%"

    def test_higher_is_better_defaults_to_true(self) -> None:
        """higher_is_better defaults to True."""
        assert _definition().higher_is_better is True

    def test_unit_settable(self) -> None:
        """The unit is settable."""
        assert _definition(unit="$").unit == "$"

    def test_higher_is_better_settable(self) -> None:
        """higher_is_better is settable (e.g., cost KPIs)."""
        assert _definition(higher_is_better=False).higher_is_better is False

    def test_id_required(self) -> None:
        """A KPI definition requires an id."""
        with pytest.raises(ValidationError):
            _definition(id=None)

    def test_formula_required(self) -> None:
        """A KPI definition requires a formula."""
        with pytest.raises(ValidationError):
            _definition(formula=None)


# =============================================================================
# KPIValue
# =============================================================================


class TestKPIValue:
    """KPI value construction."""

    def test_constructs_with_required_fields(self) -> None:
        """A KPI value builds with required fields."""
        value = _value()
        assert value.kpi_id == "KPI-GM"
        assert value.kpi_name == "gross_margin"
        assert value.period_id == "2026-06"

    def test_value_is_decimal(self) -> None:
        """The KPI value is stored as Decimal."""
        assert str(_value().value) == "42.5"

    def test_float_value_rejected(self) -> None:
        """A float KPI value is rejected."""
        with pytest.raises(ValidationError):
            _value(value=42.5)

    def test_string_value_coerced(self) -> None:
        """A string KPI value is coerced to Decimal."""
        assert str(_value(value="42.5").value) == "42.5"

    def test_negative_value_representable(self) -> None:
        """A negative KPI value is representable."""
        assert str(_value(value="-5.0").value) == "-5.0"

    def test_previous_value_defaults_to_none(self) -> None:
        """previous_value defaults to None."""
        assert _value().previous_value is None

    def test_change_defaults_to_none(self) -> None:
        """change defaults to None."""
        assert _value().change is None

    def test_change_pct_defaults_to_none(self) -> None:
        """change_pct defaults to None."""
        assert _value().change_pct is None

    def test_trend_defaults_to_none(self) -> None:
        """trend defaults to None."""
        assert _value().trend is None

    def test_target_defaults_to_none(self) -> None:
        """target defaults to None."""
        assert _value().target is None

    def test_status_defaults_to_none(self) -> None:
        """status defaults to None."""
        assert _value().status is None

    def test_comparison_fields_stored(self) -> None:
        """Prior comparison and trend fields are preserved."""
        value = _value(
            previous_value="40.0",
            change="2.5",
            change_pct="6.25",
            trend="improving",
            target="45.0",
            status="on_track",
        )
        assert str(value.previous_value) == "40.0"
        assert str(value.change) == "2.5"
        assert str(value.change_pct) == "6.25"
        assert value.trend == "improving"
        assert str(value.target) == "45.0"
        assert value.status == "on_track"

    def test_kpi_id_required(self) -> None:
        """A KPI value requires a kpi_id."""
        with pytest.raises(ValidationError):
            _value(kpi_id=None)

    def test_value_required(self) -> None:
        """A KPI value requires a value."""
        with pytest.raises(ValidationError):
            _value(value=None)

    def test_period_id_required(self) -> None:
        """A KPI value requires a period id."""
        with pytest.raises(ValidationError):
            _value(period_id=None)


# =============================================================================
# KPI aggregate
# =============================================================================


class TestKPI:
    """KPI aggregate construction."""

    def test_constructs_with_required_fields(self) -> None:
        """A KPI aggregate builds with required fields."""
        kpi = _kpi()
        assert kpi.company_id == "CF001"
        assert kpi.definition.id == "KPI-GM"
        assert len(kpi.values) == 1

    def test_definition_is_kpi_definition(self) -> None:
        """The definition is validated as a KPIDefinition."""
        assert isinstance(_kpi().definition, KPIDefinition)

    def test_values_are_kpi_value_instances(self) -> None:
        """Values are validated as KPIValue instances."""
        assert isinstance(_kpi().values[0], KPIValue)

    def test_multiple_values_stored(self) -> None:
        """A KPI carries a time series of values."""
        kpi = _kpi(values=[_value(), _value(period_id="2026-05")])
        assert len(kpi.values) == 2

    def test_company_id_required(self) -> None:
        """A KPI requires a company id."""
        with pytest.raises(ValidationError):
            _kpi(company_id=None)

    def test_definition_required(self) -> None:
        """A KPI requires a definition."""
        with pytest.raises(ValidationError):
            _kpi(definition=None)

    def test_round_trip_serialization(self) -> None:
        """A KPI round-trips through model_dump."""
        kpi = _kpi()
        dumped = kpi.model_dump()
        rebuilt = KPI(**dumped)
        assert rebuilt == kpi