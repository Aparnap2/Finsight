"""Tests for Financial Calendar + Period Model.

TDD: Tests written first (Red), then implemented (Green).
"""
from datetime import date, datetime

from finance.validation.calendar import FiscalCalendar
from finance.validation.models import (
    FiscalPeriod,
    PeriodStatus,
    PeriodType,
)
from finance.validation.progression import PeriodProgression
from finance.validation.validator import PeriodValidator

# =============================================================================
# Period Model & Calendar Tests
# =============================================================================


class TestFiscalCalendar:
    """FiscalCalendar period generation and lookup."""

    def test_generate_monthly_periods(self) -> None:
        """Generate all 12 months for 2026."""
        cal = FiscalCalendar()
        periods = cal.generate_periods(2026, PeriodType.MONTHLY)

        assert len(periods) == 12
        for p in periods:
            assert p.fiscal_year == 2026
            assert p.period_type == PeriodType.MONTHLY
            assert 1 <= p.fiscal_period <= 12
            assert p.status == PeriodStatus.OPEN

        # First period validation
        jan = periods[0]
        assert jan.fiscal_period == 1
        assert jan.id == "2026-01"
        assert jan.start_date == date(2026, 1, 1)
        assert jan.end_date == date(2026, 1, 31)
        assert jan.prior_period_id is None

        # Last period validation
        dec = periods[11]
        assert dec.fiscal_period == 12
        assert dec.id == "2026-12"
        assert dec.start_date == date(2026, 12, 1)
        assert dec.end_date == date(2026, 12, 31)

    def test_get_period_for_date(self) -> None:
        """Jan 15 → January period."""
        cal = FiscalCalendar()
        cal.generate_periods(2026, PeriodType.MONTHLY)
        period = cal.get_period_for_date(date(2026, 1, 15))
        assert period.id == "2026-01"
        assert period.fiscal_period == 1
        assert period.start_date == date(2026, 1, 1)
        assert period.end_date == date(2026, 1, 31)

    def test_get_prior_period(self) -> None:
        """February → January."""
        cal = FiscalCalendar()
        cal.generate_periods(2026, PeriodType.MONTHLY)
        prior = cal.get_prior_period("2026-02")
        assert prior is not None
        assert prior.id == "2026-01"
        assert prior.fiscal_period == 1

    def test_get_periods_for_year(self) -> None:
        """All 12 periods returned."""
        cal = FiscalCalendar()
        cal.generate_periods(2026, PeriodType.MONTHLY)
        periods = cal.get_periods_for_year(2026)
        assert len(periods) == 12
        assert all(p.fiscal_year == 2026 for p in periods)

    def test_prior_year_period(self) -> None:
        """Feb 2026 → Feb 2025."""
        cal = FiscalCalendar()
        cal.generate_periods(2026, PeriodType.MONTHLY)
        cal.generate_periods(2025, PeriodType.MONTHLY)
        feb_2026 = cal.get_period("2026-02")
        assert feb_2026.prior_year_period_id == "2025-02"

    def test_fiscal_calendar_july_start(self) -> None:
        """Fiscal year starting in July."""
        cal = FiscalCalendar(fiscal_year_start_month=7)
        periods = cal.generate_periods(2026, PeriodType.MONTHLY)

        assert len(periods) == 12

        # Period 1 should be July 2025
        p1 = periods[0]
        assert p1.fiscal_period == 1
        assert p1.start_date == date(2025, 7, 1)
        assert p1.end_date == date(2025, 7, 31)
        assert p1.id == "2026-01"

        # Period 6 should be December 2025
        p6 = periods[5]
        assert p6.fiscal_period == 6
        assert p6.start_date == date(2025, 12, 1)
        assert p6.end_date == date(2025, 12, 31)

        # Period 7 should be January 2026
        p7 = periods[6]
        assert p7.fiscal_period == 7
        assert p7.start_date == date(2026, 1, 1)
        assert p7.end_date == date(2026, 1, 31)

        # Period 12 should be June 2026
        p12 = periods[11]
        assert p12.fiscal_period == 12
        assert p12.start_date == date(2026, 6, 1)
        assert p12.end_date == date(2026, 6, 30)
        assert p12.id == "2026-12"

    def test_fiscal_calendar_quarterly(self) -> None:
        """Quarterly period generation."""
        cal = FiscalCalendar()
        periods = cal.generate_periods(2026, PeriodType.QUARTERLY)

        assert len(periods) == 4

        assert periods[0].id == "2026-Q1"
        assert periods[0].start_date == date(2026, 1, 1)
        assert periods[0].end_date == date(2026, 3, 31)

        assert periods[1].id == "2026-Q2"
        assert periods[1].start_date == date(2026, 4, 1)
        assert periods[1].end_date == date(2026, 6, 30)

        assert periods[2].id == "2026-Q3"
        assert periods[2].start_date == date(2026, 7, 1)
        assert periods[2].end_date == date(2026, 9, 30)

        assert periods[3].id == "2026-Q4"
        assert periods[3].start_date == date(2026, 10, 1)
        assert periods[3].end_date == date(2026, 12, 31)

        # All should be quarterly type
        assert all(p.period_type == PeriodType.QUARTERLY for p in periods)

        # Prior period chain
        assert periods[0].prior_period_id is None
        assert periods[1].prior_period_id == "2026-Q1"
        assert periods[2].prior_period_id == "2026-Q2"
        assert periods[3].prior_period_id == "2026-Q3"

    def test_get_range(self) -> None:
        """Range between two periods."""
        cal = FiscalCalendar()
        cal.generate_periods(2026, PeriodType.MONTHLY)
        result = cal.get_range("2026-01", "2026-03")
        assert len(result) == 3
        assert [p.id for p in result] == ["2026-01", "2026-02", "2026-03"]

    def test_get_range_reverse_order(self) -> None:
        """Range works even if start > end (returns empty list)."""
        cal = FiscalCalendar()
        cal.generate_periods(2026, PeriodType.MONTHLY)
        result = cal.get_range("2026-03", "2026-01")
        # Should be empty or raise; we choose empty for robustness
        assert result == []

    def test_period_status_transitions(self) -> None:
        """OPEN→CLOSING→VALIDATING→COMPLETED."""
        p = FiscalPeriod(
            id="2026-01",
            tenant_id="test",
            fiscal_year=2026,
            fiscal_period=1,
            period_type=PeriodType.MONTHLY,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
            status=PeriodStatus.OPEN,
        )
        assert p.status == PeriodStatus.OPEN

        p.status = PeriodStatus.CLOSING
        assert p.status == PeriodStatus.CLOSING

        p.status = PeriodStatus.VALIDATING
        assert p.status == PeriodStatus.VALIDATING

        p.status = PeriodStatus.ANALYZING
        assert p.status == PeriodStatus.ANALYZING

        p.status = PeriodStatus.REVIEWING
        assert p.status == PeriodStatus.REVIEWING

        p.status = PeriodStatus.COMPLETED
        assert p.status == PeriodStatus.COMPLETED

        p.status = PeriodStatus.LOCKED
        assert p.status == PeriodStatus.LOCKED

    def test_decimal_not_needed(self) -> None:
        """Calendar uses dates and ints, no Decimal issues."""
        cal = FiscalCalendar()
        periods = cal.generate_periods(2026, PeriodType.MONTHLY)
        for p in periods:
            assert isinstance(p.fiscal_year, int)
            assert isinstance(p.fiscal_period, int)
            assert isinstance(p.start_date, date)
            assert isinstance(p.end_date, date)
            # Verify no decimal creeping into core fields
            assert not isinstance(p.fiscal_year, float)
            assert not isinstance(p.fiscal_period, float)


