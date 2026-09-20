"""Agent authority contract: advisory outputs with a single boundary guard."""

from __future__ import annotations

from agents.authority.claims import (
    AgentClaim,
    AgentHypothesis,
    AgentObservation,
    AgentProposal,
    AmbiguityOutcome,
    AuthorityBoundary,
    correlate_evidence,
    detect_ambiguity,
    explain_proposal,
    find_missing_info,
    reason_over_evidence,
    require_model_output,
    require_tool_result,
    validate_claim_dict,
    validate_proposal_dict,
)
from agents.authority.evidence import (
    AuthoritativeFact,
    AuthorityError,
    EvidenceReference,
)

__all__ = [
    "AgentClaim",
    "AgentHypothesis",
    "AgentObservation",
    "AgentProposal",
    "AmbiguityOutcome",
    "AuthoritativeFact",
    "AuthorityBoundary",
    "AuthorityError",
    "EvidenceReference",
    "correlate_evidence",
    "detect_ambiguity",
    "explain_proposal",
    "find_missing_info",
    "reason_over_evidence",
    "require_model_output",
    "require_tool_result",
    "validate_claim_dict",
    "validate_proposal_dict",
]
