"""Domain Events — Layer 0 semantic foundation.

Defines the event schema, catalog, and type hierarchy for every
business event the platform produces or consumes. Events are the
glue between capabilities and data flows across the FP&A lifecycle.
"""

from business.events.catalog import EVENT_CATALOG, EVENTS_BY_TYPE
from business.events.models import (
    ActionProposed,
    AssertionGenerated,
    BoardReportGenerated,
    BudgetApproved,
    BudgetRevised,
    DomainEvent,
    EventCatalog,
    EventCatalogEntry,
    ForecastPublished,
    InvoiceImported,
    InvoiceRejected,
    PeriodClosed,
    PeriodReopened,
    RootCauseIdentified,
    StateTransitionEvent,
    VarianceDetected,
)

__all__ = [
    "ActionProposed",
    "AssertionGenerated",
    "BoardReportGenerated",
    "BudgetApproved",
    "BudgetRevised",
    "DomainEvent",
    "EVENT_CATALOG",
    "EVENTS_BY_TYPE",
    "EventCatalog",
    "EventCatalogEntry",
    "ForecastPublished",
    "InvoiceImported",
    "InvoiceRejected",
    "PeriodClosed",
    "PeriodReopened",
    "RootCauseIdentified",
    "StateTransitionEvent",
    "VarianceDetected",
]
