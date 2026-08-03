"""KPI (Key Performance Indicator) ontology models.

Defines KPI metadata, categories, and computed values for the
FP&A platform. KPIs are the primary metrics used to measure
financial and operational performance.
"""

# mypy: disable-error-code="misc,untyped-decorator"

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator

from business.canonical_types import FiscalPeriod, Money, Percentage


class KPICategory(BaseModel):
    """A category grouping related KPIs.

    Categories organize KPIs into logical groups such as Profitability,
    Liquidity, Efficiency, or Revenue.

    Usage:
        profitability = KPICategory(
            name="Profitability",
            description="Measures of profit generation efficiency",
        )
    """

    model_config = ConfigDict(frozen=True)

    name: str
    description: str = ""

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("KPI category name cannot be empty")
        return v.strip()

    def __str__(self) -> str:
        return self.name


class KPI(BaseModel):
    """A Key Performance Indicator definition with metadata.

    Represents the canonical definition of a KPI, including its formula,
    data type, category, owner, and version. This is the metadata layer
    — the computed value is stored in KPIValue.

    Usage:
        gross_margin = KPI(
            kpi_id="gross_margin",
            name="Gross Margin",
            description="Gross profit as a percentage of revenue",
            category=KPICategory(name="Profitability"),
            data_type="Percentage",
            formula_expression="(Revenue - COGS) / Revenue",
            owner="FP&A Team",
            version="1.0.0",
        )
    """

    kpi_id: str
    name: str
    description: str = ""
    category: KPICategory = KPICategory(name="Uncategorized")
    data_type: str = "Money"  # "Money", "Percentage", "Ratio", "Count", "Days"
    formula_expression: str = ""
    unit: str = ""  # "USD", "EUR", "%", "days", "count"
    numerator_fields: list[str] = []
    denominator_fields: list[str] = []
    depends_on: list[str] = []  # Other KPI IDs this depends on
    owner: str = ""
    steward: str = ""
    version: str = "1.0.0"
    valid_from: date | None = None
    valid_until: date | None = None
    tags: list[str] = []
    sox_relevant: bool = False
    classification: str = "internal"

    @field_validator("kpi_id")
    @classmethod
    def _validate_kpi_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("KPI ID cannot be empty")
        return v.strip()

    @field_validator("data_type")
    @classmethod
    def _validate_data_type(cls, v: str) -> str:
        allowed = {"Money", "Percentage", "Ratio", "Count", "Days", "Score"}
        if v not in allowed:
            raise ValueError(
                f"KPI data_type must be one of {allowed}, got '{v}'"
            )
        return v

    @field_validator("classification")
    @classmethod
    def _validate_classification(cls, v: str) -> str:
        allowed = {"public", "internal", "confidential", "restricted"}
        if v.lower() not in allowed:
            raise ValueError(
                f"KPI classification must be one of {allowed}, got '{v}'"
            )
        return v.lower()

    def is_active(self, as_of: date | None = None) -> bool:
        """Check whether this KPI definition is active on a given date.

        Args:
            as_of: The date to check (defaults to today).

        Returns:
            True if the KPI is valid on the given date.
        """
        check_date = as_of or date.today()
        return not (
            (self.valid_from is not None and check_date < self.valid_from)
            or (self.valid_until is not None and check_date > self.valid_until)
        )

    def __str__(self) -> str:
        return (
            f"KPI({self.kpi_id}, {self.name}, "
            f"v{self.version}, {self.data_type})"
        )


class KPIValue(BaseModel):
    """A computed KPI value for a specific period and entity.

    Represents the result of evaluating a KPI definition against
    actual financial data for a given period.

    Usage:
        value = KPIValue(
            kpi_id="gross_margin",
            period=FiscalPeriod(2026, 6, "month"),
            entity_id="US-CORP",
            value_money=Money(Decimal("1500000.00"), CurrencyCode("USD")),
            value_percentage=Percentage.from_decimal(Decimal("0.35")),
            status="actual",
        )
    """

    kpi_id: str
    name: str = ""
    period: FiscalPeriod
    entity_id: str = ""
    value_money: Money | None = None
    value_percentage: Percentage | None = None
    value_decimal: Decimal | None = None
    value_integer: int | None = None
    status: str = "actual"  # "actual", "budget", "forecast", "target"
    change_vs_prior: Percentage | None = None
    change_vs_budget: Percentage | None = None
    trend: str = "stable"  # "improving", "declining", "stable"
    confidence: float | None = None

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v: str) -> str:
        allowed = {"actual", "budget", "forecast", "target", "projected"}
        if v.lower() not in allowed:
            raise ValueError(
                f"KPI value status must be one of {allowed}, got '{v}'"
            )
        return v.lower()

    @field_validator("trend")
    @classmethod
    def _validate_trend(cls, v: str) -> str:
        allowed = {"improving", "declining", "stable", "volatile"}
        if v.lower() not in allowed:
            raise ValueError(
                f"KPI trend must be one of {allowed}, got '{v}'"
            )
        return v.lower()

    def __str__(self) -> str:
        display_value = (
            self.value_money
            or self.value_percentage
            or self.value_decimal
            or self.value_integer
            or "N/A"
        )
        return (
            f"KPIValue({self.kpi_id}, {self.period}, "
            f"{display_value}, {self.status})"
        )
