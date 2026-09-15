"""Domain event contract — version 1.

Defines the canonical shape of a domain event envelope: every event
carries provenance, sensitivity, and payload metadata. The event
catalog references this contract instead of inlining field
definitions.

Contracts are pure shape definitions: they carry no business logic and
may not import from ``business/``.
"""

# mypy: disable-error-code="misc"

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

#: Schema identifier referenced by the event catalog.
SCHEMA = "finsight/event-contract/event-v1"
VERSION = "1.0.0"

EventSensitivity = Literal["public", "internal", "confidential", "restricted"]


def _now_utc() -> datetime:
    """Return the current UTC datetime (naive, for storage compatibility)."""
    return datetime.now(UTC).replace(tzinfo=None)


class EventContractV1(BaseModel):
    """The canonical domain event envelope.

    Attributes:
        event_id: Unique event identifier (UUID or ULID).
        event_type: Stable event type (e.g. ``invoice.imported``).
        version: Schema version of this event.
        producer: System component that emitted the event.
        consumers: System components that consume the event.
        timestamp: When the event occurred.
        payload: Event-specific payload data.
        correlation_id: Correlation ID for event grouping.
        causation_id: Causation ID for chaining.
        sensitivity: Data sensitivity classification.
    """

    model_config = {"frozen": True, "extra": "forbid"}

    event_id: str = Field(description="Unique event identifier (UUID or ULID)")
    event_type: str = Field(description="Stable event type name")
    version: str = Field(default="1.0", description="Schema version of this event")
    producer: str = Field(description="System component that emitted this event")
    consumers: list[str] = Field(
        default_factory=list,
        description="System components that consume this event",
    )
    timestamp: datetime = Field(default_factory=_now_utc, description="When the event occurred")
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Event-specific payload data",
    )
    correlation_id: str | None = Field(
        default=None,
        description="Correlation ID for event grouping",
    )
    causation_id: str | None = Field(
        default=None,
        description="Causation ID for chaining",
    )
    sensitivity: EventSensitivity = Field(
        default="internal",
        description="Data sensitivity classification",
    )


__all__ = ["EventContractV1", "EventSensitivity", "SCHEMA", "VERSION"]
