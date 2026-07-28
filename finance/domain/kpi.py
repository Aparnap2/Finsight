"""KPI (Key Performance Indicator) domain models.

KPIs are calculated metrics derived from financial data — such as gross
margin, EBITDA margin, and revenue growth rate.  They provide a high-level
view of financial health and are tracked over time.
"""


from pydantic import BaseModel

from finance.domain._types import MoneyDecimal


class KPIDefinition(BaseModel):
    """The definition and formula for a single KPI.

    A KPI definition specifies how a metric is calculated (via a formula
    string), how it should be displayed, and whether higher values are
    better (for trend assessment).
    """

    id: str
    """Unique KPI identifier."""

    name: str
    """Canonical system name (e.g. ``\"gross_margin\"``)."""

    display_name: str
    """Human-readable label (e.g. ``\"Gross Margin\"``)."""

    category: str
    """Category grouping (e.g. ``\"profitability\"``, ``\"efficiency\"``)."""

    formula: str
    """Formula expression (e.g. ``\"(revenue - cogs) / revenue * 100\"``)."""

    unit: str = "%"
    """Unit of measurement (``\"%\"``, ``\"$\"``, ``\"count\"``, ``\"ratio\"``)."""

    higher_is_better: bool = True
    """Whether an increase in this KPI is considered favourable."""


class KPIValue(BaseModel):
    """A single observation / value of a KPI for a specific period.

    Includes the current value, prior-period comparison, change metrics,
    trend direction, target, and status for at-a-glance health assessment.
    """

    kpi_id: str
    """The KPI definition this value corresponds to."""

    kpi_name: str
    """Denormalised KPI name for display convenience."""

    value: MoneyDecimal
    """The calculated KPI value for this period."""

    period_id: str
    """The fiscal period this value was calculated for."""

    previous_value: MoneyDecimal | None = None
    """The KPI value from the prior comparable period."""

    change: MoneyDecimal | None = None
    """Absolute change from the previous value."""

    change_pct: MoneyDecimal | None = None
    """Percentage change from the previous value."""

    trend: str | None = None
    """Trend direction (``\"improving\"``, ``\"declining\"``, ``\"stable\"``)."""

    target: MoneyDecimal | None = None
    """Target value for this KPI (if defined)."""

    status: str | None = None
    """Health status (``\"on_track\"``, ``\"at_risk\"``, ``\"off_track\"``)."""


class KPI(BaseModel):
    """A complete KPI with its definition and time-series values.

    Combines the KPI definition with all observed values for a company,
    enabling trend analysis and target tracking.
    """

    definition: KPIDefinition
    """The KPI definition / formula."""

    values: list[KPIValue]
    """All observed values of this KPI (one per period)."""

    company_id: str
    """The company this KPI belongs to."""
