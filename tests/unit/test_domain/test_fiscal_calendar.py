"""Tests for the Fiscal Calendar domain models.

Covers ``finance/domain/fiscal_calendar.py``: the ``FiscalPeriodType`` enum,
the ``FiscalPeriod`` record, and the ``FiscalCalendar`` aggregate. Key
invariants: period numbers are ordinal within the fiscal year, periods
carry calendar start/end dates, and a calendar has one active period.
"""

from datetime import date

import pytest
from pydantic import ValidationError

from finance.domain.fiscal_calendar import (
    FiscalCalendar,
    FiscalPeriod,
    FiscalPeriodType,
)


def _period(**overrides: object) -> FiscalPeriod:
    """Build a default monthly fiscal period."""
    defaults: dict[str, object] = {
        "id": "2026-06",
        "fiscal_year": 2026,
        "period_number": 6,
        "period_type": FiscalPeriodType.MONTHLY,
        "start_date": date(2026, 6, 1),
        "end_date": date(2026, 6, 30),
    }
    defaults.update(overrides)
    return FiscalPeriod(**defaults)


def _calendar(**overrides: object) -> FiscalCalendar:
    """Build a default fiscal calendar."""
    defaults: dict[str, object] = {
        "id": "CAL-001",
        "company_id": "CF001",
        "periods": [_period()],
    }
    defaults.update(overrides)
    return FiscalCalendar(**defaults)


# =============================================================================
# FiscalPeriodType enum
# =============================================================================


class TestFiscalPeriodType:
    """FiscalPeriodType enum values."""

    def test_monthly_value(self) -> None:
        """MONTHLY serializes to 'monthly'."""
        assert FiscalPeriodType.MONTHLY.value == "monthly"

    def test_quarterly_value(self) -> None:
        """QUARTERLY serializes to 'quarterly'."""
        assert FiscalPeriodType.QUARTERLY.value == "quarterly"

    def test_annual_value(self) -> None:
        """ANNUAL serializes to 'annual'."""
        assert FiscalPeriodType.ANNUAL.value == "annual"


# =============================================================================
# FiscalPeriod
# =============================================================================


class TestFiscalPeriod:
    """Fiscal period construction."""

    def test_constructs_with_required_fields(self) -> None:
        """A fiscal period builds with required fields."""
        period = _period()
        assert period.id == "2026-06"
        assert period.fiscal_year == 2026
        assert period.period_number == 6
        assert period.period_type == FiscalPeriodType.MONTHLY
        assert period.start_date == date(2026, 6, 1)
        assert period.end_date == date(2026, 6, 30)

    def test_is_closed_defaults_to_false(self) -> None:
        """Periods default to open."""
        assert _period().is_closed is False

    def test_closed_period_representable(self) -> None:
        """A closed period is representable."""
        assert _period(is_closed=True).is_closed is True

    def test_quarterly_period_representable(self) -> None:
        """A quarterly period is representable."""
        period = _period(
            id="2026-Q2",
            period_number=2,
            period_type=FiscalPeriodType.QUARTERLY,
            start_date=date(2026, 4, 1),
            end_date=date(2026, 6, 30),
        )
        assert period.period_type == FiscalPeriodType.QUARTERLY
        assert period.period_number == 2

    def test_annual_period_representable(self) -> None:
        """An annual period is representable."""
        period = _period(
            id="FY2026",
            period_number=1,
            period_type=FiscalPeriodType.ANNUAL,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
        )
        assert period.period_type == FiscalPeriodType.ANNUAL

    def test_id_required(self) -> None:
        """A fiscal period requires an id."""
        with pytest.raises(ValidationError):
            _period(id=None)

    def test_fiscal_year_required(self) -> None:
        """A fiscal period requires a fiscal year."""
        with pytest.raises(ValidationError):
            _period(fiscal_year=None)

    def test_period_number_required(self) -> None:
        """A fiscal period requires a period number."""
        with pytest.raises(ValidationError):
            _period(period_number=None)

    def test_start_date_required(self) -> None:
        """A fiscal period requires a start date."""
        with pytest.raises(ValidationError):
            _period(start_date=None)

    def test_end_date_required(self) -> None:
        """A fiscal period requires an end date."""
        with pytest.raises(ValidationError):
            _period(end_date=None)


# =============================================================================
# FiscalCalendar
# =============================================================================


class TestFiscalCalendar:
    """Fiscal calendar aggregate construction."""

    def test_constructs_with_required_fields(self) -> None:
        """A calendar builds with required fields."""
        calendar = _calendar()
        assert calendar.id == "CAL-001"
        assert calendar.company_id == "CF001"
        assert len(calendar.periods) == 1

    def test_current_period_defaults_to_none(self) -> None:
        """current_period_id defaults to None."""
        assert _calendar().current_period_id is None

    def test_multiple_periods_stored(self) -> None:
        """A calendar carries multiple periods."""
        calendar = _calendar(
            periods=[_period(), _period(id="2026-07", period_number=7)]
        )
        assert len(calendar.periods) == 2

    def test_periods_are_fiscal_period_instances(self) -> None:
        """Periods are validated as FiscalPeriod instances."""
        assert isinstance(_calendar().periods[0], FiscalPeriod)

    def test_invalid_period_rejected(self) -> None:
        """A malformed period is rejected at the calendar boundary."""
        with pytest.raises(ValidationError):
            _calendar(periods=[{"id": "2026-06"}])

    def test_current_period_settable(self) -> None:
        """The active period is settable."""
        assert _calendar(current_period_id="2026-06").current_period_id == "2026-06"

    def test_company_id_required(self) -> None:
        """A calendar requires a company id."""
        with pytest.raises(ValidationError):
            _calendar(company_id=None)

    def test_round_trip_serialization(self) -> None:
        """A calendar round-trips through model_dump."""
        calendar = _calendar(current_period_id="2026-06")
        dumped = calendar.model_dump()
        rebuilt = FiscalCalendar(**dumped)
        assert rebuilt == calendar