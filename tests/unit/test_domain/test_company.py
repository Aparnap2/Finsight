"""Tests for the Company domain model.

Covers ``finance/domain/company.py``: the top-level legal entity anchor.
Key invariants: the base currency defaults to USD, the fiscal year start
must be a valid ``MM-DD`` string (month 01-12, day 01-31), and created/
updated timestamps are required.
"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from finance.domain.company import Company


def _now() -> datetime:
    """A fixed timestamp for created/updated fields."""
    return datetime(2026, 7, 15, 12, 0, 0, tzinfo=UTC)


def _company(**overrides: object) -> Company:
    """Build a default company."""
    defaults: dict[str, object] = {
        "id": "CF001",
        "name": "Acme Corp",
        "created_at": _now(),
        "updated_at": _now(),
    }
    defaults.update(overrides)
    return Company(**defaults)


class TestCompany:
    """Company construction."""

    def test_constructs_with_required_fields(self) -> None:
        """A company builds with required fields."""
        company = _company()
        assert company.id == "CF001"
        assert company.name == "Acme Corp"

    def test_currency_defaults_to_usd(self) -> None:
        """The base currency defaults to USD."""
        assert _company().currency == "USD"

    def test_fiscal_year_start_defaults_to_jan_1(self) -> None:
        """The fiscal year start defaults to 01-01 (calendar year)."""
        assert _company().fiscal_year_start == "01-01"

    def test_currency_settable(self) -> None:
        """The base currency is settable."""
        assert _company(currency="EUR").currency == "EUR"

    def test_fiscal_year_start_settable(self) -> None:
        """A non-calendar fiscal year start is settable."""
        assert _company(fiscal_year_start="07-01").fiscal_year_start == "07-01"

    def test_valid_fiscal_year_starts_accepted(self) -> None:
        """All month boundaries are accepted."""
        for start in ("01-01", "03-15", "12-31"):
            assert _company(fiscal_year_start=start).fiscal_year_start == start

    def test_invalid_format_rejected(self) -> None:
        """A non-MM-DD fiscal year start is rejected."""
        with pytest.raises(ValidationError, match="MM-DD"):
            _company(fiscal_year_start="2026-01-01")

    def test_non_digit_parts_rejected(self) -> None:
        """Non-digit month/day parts are rejected."""
        with pytest.raises(ValidationError, match="MM-DD"):
            _company(fiscal_year_start="aa-bb")

    def test_month_out_of_range_rejected(self) -> None:
        """A month outside 01-12 is rejected."""
        with pytest.raises(ValidationError, match="between 01 and 12"):
            _company(fiscal_year_start="13-01")

    def test_day_out_of_range_rejected(self) -> None:
        """A day outside 01-31 is rejected."""
        with pytest.raises(ValidationError, match="between 01 and 31"):
            _company(fiscal_year_start="01-32")

    def test_zero_day_rejected(self) -> None:
        """A day of 00 is rejected."""
        with pytest.raises(ValidationError):
            _company(fiscal_year_start="01-00")

    def test_id_required(self) -> None:
        """A company requires an id."""
        with pytest.raises(ValidationError):
            _company(id=None)

    def test_name_required(self) -> None:
        """A company requires a name."""
        with pytest.raises(ValidationError):
            _company(name=None)

    def test_created_at_required(self) -> None:
        """A company requires a created_at timestamp."""
        with pytest.raises(ValidationError):
            _company(created_at=None)

    def test_updated_at_required(self) -> None:
        """A company requires an updated_at timestamp."""
        with pytest.raises(ValidationError):
            _company(updated_at=None)

    def test_round_trip_serialization(self) -> None:
        """A company round-trips through model_dump."""
        company = _company()
        dumped = company.model_dump()
        rebuilt = Company(**dumped)
        assert rebuilt == company