"""FiscalCalendar — period generation, lookup, and navigation."""
from datetime import date, timedelta

from finance.validation.models import FiscalPeriod, PeriodStatus, PeriodType


def _last_day_of_month(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


class FiscalCalendar:
    """Manages fiscal period generation, lookup, and navigation."""

    def __init__(self, fiscal_year_start_month: int = 1):
        self.fiscal_year_start_month = fiscal_year_start_month
        self._periods: dict[str, FiscalPeriod] = {}

    def generate_periods(
        self, year: int, period_type: PeriodType = PeriodType.MONTHLY
    ) -> list[FiscalPeriod]:
        periods: list[FiscalPeriod] = []
        if period_type == PeriodType.MONTHLY:
            periods = self._generate_monthly(year)
        elif period_type == PeriodType.QUARTERLY:
            periods = self._generate_quarterly(year)
        elif period_type == PeriodType.YEARLY:
            periods = self._generate_yearly(year)
        self._link_periods(periods)
        for p in periods:
            self._periods[p.id] = p
        # Re-link prior-year references across all stored periods
        for p in self._periods.values():
            self._link_prior_year(p)
        return periods

    def _generate_monthly(self, year: int) -> list[FiscalPeriod]:
        periods: list[FiscalPeriod] = []
        sm = self.fiscal_year_start_month
        for i in range(12):
            cal_month = ((sm - 1 + i) % 12) + 1
            # Prior-year months (sm > 1) belong to the previous fiscal year
            cal_year = year - 1 if sm != 1 and i < (12 - sm + 1) else year
            period_start = date(cal_year, cal_month, 1)
            period_end = _last_day_of_month(cal_year, cal_month)
            fp = FiscalPeriod(
                id=f"{year}-{i + 1:02d}",
                tenant_id="default",
                fiscal_year=year,
                fiscal_period=i + 1,
                period_type=PeriodType.MONTHLY,
                start_date=period_start,
                end_date=period_end,
                status=PeriodStatus.OPEN,
            )
            periods.append(fp)
        return periods

    def _generate_quarterly(self, year: int) -> list[FiscalPeriod]:
        q_start = {1: 1, 2: 4, 3: 7, 4: 10}
        periods = []
        for q in range(1, 5):
            sm = q_start[q]
            em = sm + 2
            cal_year_sm = year
            cal_year_em = year
            start_date = date(cal_year_sm, sm, 1)
            end_date = _last_day_of_month(cal_year_em, em)
            fp = FiscalPeriod(
                id=f"{year}-Q{q}",
                tenant_id="default",
                fiscal_year=year,
                fiscal_period=q,
                period_type=PeriodType.QUARTERLY,
                start_date=start_date,
                end_date=end_date,
                status=PeriodStatus.OPEN,
            )
            periods.append(fp)
        return periods

    def _generate_yearly(self, year: int) -> list[FiscalPeriod]:
        sm = self.fiscal_year_start_month
        cal_year = year if sm == 1 else year - 1
        start_date = date(cal_year, sm, 1)
        end_month = sm - 1 if sm > 1 else 12
        end_year = year if end_month < sm else year
        end_date = _last_day_of_month(end_year, end_month)
        fp = FiscalPeriod(
            id=f"{year}",
            tenant_id="default",
            fiscal_year=year,
            fiscal_period=1,
            period_type=PeriodType.YEARLY,
            start_date=start_date,
            end_date=end_date,
            status=PeriodStatus.OPEN,
        )
        self._periods[fp.id] = fp
        return [fp]

    def _link_periods(self, periods: list[FiscalPeriod]) -> None:
        for i, p in enumerate(periods):
            if i > 0:
                prev = periods[i - 1]
                if p.fiscal_year == prev.fiscal_year:
                    p.prior_period_id = prev.id
            self._link_prior_year(p)

    def _link_prior_year(self, p: FiscalPeriod) -> None:
        prior_key = self._prior_year_key(p)
        if prior_key in self._periods:
            p.prior_year_period_id = prior_key

    @staticmethod
    def _prior_year_key(p: FiscalPeriod) -> str:
        if p.period_type == PeriodType.MONTHLY:
            return f"{p.fiscal_year - 1}-{p.fiscal_period:02d}"
        if p.period_type == PeriodType.QUARTERLY:
            return f"{p.fiscal_year - 1}-Q{p.fiscal_period}"
        return f"{p.fiscal_year - 1}"

    def get_period(self, period_id: str) -> FiscalPeriod:
        if period_id not in self._periods:
            raise KeyError(f"Period '{period_id}' not found")
        return self._periods[period_id]

    def get_period_for_date(self, target: date) -> FiscalPeriod:
        for p in self._periods.values():
            if p.start_date <= target <= p.end_date:
                return p
        raise ValueError(f"No period found for date {target}")

    def get_prior_period(self, period_id: str) -> FiscalPeriod | None:
        p = self.get_period(period_id)
        if p.prior_period_id:
            return self._periods.get(p.prior_period_id)
        return None

    def get_periods_for_year(self, year: int) -> list[FiscalPeriod]:
        return [p for p in self._periods.values() if p.fiscal_year == year]

    def get_range(self, start_id: str, end_id: str) -> list[FiscalPeriod]:
        if start_id not in self._periods or end_id not in self._periods:
            return []
        keys = sorted(self._periods.keys())
        if start_id > end_id:
            return []
        start_idx = keys.index(start_id)
        end_idx = keys.index(end_id)
        return [self._periods[k] for k in keys[start_idx : end_idx + 1]]