# =============================================================================
# Period Validator Tests
# =============================================================================


class TestPeriodValidator:
    """PeriodValidator validation logic."""

    def test_validate_valid_period(self) -> None:
        """No errors for valid period."""
        cal = FiscalCalendar()
        cal.generate_periods(2026, PeriodType.MONTHLY)
        validator = PeriodValidator()
        result = validator.validate_period(cal.get_period("2026-01"), cal)

        assert result.is_valid
        assert len(result.errors) == 0
        assert result.period_id == "2026-01"

    def test_validate_overlapping_periods(self) -> None:
        """Detect overlap."""
        cal = FiscalCalendar()
        cal.generate_periods(2026, PeriodType.MONTHLY)
        validator = PeriodValidator()

        # Add an overlapping manual period
        overlapping = FiscalPeriod(
            id="overlap-2026-01",
            tenant_id="test",
            fiscal_year=2026,
            fiscal_period=1,
            period_type=PeriodType.MONTHLY,
            start_date=date(2026, 1, 15),
            end_date=date(2026, 2, 15),
            status=PeriodStatus.OPEN,
        )
        cal._periods["overlap-2026-01"] = overlapping

        result = validator.validate_period(overlapping, cal)
        assert not result.is_valid
        assert any("overlap" in err.lower() for err in result.errors)
        # Should list which periods overlap
        assert len(result.overlapping_periods) > 0

    def test_validate_missing_periods(self) -> None:
        """Detect gaps."""
        cal = FiscalCalendar()
        cal.generate_periods(2026, PeriodType.MONTHLY)
        validator = PeriodValidator()

        # Remove June to create a gap
        del cal._periods["2026-06"]

        results = validator.validate_year(2026, cal)
        # At least one result should report missing periods
        missing_found = any(len(r.missing_periods) > 0 for r in results)
        assert missing_found, "Expected at least one validation result to report missing periods"


