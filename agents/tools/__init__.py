"""Investigation tool contracts — typed, registry-resolved, advisory only."""

from __future__ import annotations

from agents.tools.correlation import CorrelationRequest, CorrelationResult, correlate
from agents.tools.evidence_lookup import (
    EvidenceLookupRequest,
    EvidenceLookupResult,
    evidence_lookup,
)
from agents.tools.explanation import ExplanationRequest, ExplanationResult, explain

__all__ = [
    "CorrelationRequest",
    "CorrelationResult",
    "EvidenceLookupRequest",
    "EvidenceLookupResult",
    "ExplanationRequest",
    "ExplanationResult",
    "correlate",
    "evidence_lookup",
    "explain",
]
