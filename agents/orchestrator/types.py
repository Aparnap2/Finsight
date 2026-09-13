"""Frozen orchestration result contract (P4.5).

The result carries the full trajectory: every verifier verdict, every
capability output, the accepted candidate (if any), and the provider journal.
No financial mutation occurs here: the candidate proposal is a frozen draft
requiring downstream P3 policy, HITL, and sandbox verification.

The module imports nothing from ``finance`` execution paths, ``apps``, or
any LLM framework.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from agents.capabilities.types import CapabilityOutcome
from agents.verification.verdict import Verdict
from finance.proposals.proposal import Proposal
from shared.llm.types import ProviderCallLog

OrchestrationStatus = Literal[
    "ACCEPTED_CANDIDATE",
    "REPLAN_EXHAUSTED_HITL",
    "PROVIDER_FAILURE_HITL",
]


class OrchestrationResult(BaseModel):
    """Deterministic orchestration trace for one investigation request."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    status: OrchestrationStatus
    request_id: str
    attempts: int
    verdicts: tuple[Verdict, ...]
    plan: object | None = None
    capability_outcomes: tuple[CapabilityOutcome, ...] = ()
    proposal_candidate: Proposal | None = None
    provider_journal: tuple[ProviderCallLog, ...] = ()
    hitl_reason: str | None = None

    @property
    def is_hitl(self) -> bool:
        """Return True when the trajectory escalated to HITL."""
        return self.status in ("REPLAN_EXHAUSTED_HITL", "PROVIDER_FAILURE_HITL")
