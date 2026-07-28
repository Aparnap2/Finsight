"""Company domain model.

A **Company** represents the legal entity being analysed within FinSight.
It is the top-level organisational anchor that scopes all financial data,
budgets, forecasts, variances, and commentary.
"""

from datetime import datetime

from pydantic import BaseModel, field_validator


class Company(BaseModel):
    """A legal entity whose financial data is managed by the FinSight platform.

    Every analysis run, assertion, and recommendation belongs to exactly one
    company.  In multi-entity deployments each legal entity is modelled as an
    independent company; consolidation is handled at the reporting layer.
    """

    id: str
    """Unique tenant identifier (e.g. ``\"CF001\"``)."""

    name: str
    """Legal entity name for display and reporting purposes."""

    currency: str = "USD"
    """Base reporting currency (ISO 4217)."""

    fiscal_year_start: str = "01-01"
    """Fiscal year start in ``MM-DD`` format (e.g. ``\"01-01\"`` for calendar year)."""

    created_at: datetime
    """Timestamp when the company record was created."""

    updated_at: datetime
    """Timestamp when the company record was last updated."""

    @field_validator("fiscal_year_start")
    @classmethod
    def validate_fiscal_year_start(cls, v: str) -> str:
        """Ensure ``fiscal_year_start`` is in ``MM-DD`` format."""
        parts = v.split("-")
        if len(parts) != 2:
            raise ValueError("fiscal_year_start must be in MM-DD format")
        mm, dd = parts
        if not (mm.isdigit() and dd.isdigit()):
            raise ValueError("fiscal_year_start must be in MM-DD format (digits only)")
        month = int(mm)
        day = int(dd)
        if not (1 <= month <= 12):
            raise ValueError("Month in fiscal_year_start must be between 01 and 12")
        if not (1 <= day <= 31):
            raise ValueError("Day in fiscal_year_start must be between 01 and 31")
        return v
