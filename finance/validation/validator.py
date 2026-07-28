"""PeriodValidator — validates fiscal period consistency."""
from finance.validation.calendar import FiscalCalendar
from finance.validation.models import FiscalPeriod
from pydantic import BaseModel


class PeriodValidationResult(BaseModel):
    period_id: str
    is_valid: bool
    errors: list[str] = []
    warnings: list[str] = []
    overlapping_periods: list[str] = []
    missing_periods: list[str] = []


class PeriodValidator:
    def validate_period(
        self, period: FiscalPeriod, calendar: FiscalCalendar
    ) -> PeriodValidationResult:
        errors: list[str] = []
        warnings: list[str] = []
        overlapping: list[str] = []

        if period.start_date >= period.end_date:
            errors.append("Start date must be before end date")

        if self.check_overlapping(period, calendar):
            overlapping = self._find_overlapping_ids(period, calendar)
            errors.append(f"Period overlaps with: {', '.join(overlapping)}")

        is_valid = len(errors) == 0
        return PeriodValidationResult(
            period_id=period.id,
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            overlapping_periods=overlapping,
        )

    def validate_year(
        self, year: int, calendar: FiscalCalendar
    ) -> list[PeriodValidationResult]:
        year_periods = calendar.get_periods_for_year(year)
        results = [self.validate_period(p, calendar) for p in year_periods]

        gaps = self.check_gaps(year, calendar)
        if gaps:
            gap_ids = [g.id for g in gaps]
            results.append(
                PeriodValidationResult(
                    period_id=str(year),
                    is_valid=False,
                    errors=["Missing periods detected"],
                    missing_periods=gap_ids,
                )
            )
        return results

    def check_overlapping(
        self, period: FiscalPeriod, calendar: FiscalCalendar
    ) -> bool:
        for p in calendar._periods.values():
            if p.id == period.id:
                continue
            if p.start_date < period.end_date and period.start_date < p.end_date:
                return True
        return False

    def _find_overlapping_ids(
        self, period: FiscalPeriod, calendar: FiscalCalendar
    ) -> list[str]:
        overlapping: list[str] = []
        for p in calendar._periods.values():
            if p.id == period.id:
                continue
            if p.start_date < period.end_date and period.start_date < p.end_date:
                overlapping.append(p.id)
        return overlapping

    def check_gaps(
        self, year: int, calendar: FiscalCalendar
    ) -> list[FiscalPeriod]:
        year_periods = calendar.get_periods_for_year(year)
        if not year_periods:
            return []
        sorted_periods = sorted(year_periods, key=lambda p: p.start_date)
        gaps: list[FiscalPeriod] = []
        for i in range(len(sorted_periods) - 1):
            current = sorted_periods[i]
            next_p = sorted_periods[i + 1]
            expected_next_start = current.end_date + __import__("datetime").timedelta(days=1)
            if next_p.start_date != expected_next_start:
                if next_p.start_date > expected_next_start:
                    prev_end = current.end_date
                    gap_id = f"gap_{prev_end.isoformat()}"
                    gap = FiscalPeriod(
                        id=gap_id,
                        tenant_id="default",
                        fiscal_year=year,
                        fiscal_period=0,
                        period_type=current.period_type,
                        start_date=expected_next_start,
                        end_date=next_p.start_date - __import__("datetime").timedelta(days=1),
                        status=__import__("finance.validation.models", fromlist=["PeriodStatus"]).PeriodStatus.OPEN,
                    )
                    gaps.append(gap)
        return gaps
