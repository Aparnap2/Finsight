"""PeriodProgression — state advancement and lifecycle management."""
from datetime import datetime, timezone

from finance.validation.calendar import FiscalCalendar
from finance.validation.models import FiscalPeriod, PeriodStatus


class PeriodProgression:
    def advance(
        self, current_period: FiscalPeriod, calendar: FiscalCalendar
    ) -> FiscalPeriod:
        current_period.is_closed = True
        current_period.closed_at = datetime.now(timezone.utc).isoformat()
        current_period.status = PeriodStatus.LOCKED

        next_period_id = None
        for p in calendar._periods.values():
            if p.prior_period_id == current_period.id:
                next_period_id = p.id
                break

        if next_period_id is None:
            sorted_periods = sorted(
                calendar._periods.values(), key=lambda x: x.start_date
            )
            for p in sorted_periods:
                if p.start_date > current_period.start_date:
                    next_period_id = p.id
                    break

        if next_period_id is None:
            raise ValueError(
                f"No successor period found for '{current_period.id}'"
            )
        return calendar.get_period(next_period_id)

    def reopen(
        self, period: FiscalPeriod, audit_reason: str = ""
    ) -> FiscalPeriod:
        period.is_closed = False
        period.status = PeriodStatus.OPEN
        period.closed_at = None
        entry = f"REOPENED: {datetime.now(timezone.utc).isoformat()} | {audit_reason}"
        period.audit_trail.append(entry)
        return period

    @staticmethod
    def get_ytd_periods(
        period: FiscalPeriod, calendar: FiscalCalendar
    ) -> list[FiscalPeriod]:
        periods = calendar.get_periods_for_year(period.fiscal_year)
        sorted_periods = sorted(periods, key=lambda p: p.fiscal_period)
        return [p for p in sorted_periods if p.fiscal_period <= period.fiscal_period]
