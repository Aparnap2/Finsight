"""Evidence Engine — collects and scores evidence for claims."""
from __future__ import annotations

from decimal import Decimal

from finance.evidence.models import EvidenceItem


class EvidenceEngine:
    """Collects evidence and computes coverage scores."""

    def collect(self, account_id: str, period_id: str) -> list[EvidenceItem]:
        return []

    def coverage_score(self, period_id: str) -> Decimal:
        return Decimal("0")
