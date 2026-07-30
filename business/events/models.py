"""Domain event models for the FP&A semantic layer.

Each event represents a meaningful business occurrence and carries
structured payload data, provenance metadata (correlation/causation),
and sensitivity classification for access control.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Sensitivity classification
# ---------------------------------------------------------------------------

Sensitivity = Literal["public", "internal", "confidential", "restricted"]

# ---------------------------------------------------------------------------
# Base event
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    """Return the current UTC datetime (naive, for storage compatibility)."""
    return datetime.now(UTC).replace(tzinfo=None)


class DomainEvent(BaseModel):
    """Base model for all domain events.

    Every event carries provenance metadata for tracing, correlation,
    and sensitivity-aware routing.
    """

    event_id: str = Field(..., description="Unique event identifier (UUID or ULID)")
    event_type: str = Field(..., description="Stable event type name, e.g. 'invoice.imported'")
    version: str = Field(default="1.0", description="Schema version of this event")
    producer: str = Field(..., description="System component that emitted this event")
    consumer: list[str] = Field(..., description="System components that consume this event")
    timestamp: datetime = Field(default_factory=_now_utc, description="When the event occurred")
    payload: dict[str, Any] = Field(default_factory=dict, description="Event-specific payload data")
    correlation_id: str | None = Field(
        default=None, description="Correlation ID for event grouping"
    )
    causation_id: str | None = Field(default=None, description="Causation ID for chaining")
    sensitivity: Sensitivity = Field(
        default="internal", description="Data sensitivity classification"
    )

    model_config = {"frozen": True, "extra": "forbid"}


# ---------------------------------------------------------------------------
# Specific event models
# ---------------------------------------------------------------------------


class InvoiceImported(DomainEvent):
    """A vendor invoice was successfully ingested from an external source."""

    vendor_id: str = Field(..., description="Vendor identifier")
    invoice_number: str = Field(..., description="Invoice reference number")
    amount: Decimal = Field(..., description="Invoice amount")
    currency: str = Field(default="USD", description="ISO 4217 currency code")
    date: datetime = Field(..., description="Invoice date")


class InvoiceRejected(DomainEvent):
    """An invoice failed validation and was rejected."""

    vendor_id: str = Field(..., description="Vendor identifier")
    invoice_number: str = Field(..., description="Invoice reference number")
    rejection_reason: str = Field(..., description="High-level rejection reason")
    validation_errors: list[str] = Field(
        default_factory=list, description="Detailed validation error messages"
    )


class BudgetApproved(DomainEvent):
    """A budget version was approved for a period."""

    entity_id: str = Field(..., description="Entity identifier")
    period: str = Field(..., description="Fiscal period (YYYY-MM)")
    budget_version: str = Field(..., description="Approved budget version identifier")
    approved_by: str = Field(..., description="Approver identity")


class BudgetRevised(DomainEvent):
    """A budget revision was created."""

    entity_id: str = Field(..., description="Entity identifier")
    period: str = Field(..., description="Fiscal period (YYYY-MM)")
    previous_version: str = Field(..., description="Previous budget version")
    new_version: str = Field(..., description="New budget version identifier")
    changes: list[str] = Field(default_factory=list, description="Description of changes made")


class PeriodClosed(DomainEvent):
    """A fiscal period was closed for postings."""

    entity_id: str = Field(..., description="Entity identifier")
    period: str = Field(..., description="Fiscal period (YYYY-MM)")
    closed_by: str = Field(..., description="User or system that closed the period")
    close_date: datetime = Field(
        default_factory=_now_utc, description="When the close was executed"
    )


class PeriodReopened(DomainEvent):
    """A period was exceptionally reopened for adjustments."""

    entity_id: str = Field(..., description="Entity identifier")
    period: str = Field(..., description="Fiscal period (YYYY-MM)")
    reason: str = Field(..., description="Business reason for reopening")
    approved_by: str = Field(..., description="Approver who authorised the reopening")


class VarianceDetected(DomainEvent):
    """A material variance was identified during analysis."""

    entity_id: str = Field(..., description="Entity identifier")
    period: str = Field(..., description="Fiscal period (YYYY-MM)")
    account_id: str = Field(..., description="GL account identifier")
    variance_amount: Decimal = Field(..., description="Calculated variance amount")
    variance_pct: Decimal = Field(..., description="Variance as a percentage")
    is_material: bool = Field(default=False, description="Exceeds materiality thresholds")


class RootCauseIdentified(DomainEvent):
    """A root cause was determined for a previously detected variance."""

    variance_id: str = Field(..., description="Reference to the variance event/record")
    root_cause_summary: str = Field(..., description="Natural language root cause explanation")
    confidence: Decimal = Field(
        default=Decimal("0.0"), description="Confidence score [0, 1]", ge=0, le=1
    )


class ForecastPublished(DomainEvent):
    """A new forecast version was published."""

    entity_id: str = Field(..., description="Entity identifier")
    period: str = Field(..., description="Fiscal period (YYYY-MM)")
    version: str = Field(..., description="Forecast version identifier")
    forecast_type: str = Field(
        ..., description="Type of forecast (e.g. 'rolling', 'bottom_up', 'top_down')"
    )


class AssertionGenerated(DomainEvent):
    """A new set of assertions was created by the assertion pipeline."""

    entity_id: str = Field(..., description="Entity identifier")
    period: str = Field(..., description="Fiscal period (YYYY-MM)")
    assertion_count: int = Field(default=0, description="Number of assertions generated", ge=0)
    pipeline_version: str = Field(..., description="Assertion pipeline version that produced these")


class ActionProposed(DomainEvent):
    """An action item has been proposed for review and approval."""

    entity_id: str = Field(..., description="Entity identifier")
    period: str = Field(..., description="Fiscal period (YYYY-MM)")
    action: str = Field(..., description="The proposed action verb (e.g. 'reduce', 'increase')")
    domain: str = Field(..., description="Business domain (e.g. 'cost', 'revenue', 'headcount')")
    target: str = Field(..., description="Target of the action (e.g. account, process, entity)")
    impact_estimate: Decimal | None = Field(default=None, description="Estimated financial impact")


class BoardReportGenerated(DomainEvent):
    """A board report was compiled, rendered, or published."""

    entity_id: str = Field(..., description="Entity identifier")
    period: str = Field(..., description="Fiscal period (YYYY-MM)")
    report_type: str = Field(..., description="Type of board report (e.g. 'monthly', 'quarterly')")
    metrics_included: list[str] = Field(
        default_factory=list, description="List of metric IDs included in the report"
    )


class StateTransitionEvent(DomainEvent):
    """Recorded for every state machine transition across all workflow entities.

    This event type is produced by the state machine framework whenever
    an entity transitions between legal states. It is consumed by the
    audit logging subsystem.
    """

    entity_type: str = Field(
        ..., description="Type of entity that transitioned (e.g. 'pipeline_run')"
    )
    entity_id: str = Field(..., description="Entity identifier")
    from_status: str = Field(..., description="Previous status value")
    to_status: str = Field(..., description="New status value")
    triggered_by: str = Field(
        ...,
        description="Trigger source: 'system', 'user:<id>', or 'agent:<name>'",
    )
    reason: str = Field(default="", description="Human-readable reason for the transition")


# ---------------------------------------------------------------------------
# Event catalog entry
# ---------------------------------------------------------------------------


class EventCatalogEntry(BaseModel):
    """Metadata entry for a single event type in the event catalog."""

    event_type: str = Field(..., description="Stable event type identifier")
    name: str = Field(..., description="Human-readable event name")
    description: str = Field(..., description="Business description of the event")
    producer: str = Field(..., description="System component that emits this event")
    consumers: list[str] = Field(
        default_factory=list,
        description="System components that react to this event",
    )
    category: str = Field(
        ...,
        description="Event category: financial, operational, or governance",
    )
    sensitivity: Sensitivity = Field(
        default="internal",
        description="Default sensitivity for this event type",
    )
    schema_ref: str = Field(default="", description="Reference to the event model class name")


class EventCatalog(BaseModel):
    """Registry of all domain event types with metadata.

    Provides lookup by event type name and iteration over all
    registered events in the platform.
    """

    entries: dict[str, EventCatalogEntry] = Field(
        default_factory=dict,
        description="Event catalog entries keyed by event_type",
    )

    def get(self, event_type: str) -> EventCatalogEntry | None:
        """Look up an event by its type identifier.

        Args:
            event_type: The event type string (e.g. 'invoice.imported').

        Returns:
            The catalog entry if found, None otherwise.
        """
        return self.entries.get(event_type)

    def list_by_category(self, category: str) -> list[EventCatalogEntry]:
        """Return all events in a given category.

        Args:
            category: One of 'financial', 'operational', or 'governance'.

        Returns:
            List of matching catalog entries.
        """
        return [e for e in self.entries.values() if e.category == category]

    def list_by_consumer(self, consumer: str) -> list[EventCatalogEntry]:
        """Return all events consumed by a given component.

        Args:
            consumer: The component name (e.g. 'VarianceEngine').

        Returns:
            List of matching catalog entries.
        """
        return [e for e in self.entries.values() if consumer in e.consumers]

    @property
    def count(self) -> int:
        """Total number of registered events."""
        return len(self.entries)
