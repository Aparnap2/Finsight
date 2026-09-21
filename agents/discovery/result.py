"""Discovery result — RED permissive stub (no enforcement)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from agents.authority.evidence import EvidenceReference


@dataclass
class DiscoveryFailure:
    """Typed failure (RED stub)."""

    code: str
    detail: str


@dataclass
class DiscoveryResult:
    """Permissive stub: allows authoritative markers and missing validation (RED)."""

    success: bool
    situation_id: str
    company_id: str
    now: datetime
    evidence_refs: tuple[EvidenceReference, ...] | None = None
    observations: tuple[str, ...] | None = None
    hypotheses: tuple[str, ...] | None = None
    proposals: tuple[Any, ...] | None = None
    failure: DiscoveryFailure | None = None
    # Permissive authoritative seams (RED: should be rejected)
    status: str | None = None
    verdict: str | None = None
    decision: str | None = None
    amount: Any | None = None

    @property
    def tier(self) -> str:
        """Tier label (RED stub)."""
        return "discovery"

    def to_dict(self) -> dict[str, Any]:
        """Advisory dict (RED stub — incorrectly allows authoritative keys)."""
        payload: dict[str, Any] = {
            "success": self.success,
            "situation_id": self.situation_id,
            "company_id": self.company_id,
            "now": self.now.isoformat(),
            "evidence_ids": [r.evidence_id for r in self.evidence_refs or ()],
            "observations": self.observations,
            "tier": self.tier,
        }
        if self.status is not None:
            payload["status"] = self.status
        if self.verdict is not None:
            payload["verdict"] = self.verdict
        if self.decision is not None:
            payload["decision"] = self.decision
        if self.amount is not None:
            payload["amount"] = self.amount
        if self.failure is not None:
            payload["failure"] = {"code": self.failure.code, "detail": self.failure.detail}
        return payload
