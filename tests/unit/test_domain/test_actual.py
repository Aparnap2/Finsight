"""Tests for the Actual domain models.

Covers ``finance/domain/actual.py``: the ``ActualLine`` record and the
``Actual`` batch aggregate. Key invariants: amounts use ``MoneyDecimal``
(float rejected), lines carry optional department/cost-centre attribution,
and transaction counts are non-negative aggregates.
"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from finance.domain.actual import Actual, ActualLine


def _now() -> datetime:
    """A fixed timestamp for loaded_at."""
    return datetime(2026, 7, 15, 12, 0, 0, tzinfo=UTC)


def _line(**overrides: object) -> ActualLine:
    """Build a default actual line."""
    defaults: dict[str, object] = {
        "id": "ACT-001",
        "account_id": "4010",
        "amount": "1250.00",
        "period_id": "2026-06",
    }
    defaults.update(overrides)
    return ActualLine(**defaults)


def _actual(**overrides: object) -> Actual:
    """Build a default actual batch."""
    defaults: dict[str, object] = {
        "id": "ACT-BATCH-001",
        "company_id": "CF001",
        "fiscal_year": 2026,
        "lines": [_line()],
        "period_id": "2026-06",
        "loaded_at": _now(),
    }
    defaults.update(overrides)
    return Actual(**defaults)


# =============================================================================
# ActualLine
# =============================================================================


class TestActualLine:
    """Actual line construction."""

    def test_constructs_with_required_fields(self) -> None:
        """An actual line builds with required fields."""
        line = _line()
        assert line.id == "ACT-001"
        assert line.account_id == "4010"
        assert line.period_id == "2026-06"

    def test_amount_is_decimal(self) -> None:
        """The amount is stored as Decimal."""
        assert str(_line().amount) == "1250.00"

    def test_float_amount_rejected(self) -> None:
        """A float amount is rejected."""
        with pytest.raises(ValidationError):
            _line(amount=1250.0)

    def test_string_amount_coerced(self) -> None:
        """A string amount is coerced to Decimal."""
        assert str(_line(amount="1250.50").amount) == "1250.50"

    def test_negative_amount_representable(self) -> None:
        """A negative amount (e.g., credit memo) is representable."""
        line = _line(amount="-100.00")
        assert str(line.amount) == "-100.00"

    def test_department_defaults_to_none(self) -> None:
        """department_id defaults to None."""
        assert _line().department_id is None

    def test_cost_center_defaults_to_none(self) -> None:
        """cost_center_id defaults to None."""
        assert _line().cost_center_id is None

    def test_transaction_count_defaults_to_zero(self) -> None:
        """transaction_count defaults to 0."""
        assert _line().transaction_count == 0

    def test_source_defaults_to_gl(self) -> None:
        """source defaults to 'gl'."""
        assert _line().source == "gl"

    def test_attribution_stored(self) -> None:
        """Department and cost-centre attribution are preserved."""
        line = _line(department_id="FINANCE", cost_center_id="CC-100")
        assert line.department_id == "FINANCE"
        assert line.cost_center_id == "CC-100"

    def test_transaction_count_settable(self) -> None:
        """The transaction count is settable."""
        assert _line(transaction_count=14).transaction_count == 14

    def test_id_required(self) -> None:
        """An actual line requires an id."""
        with pytest.raises(ValidationError):
            _line(id=None)

    def test_account_id_required(self) -> None:
        """An actual line requires an account id."""
        with pytest.raises(ValidationError):
            _line(account_id=None)

    def test_amount_required(self) -> None:
        """An actual line requires an amount."""
        with pytest.raises(ValidationError):
            _line(amount=None)

    def test_period_id_required(self) -> None:
        """An actual line requires a period id."""
        with pytest.raises(ValidationError):
            _line(period_id=None)


# =============================================================================
# Actual
# =============================================================================


class TestActual:
    """Actual batch aggregate construction."""

    def test_constructs_with_required_fields(self) -> None:
        """An actual batch builds with required fields."""
        actual = _actual()
        assert actual.id == "ACT-BATCH-001"
        assert actual.company_id == "CF001"
        assert actual.fiscal_year == 2026
        assert actual.period_id == "2026-06"
        assert len(actual.lines) == 1

    def test_multiple_lines_stored(self) -> None:
        """A batch carries multiple lines."""
        actual = _actual(lines=[_line(), _line(id="ACT-002")])
        assert len(actual.lines) == 2

    def test_lines_are_actual_line_instances(self) -> None:
        """Lines are validated as ActualLine instances."""
        actual = _actual()
        assert isinstance(actual.lines[0], ActualLine)

    def test_invalid_line_rejected(self) -> None:
        """A malformed line is rejected at the batch boundary."""
        with pytest.raises(ValidationError):
            _actual(lines=[{"id": "ACT-003"}])

    def test_fiscal_year_boundaries_representable(self) -> None:
        """Fiscal years at the documented boundaries are representable."""
        for year in (1900, 2100):
            actual = _actual(fiscal_year=year)
            assert actual.fiscal_year == year

    def test_empty_lines_representable(self) -> None:
        """An empty lines list is representable (no postings yet)."""
        assert _actual(lines=[]).lines == []

    def test_company_id_required(self) -> None:
        """An actual batch requires a company id."""
        with pytest.raises(ValidationError):
            _actual(company_id=None)

    def test_loaded_at_required(self) -> None:
        """An actual batch requires a loaded_at timestamp."""
        with pytest.raises(ValidationError):
            _actual(loaded_at=None)

    def test_round_trip_serialization(self) -> None:
        """An actual batch round-trips through model_dump."""
        actual = _actual()
        dumped = actual.model_dump()
        rebuilt = Actual(**dumped)
        assert rebuilt == actual