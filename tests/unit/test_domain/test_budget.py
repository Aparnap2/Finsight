"""Tests for the Budget domain models.

Covers the analytics `finance.domain.budget` model: version lifecycle,
line-item construction, monetary invariants, and aggregation. All monetary
values are ``decimal.Decimal`` — never ``float``.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from finance.domain.budget import Budget, BudgetLine, BudgetVersion


def _now() -> datetime:
    """Return a fixed, timezone-aware timestamp for determinism."""
    return datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)


def _line(
    amount: Decimal | str = Decimal("100000.0000"),
    version: BudgetVersion = BudgetVersion.ORIGINAL,
    line_id: str = "bl-001",
) -> BudgetLine:
    """Build a budget line with sensible defaults."""
    return BudgetLine(
        id=line_id,
        account_id="acc-1000",
        amount=amount if isinstance(amount, Decimal) else Decimal(amount),
        period_id="2026-07",
        version=version,
    )


class TestBudgetVersion:
    """Budget version lifecycle enum."""

    def test_enum_values(self) -> None:
        """The enum exposes the canonical lifecycle stages."""
        assert BudgetVersion.ORIGINAL.value == "original"
        assert BudgetVersion.REVISED.value == "revised"
        assert BudgetVersion.ADJUSTED.value == "adjusted"

    def test_str_round_trip(self) -> None:
        """StrEnum values serialize to their canonical strings."""
        assert str(BudgetVersion.REVISED) == "revised"

    def test_default_version_is_original(self) -> None:
        """A budget line defaults to the original version."""
        assert _line().version == BudgetVersion.ORIGINAL


class TestBudgetLine:
    """Budget line construction invariants."""

    def test_valid_line_constructs(self) -> None:
        """A fully specified budget line constructs."""
        line = _line()
        assert line.id == "bl-001"
        assert line.account_id == "acc-1000"
        assert line.amount == Decimal("100000.0000")

    def test_defaults_are_none(self) -> None:
        """Department and cost centre default to None."""
        line = _line()
        assert line.department_id is None
        assert line.cost_center_id is None

    def test_float_amount_rejected(self) -> None:
        """Float monetary values are rejected."""
        with pytest.raises(ValidationError, match="Float values are not allowed"):
            BudgetLine(
                id="bl-002",
                account_id="acc-1000",
                amount=1000.50,
                period_id="2026-07",
            )

    def test_string_amount_accepted(self) -> None:
        """String amounts are coerced to Decimal."""
        line = BudgetLine(
            id="bl-003",
            account_id="acc-1000",
            amount="1000.50",
            period_id="2026-07",
        )
        assert isinstance(line.amount, Decimal)
        assert line.amount == Decimal("1000.5000")

    def test_zero_amount_constructs(self) -> None:
        """A zero budget line is valid."""
        assert _line(amount=Decimal("0.00")).amount == Decimal("0.0000")

    def test_negative_amount_constructs(self) -> None:
        """A negative budget line (e.g. contra-account) is valid."""
        assert _line(amount=Decimal("-500.00")).amount == Decimal("-500.0000")

    def test_missing_id_rejected(self) -> None:
        """A budget line identifier is required."""
        with pytest.raises(ValidationError):
            BudgetLine(
                account_id="acc-1000",  # type: ignore[call-arg]
                amount=Decimal("1000.00"),
                period_id="2026-07",
            )

    def test_missing_amount_rejected(self) -> None:
        """A budget line amount is required."""
        with pytest.raises(ValidationError):
            BudgetLine(
                id="bl-004",
                account_id="acc-1000",
                period_id="2026-07",
            )  # type: ignore[call-arg]

    def test_invalid_version_rejected(self) -> None:
        """An unknown budget version string is rejected."""
        with pytest.raises(ValidationError):
            BudgetLine(
                id="bl-005",
                account_id="acc-1000",
                amount=Decimal("1000.00"),
                period_id="2026-07",
                version="draft", 
            )

    def test_revised_version_constructs(self) -> None:
        """A revised budget line is representable."""
        line = _line(version=BudgetVersion.REVISED)
        assert line.version == BudgetVersion.REVISED


class TestBudget:
    """Budget aggregate construction invariants."""

    def test_valid_budget_constructs(self) -> None:
        """A budget with lines constructs."""
        budget = Budget(
            id="bud-001",
            company_id="comp-001",
            fiscal_year=2026,
            version=BudgetVersion.ORIGINAL,
            lines=[_line()],
            created_at=_now(),
            updated_at=_now(),
        )
        assert budget.id == "bud-001"
        assert budget.fiscal_year == 2026
        assert len(budget.lines) == 1

    def test_empty_lines_allowed(self) -> None:
        """A budget with no lines is representable."""
        budget = Budget(
            id="bud-002",
            company_id="comp-001",
            fiscal_year=2026,
            version=BudgetVersion.ORIGINAL,
            lines=[],
            created_at=_now(),
            updated_at=_now(),
        )
        assert budget.lines == []

    def test_multiple_lines_preserved(self) -> None:
        """Multiple budget lines are preserved in order."""
        lines = [_line(line_id="bl-1"), _line(line_id="bl-2", amount=Decimal("2000.00"))]
        budget = Budget(
            id="bud-003",
            company_id="comp-001",
            fiscal_year=2026,
            version=BudgetVersion.REVISED,
            lines=lines,
            created_at=_now(),
            updated_at=_now(),
        )
        assert [line.id for line in budget.lines] == ["bl-1", "bl-2"]

    def test_missing_company_rejected(self) -> None:
        """A budget requires a company identifier."""
        with pytest.raises(ValidationError):
            Budget(
                id="bud-004",
                fiscal_year=2026,  # type: ignore[call-arg]
                version=BudgetVersion.ORIGINAL,
                lines=[],
                created_at=_now(),
                updated_at=_now(),
            )

    def test_missing_version_rejected(self) -> None:
        """A budget requires a version."""
        with pytest.raises(ValidationError):
            Budget(
                id="bud-005",
                company_id="comp-001",
                fiscal_year=2026,
                lines=[],  # type: ignore[call-arg]
                created_at=_now(),
                updated_at=_now(),
            )

    def test_missing_timestamps_rejected(self) -> None:
        """A budget requires created and updated timestamps."""
        with pytest.raises(ValidationError):
            Budget(
                id="bud-006",
                company_id="comp-001",
                fiscal_year=2026,
                version=BudgetVersion.ORIGINAL,
                lines=[],
            )  # type: ignore[call-arg]

    def test_fiscal_year_accepts_any_int(self) -> None:
        """fiscal_year has no range validator — any int is accepted.

        Note: the engine Budget model does not bound the fiscal year; period
        semantics are enforced by the canonical FiscalPeriod value object.
        """
        budget = Budget(
            id="bud-007",
            company_id="comp-001",
            fiscal_year=-2026,
            version=BudgetVersion.ORIGINAL,
            lines=[],
            created_at=_now(),
            updated_at=_now(),
        )
        assert budget.fiscal_year == -2026

    def test_adjusted_version_constructs(self) -> None:
        """An adjusted budget version is accepted."""
        budget = Budget(
            id="bud-008",
            company_id="comp-001",
            fiscal_year=2026,
            version=BudgetVersion.ADJUSTED,
            lines=[],
            created_at=_now(),
            updated_at=_now(),
        )
        assert budget.version == BudgetVersion.ADJUSTED


class TestBudgetMonetaryInvariants:
    """Monetary invariants across budget lines."""

    def test_amounts_are_decimal_not_float(self) -> None:
        """Every budget line amount is a Decimal."""
        budget = Budget(
            id="bud-010",
            company_id="comp-001",
            fiscal_year=2026,
            version=BudgetVersion.ORIGINAL,
            lines=[
                _line(amount=Decimal("100.00")),
                _line(amount=Decimal("200.00"), line_id="bl-2"),
            ],
            created_at=_now(),
            updated_at=_now(),
        )
        for line in budget.lines:
            assert isinstance(line.amount, Decimal)

    def test_amounts_quantized_to_four_places(self) -> None:
        """Budget amounts are normalized to 4 decimal places."""
        line = _line(amount=Decimal("123.45"))
        assert line.amount == Decimal("123.4500")

    def test_large_amounts_preserve_precision(self) -> None:
        """Large budget amounts do not lose precision."""
        line = _line(amount=Decimal("999999999999.99"))
        assert line.amount == Decimal("999999999999.9900")