"""Evidence domain model.

Evidence items are structured records that support claims made during
variance analysis and commentary generation.  They link assertions to
their source data (KPIs, variances, drivers, or manual input) with a
confidence level.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel

from finance.domain._types import MoneyDecimal


class EvidenceSource(StrEnum):
    """The origin of an evidence item."""

    KPI = "kpi"
    """Evidence derived from a KPI calculation."""

    VARIANCE = "variance"
    """Evidence derived from a variance analysis."""

    DRIVER = "driver"
    """Evidence derived from a driver analysis."""

    TRANSACTION = "transaction"
    """Evidence derived from individual transactions."""

    MANUAL = "manual"
    """Evidence manually entered by a human analyst."""


class EvidenceConfidence(StrEnum):
    """Confidence level assigned to an evidence item."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    TENTATIVE = "tentative"


class EvidenceItem(BaseModel):
    """A structured piece of evidence supporting a financial claim.

    Evidence items are used by the commentary engine to substantiate
    assertions about variances, trends, and financial health.  Each item
    specifies a claim, its source, assumptions, limitations, and
    confidence level.
    """

    id: str
    """Unique evidence identifier."""

    claim: str
    """The statement or assertion this evidence supports."""

    source_type: EvidenceSource
    """The category of source this evidence originates from."""

    source_id: str
    """Identifier of the source object (KPI, variance, driver, etc.)."""

    source_value: MoneyDecimal | None = None
    """The numerical value from the source (if applicable)."""

    supporting_metrics: list[str] = []
    """Identifiers of additional metrics that corroborate this evidence."""

    confidence: EvidenceConfidence
    """How reliable this evidence is considered."""

    assumptions: list[str] = []
    """Assumptions made when generating this evidence."""

    limitations: list[str] = []
    """Known limitations or caveats."""

    created_at: datetime
    """Timestamp when the evidence was created."""
