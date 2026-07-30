"""Budget and forecast ontology models.

Represents financial planning documents: budgets (approved financial
targets set before the period begins) and forecasts (updated projections
that replace budgets during the fiscal year).
"""

# mypy: disable-error-code="misc,untyped-decorator"

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, field_validator

from business.canonical_types import (
    CostCenter,
    Department,
    FiscalPeriod,
    GLAccountNumber,
    Money,
)


class BudgetLine(BaseModel):
    """A single line item in a budget.

    Represents the planned amount for a specific GL account, cost center,
    and department combination within a fiscal period.

    Usage:
        line = BudgetLine(
            account=GLAccountNumber("6010"),
            amount=Money(Decimal("50000.00"), CurrencyCode("USD")),
            period=FiscalPeriod(2026, 1, "month"),
            cost_center=CostCenter("ENG"),
            department=Department("ENGINEERING"),
        )
    """

    account: GLAccountNumber
    amount: Money
    period: FiscalPeriod
    cost_center: CostCenter | None = None
    department: Department | None = None
    description: str = ""

    def __str__(self) -> str:
        return (
            f"BudgetLine({self.account}, {self.amount}, "
            f"{self.period})"
        )


class Budget(BaseModel):
    """A financial budget for a specific entity and fiscal year.

    A budget is a financial plan approved by management that allocates
    resources and sets performance targets before the fiscal period begins.
    Budgets are compared against actuals during variance analysis.

    Usage:
        budget = Budget(
            budget_id="BUD-2026-001",
            name="FY2026 Operating Budget",
            entity_id="US-CORP",
            fiscal_year=2026,
            version="1.0",
            status="approved",
            lines=[...],
        )
    """

    budget_id: str
    name: str
    entity_id: str
    fiscal_year: int
    version: str = "1.0"
    status: str = "draft"
    lines: list[BudgetLine] = []
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("budget_id")
    @classmethod
    def _validate_budget_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Budget ID cannot be empty")
        return v.strip()

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v: str) -> str:
        allowed = {"draft", "review", "approved", "revised", "archived"}
        if v.lower() not in allowed:
            raise ValueError(
                f"Budget status must be one of {allowed}, got '{v}'"
            )
        return v.lower()

    @property
    def total_amount(self) -> Money | None:
        """Total budget amount across all lines."""
        if not self.lines:
            return None
        total = self.lines[0].amount
        for line in self.lines[1:]:
            total = total + line.amount
        return total

    def lines_for_period(self, period: FiscalPeriod) -> list[BudgetLine]:
        """Get all budget lines for a specific fiscal period.

        Args:
            period: The fiscal period to filter by.

        Returns:
            Budget lines matching the given period.
        """
        return [line for line in self.lines if line.period == period]

    def __str__(self) -> str:
        return (
            f"Budget({self.budget_id}, {self.name}, "
            f"FY{self.fiscal_year}, {self.status})"
        )


class ForecastLine(BaseModel):
    """A single line item in a forecast.

    Forecast lines represent projected amounts with higher granularity
    than budget lines, often including confidence intervals and driver
    references.

    Usage:
        line = ForecastLine(
            account=GLAccountNumber("4010"),
            amount=Money(Decimal("120000.00"), CurrencyCode("USD")),
            period=FiscalPeriod(2026, 7, "month"),
            confidence_lower=Money(Decimal("110000.00"), CurrencyCode("USD")),
            confidence_upper=Money(Decimal("130000.00"), CurrencyCode("USD")),
        )
    """

    account: GLAccountNumber
    amount: Money
    period: FiscalPeriod
    cost_center: CostCenter | None = None
    department: Department | None = None
    description: str = ""
    confidence_lower: Money | None = None
    confidence_upper: Money | None = None
    driver_name: str = ""
    driver_value: float | None = None  # Operational driver value (not monetary)

    def __str__(self) -> str:
        return (
            f"ForecastLine({self.account}, {self.amount}, "
            f"{self.period})"
        )


class Forecast(BaseModel):
    """A financial forecast for a specific entity and horizon.

    A forecast is an updated projection of financial performance, typically
    more frequent than the annual budget cycle. Forecasts may use driver-based
    modeling and often include confidence intervals.

    Usage:
        forecast = Forecast(
            forecast_id="FORECAST-2026-Q3",
            name="Q3 2026 Rolling Forecast",
            entity_id="US-CORP",
            version="3",
            status="published",
            lines=[...],
        )
    """

    forecast_id: str
    name: str
    entity_id: str
    version: str = "1.0"
    status: str = "draft"
    lines: list[ForecastLine] = []
    created_at: datetime | None = None
    updated_at: datetime | None = None
    published_at: datetime | None = None

    @field_validator("forecast_id")
    @classmethod
    def _validate_forecast_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Forecast ID cannot be empty")
        return v.strip()

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v: str) -> str:
        allowed = {"draft", "review", "published", "superseded", "archived"}
        if v.lower() not in allowed:
            raise ValueError(
                f"Forecast status must be one of {allowed}, got '{v}'"
            )
        return v.lower()

    @property
    def total_amount(self) -> Money | None:
        """Total forecast amount across all lines."""
        if not self.lines:
            return None
        total = self.lines[0].amount
        for line in self.lines[1:]:
            total = total + line.amount
        return total

    def lines_for_period(self, period: FiscalPeriod) -> list[ForecastLine]:
        """Get all forecast lines for a specific fiscal period."""
        return [line for line in self.lines if line.period == period]

    def __str__(self) -> str:
        return (
            f"Forecast({self.forecast_id}, {self.name}, "
            f"v{self.version}, {self.status})"
        )
