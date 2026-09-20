"""Typed proposal handoff — explicit, deterministic-gate boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from agents.authority.claims import AgentProposal
from agents.authority.evidence import AuthorityError


def _require_tz_aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise AuthorityError(f"{field} must be timezone-aware.")
    return value


@dataclass(frozen=True)
class RuntimeHandoff:
    """Explicit handoff object to the deterministic gate.

    Carries only an advisory ``AgentProposal`` plus provenance.
    No authoritative status, no financial fact, no execution input.
    The deterministic gate decides accept/reject — this object never
    implies execution.
    """

    proposal: AgentProposal
    situation_id: str
    company_id: str
    created_at: datetime

    def __post_init__(self) -> None:
        """Validate handoff shape."""
        if not isinstance(self.proposal, AgentProposal):
            raise AuthorityError("handoff proposal must be an AgentProposal.")
        if not isinstance(self.situation_id, str) or not self.situation_id.strip():
            raise AuthorityError("situation_id must be a non-blank string.")
        if self.company_id != "meridian":
            raise AuthorityError("company_id must be 'meridian'.")
        _require_tz_aware(self.created_at, "created_at")

    def to_dict(self) -> dict[str, Any]:
        """Return advisory handoff dict — never carries authoritative status."""
        return {
            "proposal": self.proposal.to_dict(),
            "situation_id": self.situation_id,
            "company_id": self.company_id,
            "created_at": self.created_at.isoformat(),
            "tier": "handoff",
        }
