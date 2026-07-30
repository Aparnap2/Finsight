"""Fiscal period value object for period identification and arithmetic.

A FiscalPeriod identifies a specific time period in the financial
calendar — month, quarter, or year. It supports ordering, period
difference calculation, and generation of adjacent periods.
"""

# mypy: disable-error-code="misc,untyped-decorator"

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator

_FISCAL_YEAR_MIN = 1900
_FISCAL_YEAR_MAX = 2100


class FiscalPeriod(BaseModel):
    """A fiscal period identifier.

    Canonical string formats:
    - Monthly:  YYYY-MM    (e.g., "2026-01" for January 2026)
    - Quarterly: YYYY-QN   (e.g., "2026-Q2" for Q2 2026)
    - Annual:   FYYYYY     (e.g., "FY2026" for fiscal year 2026)

    Supports ordering, month-level subtraction, and generation of
    prior/next periods across year boundaries.

    Usage:
        jan = FiscalPeriod(2026, 1, "month")
        q1 = FiscalPeriod(2026, 1, "quarter")
        fy = FiscalPeriod(2026, 1, "year")

        str(jan)          # "2026-01"
        str(q1)           # "2026-Q1"
        str(fy)           # "FY2026"

        jan.next_period   # FiscalPeriod(2026, 2, "month")
        q1.prior_period   # FiscalPeriod(2025, 4, "quarter")

        FiscalPeriod.from_string("2026-01")  # Monthly
        FiscalPeriod.from_string("2026-Q3")  # Quarterly
        FiscalPeriod.from_string("FY2026")   # Annual
    """

    model_config = ConfigDict(frozen=True)

    year: int
    period: int
    type: Literal["month", "quarter", "year"] = "month"

    @field_validator("year")
    @classmethod
    def _validate_year(cls, v: int) -> int:
        if v < _FISCAL_YEAR_MIN or v > _FISCAL_YEAR_MAX:
            raise ValueError(
                f"Fiscal period year must be between {_FISCAL_YEAR_MIN} "
                f"and {_FISCAL_YEAR_MAX}, got {v}"
            )
        return v

    @field_validator("period")
    @classmethod
    def _validate_period(cls, v: int, info: ValidationInfo) -> int:
        """Validate period range based on fiscal period type."""
        period_type = info.data.get("type", "month")
        if period_type == "month" and (v < 1 or v > 12):
            raise ValueError(
                f"Month period must be between 1 and 12, got {v}"
            )
        if period_type == "quarter" and (v < 1 or v > 4):
            raise ValueError(
                f"Quarter period must be between 1 and 4, got {v}"
            )
        if period_type == "year" and v != 1:
            raise ValueError(
                f"Year period must be 1, got {v}"
            )
        return v

    # ── String Representations ────────────────────────────────────────────

    @property
    def period_str(self) -> str:
        """Canonical string representation: YYYY-MM, YYYY-QN, or FYYYYY."""
        match self.type:
            case "month":
                return f"{self.year}-{self.period:02d}"
            case "quarter":
                return f"{self.year}-Q{self.period}"
            case "year":
                return f"FY{self.year}"

    def __str__(self) -> str:
        return self.period_str

    @classmethod
    def from_string(cls, s: str) -> FiscalPeriod:
        """Parse a FiscalPeriod from its canonical string format.

        Supported formats:
        - "YYYY-MM"   → monthly period
        - "YYYY-QN"   → quarterly period (N = 1-4)
        - "FYYYYY"    → annual period

        Raises:
            ValueError: If the string cannot be parsed.
        """
        # YYYY-MM (monthly)
        m = re.match(r"^(\d{4})-(\d{2})$", s)
        if m:
            return cls(year=int(m.group(1)), period=int(m.group(2)), type="month")
        # YYYY-QN (quarterly)
        m = re.match(r"^(\d{4})-Q([1-4])$", s)
        if m:
            return cls(year=int(m.group(1)), period=int(m.group(2)), type="quarter")
        # FYYYYY (annual)
        m = re.match(r"^FY(\d{4})$", s)
        if m:
            return cls(year=int(m.group(1)), period=1, type="year")
        raise ValueError(f"Cannot parse FiscalPeriod from: '{s}'")

    # ── Ordering ──────────────────────────────────────────────────────────

    def _sort_key(self) -> int:
        """Sort key for ordering: year * 100 + period."""
        return self.year * 100 + self.period

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, FiscalPeriod):
            return NotImplemented
        return self._sort_key() < other._sort_key()

    # ── Period Arithmetic ─────────────────────────────────────────────────

    def __add__(self, periods: int) -> FiscalPeriod:
        """Add (or subtract) periods to get a new FiscalPeriod.

        The operation uses the native unit of the period type:
        - Months: adds/subtracts months
        - Quarters: adds/subtracts quarters
        - Years: adds/subtracts years

        All operations correctly roll across year boundaries.

        Args:
            periods: Number of periods to add (negative for subtraction).

        Usage:
            FiscalPeriod(2026, 1, "month") + 11  # FiscalPeriod(2026, 12, "month")
            FiscalPeriod(2026, 1, "month") + 12  # FiscalPeriod(2027, 1, "month")
            FiscalPeriod(2026, 1, "quarter") + 1  # FiscalPeriod(2026, 2, "quarter")
        """
        if not isinstance(periods, int):
            return NotImplemented

        if self.type == "year":
            return FiscalPeriod(year=self.year + periods, period=1, type="year")

        if self.type == "quarter":
            total_quarters = (self.year * 4 + (self.period - 1)) + periods
            new_year_val = total_quarters // 4
            new_quarter = (total_quarters % 4) + 1
            return FiscalPeriod(year=new_year_val, period=new_quarter, type="quarter")

        # Monthly
        total_months = (self.year * 12 + (self.period - 1)) + periods
        new_year_val = total_months // 12
        new_month_val = (total_months % 12) + 1
        return FiscalPeriod(year=new_year_val, period=new_month_val, type="month")

    def __sub__(self, other: FiscalPeriod) -> int:
        """Compute the month difference between two FiscalPeriods.

        Both periods must be of the same type.

        Args:
            other: The earlier FiscalPeriod.

        Returns:
            Number of periods (months/quarters/years) between them.

        Raises:
            TypeError: If period types differ.
        """
        if not isinstance(other, FiscalPeriod):
            return NotImplemented
        if self.type != other.type:
            raise TypeError(
                f"Cannot subtract {other.type} period from {self.type} period"
            )
        if self.type == "month":
            return (self.year * 12 + self.period) - (other.year * 12 + other.period)
        if self.type == "quarter":
            return (self.year * 4 + self.period) - (other.year * 4 + other.period)
        # Annual
        return self.year - other.year

    # ── Adjacent Periods ──────────────────────────────────────────────────

    @property
    def prior_period(self) -> FiscalPeriod:
        """The previous period (month, quarter, or year)."""
        return self.__add__(-1)

    @property
    def next_period(self) -> FiscalPeriod:
        """The next period (month, quarter, or year)."""
        return self.__add__(1)

    @property
    def prior_year_period(self) -> FiscalPeriod:
        """The same period in the prior fiscal year.

        Usage:
            FiscalPeriod(year=2026, period=3, type="month").prior_year_period
            # → FiscalPeriod(year=2025, period=3, type="month")
        """
        return FiscalPeriod(year=self.year - 1, period=self.period, type=self.type)

    def __hash__(self) -> int:
        return hash((self.year, self.period, self.type))