# =============================================================================
# Period Progression Tests
# =============================================================================


class TestPeriodProgression:
    """PeriodProgression state advancement."""

    def test_period_progression_advance(self) -> None:
        """Close current period and return next period."""
        cal = FiscalCalendar()
        periods = cal.generate_periods(2026, PeriodType.MONTHLY)
        jan = periods[0]
        progression = PeriodProgression()

        feb = progression.advance(jan, cal)

        # Should return the next period
        assert feb is not None
        assert feb.id == "2026-02"

        # Jan should now be closed
        assert jan.is_closed is True
        assert jan.closed_at is not None
        assert jan.status == PeriodStatus.LOCKED

    def test_period_progression_ytd(self) -> None:
        """Year-to-date periods."""
        cal = FiscalCalendar()
        cal.generate_periods(2026, PeriodType.MONTHLY)
        june = cal.get_period("2026-06")
        progression = PeriodProgression()

        ytd = progression.get_ytd_periods(june, cal)

        assert len(ytd) == 6
        assert ytd[0].id == "2026-01"
        assert ytd[-1].id == "2026-06"
        # Verify order
        assert [p.fiscal_period for p in ytd] == [1, 2, 3, 4, 5, 6]

    def test_advance_preserves_audit_trail(self) -> None:
        """Advance sets closed_at ISO timestamp."""
        cal = FiscalCalendar()
        periods = cal.generate_periods(2026, PeriodType.MONTHLY)
        jan = periods[0]
        progression = PeriodProgression()

        progression.advance(jan, cal)

        assert jan.is_closed is True
        assert jan.closed_at is not None
        assert isinstance(jan.closed_at, str)
        # Verify it's a valid ISO format timestamp
        parsed = datetime.fromisoformat(jan.closed_at)
        assert parsed is not None  # no parse error

    def test_reopen_logs_audit(self) -> None:
        """Reopening requires audit entry."""
        cal = FiscalCalendar()
        periods = cal.generate_periods(2026, PeriodType.MONTHLY)
        jan = periods[0]
        # Manually close it first
        jan.is_closed = True
        jan.status = PeriodStatus.COMPLETED

        progression = PeriodProgression()
        reopened = progression.reopen(jan, audit_reason="Data correction needed")

        assert reopened.is_closed is False
        assert reopened.status == PeriodStatus.OPEN
        # Audit trail should contain the reason
        assert reopened.audit_trail is not None
        assert len(reopened.audit_trail) > 0
        assert any("Data correction needed" in entry for entry in reopened.audit_trail)
