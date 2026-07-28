"""Evidence models.

Every claim made by the LLM must reference supporting evidence.
"""
from __future__ import annotations
from decimal import Decimal
from pydantic import BaseModel


class EvidenceItem(BaseModel):
    """A single piece of evidence supporting a claim."""

    claim: str
    source_type: str
    source_id: str
    source_value: Decimal | None = None
    supporting_metrics: list[str] = []
    confidence: str = "medium"
    assumptions: list[str] = []
    limitations: list[str] = []
