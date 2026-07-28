"""Fiscal calendar domain models.

Defines the period structure for a company's fiscal year, including monthly,
quarterly, and annual periods.  All financial data (actuals, budgets,
forecasts) is posted to specific fiscal periods.
"""

from datetime import date
from enum import StrEnum

from pydantic import BaseModel


class FiscalPeriodType(StrEnum):
    """Granularity of a fiscal period."""

    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"


class FiscalPeriod(BaseModel):
    """A single fiscal period within a company's calendar.

    Periods represent time buckets (month / quarter / year) to which
    financial data is posted.  They are the common time dimension across
    actuals, budgets, and forecasts.
    """

    id: str
    """Unique period identifier (e.g. ``\"2026-01\"`` for January 2026)."""

    fiscal_year: int
    """The fiscal year this period belongs to."""

    period_number: int
    """Ordinal within the fiscal year: 1-12 for monthly, 1-4 for quarterly."""

    period_type: FiscalPeriodType
    """Whether this is a monthly, quarterly, or annual period."""

    start_date: date
    """Calendar start date of the period."""

    end_date: date
    """Calendar end date of the period."""

    is_closed: bool = False
    """Whether the period has been closed (prevents new postings)."""


class FiscalCalendar(BaseModel):
    """A company's complete set of fiscal periods.

    The calendar defines all time boundaries for budgeting, forecasting,
    and variance analysis.  A company has exactly one active fiscal calendar.
    """

    id: str
    """Unique calendar identifier."""

    company_id: str
    """The company this calendar belongs to."""

    periods: list[FiscalPeriod]
    """All periods defined for this calendar."""

    current_period_id: str | None = None
    """The currently-active period (used as the default analysis anchor)."""
