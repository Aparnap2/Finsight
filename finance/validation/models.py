"""Financial Period domain models."""
from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field


class PeriodStatus(StrEnum):
    OPEN = "open"
    CLOSING = "closing"
    VALIDATING = "validating"
    ANALYZING = "analyzing"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    LOCKED = "locked"


class PeriodType(StrEnum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


class FiscalPeriod(BaseModel):
    id: str
    tenant_id: str
    fiscal_year: int
    fiscal_period: int  # 1-12 for monthly, 1-4 for quarterly
    period_type: PeriodType
    start_date: date
    end_date: date
    status: PeriodStatus = PeriodStatus.OPEN
    prior_period_id: str | None = None
    prior_year_period_id: str | None = None
    is_closed: bool = False
    closed_at: str | None = None
    audit_trail: list[str] = Field(default_factory=list)
