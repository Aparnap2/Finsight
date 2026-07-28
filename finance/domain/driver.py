"""Driver domain models.

Drivers are the operational and macro factors that influence financial
outcomes — such as headcount, ARR, or exchange rates.  The Driver Tree
represents how drivers cascade and contribute to variance explanations.
"""

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel

from finance.domain._types import MoneyDecimal


class DriverType(StrEnum):
    """Classification of a financial driver."""

    REVENUE = "revenue"
    """A driver that primarily affects revenue (e.g. ARR, deal volume)."""

    COST = "cost"
    """A driver that primarily affects costs (e.g. headcount, COGS ratio)."""

    OPERATIONAL = "operational"
    """A non-financial operational metric (e.g. utilisation rate, NPS)."""

    MACRO = "macro"
    """An external / macro-economic factor (e.g. FX rate, inflation)."""


class Driver(BaseModel):
    """An operational or financial driver that impacts performance.

    Drivers are the "levers" that explain why a variance occurred.  Each
    driver has a current value, prior value (for comparison), and optional
    correlation with related accounts.
    """

    id: str
    """Unique driver identifier."""

    name: str
    """Driver name (e.g. ``\"Headcount\"``, ``\"ARR\"``)."""

    type: DriverType
    """Classification of the driver."""

    description: str
    """Narrative description of what this driver represents."""

    unit: str
    """Unit of measurement (e.g. ``\"headcount\"``, ``\"ARR\"``, ``\"sqft\"``)."""

    value: MoneyDecimal
    """The current value of this driver."""

    previous_value: MoneyDecimal | None = None
    """The prior-period value for comparison."""

    change_pct: MoneyDecimal | None = None
    """Percentage change from the previous value."""

    related_account_codes: list[str] = []
    """Account codes that this driver is correlated with."""

    correlation: MoneyDecimal | None = None
    """Correlation coefficient between the driver and related accounts."""


class DriverTree(BaseModel):
    """A hierarchical tree of drivers showing contribution weights.

    The driver tree decomposes a variance into its root drivers.  Each
    child driver has a ``weight`` indicating its contribution to the
    parent driver's total impact.
    """

    root_driver: Driver
    """The top-level driver in this tree branch."""

    children: list["DriverTree"] = []
    """Sub-drivers that further decompose this driver."""

    weight: Decimal = Decimal("1.0")
    """Contribution weight of this driver to its parent (0.0 to 1.0)."""
