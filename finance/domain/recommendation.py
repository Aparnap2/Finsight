"""Recommendation domain models.

Recommendations are actionable suggestions produced by the FinSight
recommendation engine.  They identify cost-saving opportunities, revenue
optimisation plays, process improvements, and risk mitigations backed by
evidence.
"""

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel

from finance.domain._types import MoneyDecimal
from finance.domain.evidence import EvidenceConfidence


class RecommendationType(StrEnum):
    """The category of a recommendation."""

    COST_SAVING = "cost_saving"
    """An opportunity to reduce costs (e.g. vendor consolidation)."""

    REVENUE_OPTIMIZATION = "revenue_optimization"
    """An opportunity to increase or optimise revenue."""

    PROCESS_IMPROVEMENT = "process_improvement"
    """A suggestion to improve a business process."""

    RISK_MITIGATION = "risk_mitigation"
    """An action to reduce financial or operational risk."""


class RecommendationStatus(StrEnum):
    """The lifecycle state of a recommendation."""

    PROPOSED = "proposed"
    """The recommendation has been generated but not yet reviewed."""

    REVIEWED = "reviewed"
    """The recommendation has been reviewed by a human."""

    APPROVED = "approved"
    """The recommendation has been approved for implementation."""

    IMPLEMENTED = "implemented"
    """The recommendation has been implemented."""

    REJECTED = "rejected"
    """The recommendation was rejected and will not be pursued."""


class Recommendation(BaseModel):
    """An actionable recommendation backed by evidence.

    Recommendations are the output of the recommendation engine.  Each
    recommendation has a type, expected financial impact, supporting
    evidence, and a lifecycle status for tracking from proposal to
    implementation.
    """

    id: str
    """Unique recommendation identifier."""

    type: RecommendationType
    """The category of recommendation."""

    title: str
    """Short, action-oriented title."""

    description: str
    """Detailed explanation of the recommendation."""

    expected_impact: MoneyDecimal | None = None
    """Estimated financial impact (positive = benefit, negative = cost)."""

    impact_currency: str = "USD"
    """Currency of the expected impact."""

    evidence_ids: list[str] = []
    """Identifiers of supporting evidence items."""

    confidence: EvidenceConfidence
    """How confident the system is in this recommendation."""

    status: RecommendationStatus = RecommendationStatus.PROPOSED
    """The current lifecycle state."""

    owner: str | None = None
    """Person responsible for actioning this recommendation."""

    target_date: date | None = None
    """Target date for implementation."""

    created_at: datetime
    """Timestamp when the recommendation was created."""

    updated_at: datetime
    """Timestamp when the recommendation was last updated."""
