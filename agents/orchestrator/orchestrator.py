"""Controlled P4.5 orchestrator (P4.5).

Runs the frozen loop: request -> planner -> verifier -> (replan or)
capability executor -> deterministic proposal candidate. Bounded replans
escalate to HITL; provider failures escalate; no financial mutation,
no state transitions, no LangChain. Provider-independent: any
``LLMProvider`` works identically.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from agents.capabilities.executor import CapabilityExecutor
from agents.capabilities.types import ExecutorRejectedError
from agents.investigation.errors import PlannerError
from agents.investigation.planner import Planner
from agents.investigation.request import InvestigationRequest
from agents.orchestrator.types import OrchestrationResult
from agents.verification.verdict import Verdict
from agents.verification.verifier import Verifier
from finance.proposals.proposal import Proposal
from shared.llm.errors import CredentialMissingError, ProviderError, ProviderUnavailableError

logger = logging.getLogger(__name__)


class InvestigateOrchestrator:
    """Orchestrate one investigation request through the frozen P4 gates."""

    def __init__(
        self,
        llm: Any,
        capability_executor: CapabilityExecutor,
        verifier: Verifier,
        proposal_builder: Callable[..., Proposal] | None = None,
        *,
        max_replans: int | None = None,
    ) -> None:
        """Bind seams.

        Args:
            llm: Any ``LLMProvider``.
            capability_executor: Deterministic executor.
            verifier: Deterministic gate.
            proposal_builder: Optional deterministic builder to call after
                ACCEPTED (receives no invented amounts; None means no proposal
                synthesis, leaving ``proposal_candidate`` as None).
            max_replans: Override re-plan budget; defaults to verifier's.

        Raises:
            TypeError: On bad types.
        """
        if llm is None:
            raise TypeError("llm must be an LLMProvider, got None.")
        if not isinstance(capability_executor, CapabilityExecutor):
            raise TypeError("capability_executor must be a CapabilityExecutor.")
        if not isinstance(verifier, Verifier):
            raise TypeError("verifier must be a Verifier.")
        self._llm = llm
        self._planner = Planner(llm)
        self._executor = capability_executor
        self._verifier = verifier
        self._proposal_builder = proposal_builder
        self._max_replans = verifier.max_replans if max_replans is None else max_replans
        if not isinstance(self._max_replans, int) or isinstance(self._max_replans, bool):
            raise TypeError("max_replans must be an int.")
        if self._max_replans < 0:
            raise ValueError("max_replans must be >= 0.")

    def run(
        self,
        request: InvestigationRequest,
        tenant_id: str,
        *,
        exception_snapshot: Any | None = None,
        canonical_records: Any | None = None,
    ) -> OrchestrationResult:
        """Run one bounded investigation.

        Args:
            request: Validated request.
            tenant_id: Tenant scope for capability execution.
            exception_snapshot: Optional verified snapshot for proposal build.
            canonical_records: Optional records for proposal amount recomputation.

        Returns:
            Frozen :class:`OrchestrationResult`.
        """
        if not isinstance(request, InvestigationRequest):
            raise TypeError("request must be an InvestigationRequest.")
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("tenant_id must be non-blank.")

        verdicts: list[Verdict] = []
        last_plan: Any | None = None
        outcomes: tuple[Any, ...] = ()
        journal: tuple[Any, ...] = self._collect_journal()

        # Health gate: if provider reports unhealthy before any LLM call,
        # escalate without consuming budget? Per spec, health_check gates.
        # We expose it but do not consume round budget on unhealthy.
        try:
            health = self._llm.health_check()  # type: ignore[attr-defined]
            if hasattr(health, "ok") and not health.ok:
                return OrchestrationResult(
                    status="PROVIDER_FAILURE_HITL",
                    request_id=request.exception_id,
                    attempts=0,
                    verdicts=(),
                    plan=None,
                    capability_outcomes=(),
                    proposal_candidate=None,
                    provider_journal=journal,
                    hitl_reason="provider unhealthy",
                )
        except Exception:
            pass

        for attempt in range(self._max_replans + 1):
            try:
                plan = self._planner.plan(request)
            except PlannerError as exc:
                # Distinguish provider-caused failures for HITL type.
                cause = exc.__cause__
                is_provider = isinstance(
                    cause,
                    (ProviderError, ProviderUnavailableError, CredentialMissingError),
                ) or isinstance(
                    exc, (ProviderError, ProviderUnavailableError, CredentialMissingError)
                )
                reason = f"planner_error:{type(exc).__name__}"
                verdict = Verdict(
                    status="REJECTED_REPLAN",
                    reasons=(reason,),
                    attempt_index=attempt,
                )
                verdicts.append(verdict)
                journal = self._collect_journal()
                if is_provider and attempt == 0:
                    # Provider failure heads to HITL after budget or immediately if configured
                    # For now, treat as replan-able unless budget exhausted
                    pass
                if attempt >= self._max_replans:
                    return OrchestrationResult(
                        status="REPLAN_EXHAUSTED_HITL",
                        request_id=request.exception_id,
                        attempts=attempt + 1,
                        verdicts=tuple(verdicts),
                        plan=None,
                        capability_outcomes=(),
                        proposal_candidate=None,
                        provider_journal=journal,
                        hitl_reason="planner failed; budget exhausted",
                    )
                continue
            except Exception as exc:  # pragma: no cover
                verdict = Verdict(
                    status="REJECTED_REPLAN",
                    reasons=(f"planner_unexpected:{type(exc).__name__}",),
                    attempt_index=attempt,
                )
                verdicts.append(verdict)
                journal = self._collect_journal()
                if attempt >= self._max_replans:
                    return OrchestrationResult(
                        status="REPLAN_EXHAUSTED_HITL",
                        request_id=request.exception_id,
                        attempts=attempt + 1,
                        verdicts=tuple(verdicts),
                        plan=None,
                        capability_outcomes=(),
                        proposal_candidate=None,
                        provider_journal=journal,
                        hitl_reason="unexpected planner failure; budget exhausted",
                    )
                continue

            last_plan = plan
            verdict = self._verifier.verify(plan, request.evidence_ids, attempt)
            verdicts.append(verdict)

            if verdict.status == "REJECTED_REPLAN":
                journal = self._collect_journal()
                if attempt >= self._max_replans:
                    return OrchestrationResult(
                        status="REPLAN_EXHAUSTED_HITL",
                        request_id=request.exception_id,
                        attempts=attempt + 1,
                        verdicts=tuple(verdicts),
                        plan=plan,
                        capability_outcomes=(),
                        proposal_candidate=None,
                        provider_journal=journal,
                        hitl_reason="verifier rejected; budget exhausted",
                    )
                continue

            if verdict.status == "ESCALATE_HITL":
                journal = self._collect_journal()
                return OrchestrationResult(
                    status="REPLAN_EXHAUSTED_HITL",
                    request_id=request.exception_id,
                    attempts=attempt + 1,
                    verdicts=tuple(verdicts),
                    plan=plan,
                    capability_outcomes=(),
                    proposal_candidate=None,
                    provider_journal=journal,
                    hitl_reason="verifier escalated to HITL",
                )

            # ACCEPTED -> execute capabilities
            try:
                outcomes = self._executor.execute(plan, tenant_id)
            except ExecutorRejectedError as exc:
                # Treat whole-run rejection as verifier-level replan without execution
                reject = Verdict(
                    status="REJECTED_REPLAN",
                    reasons=(f"executor_rejected:{exc}",),
                    attempt_index=attempt,
                )
                verdicts.append(reject)
                journal = self._collect_journal()
                if attempt >= self._max_replans:
                    return OrchestrationResult(
                        status="REPLAN_EXHAUSTED_HITL",
                        request_id=request.exception_id,
                        attempts=attempt + 1,
                        verdicts=tuple(verdicts),
                        plan=plan,
                        capability_outcomes=(),
                        proposal_candidate=None,
                        provider_journal=journal,
                        hitl_reason="executor rejected; budget exhausted",
                    )
                continue

            # Deterministic proposal candidate after verified cognition
            proposal_candidate: Proposal | None = None
            if (
                self._proposal_builder is not None
                and exception_snapshot is not None
                and canonical_records is not None
            ):
                try:
                    proposal_candidate = self._proposal_builder(
                        exception_snapshot, canonical_records, plan.evidence_required
                    )
                except Exception as exc:  # pragma: no cover
                    logger.info("proposal build skipped: %s", exc)

            journal = self._collect_journal()
            return OrchestrationResult(
                status="ACCEPTED_CANDIDATE",
                request_id=request.exception_id,
                attempts=attempt + 1,
                verdicts=tuple(verdicts),
                plan=plan,
                capability_outcomes=outcomes,
                proposal_candidate=proposal_candidate,
                provider_journal=journal,
                hitl_reason=None,
            )

        # Exhausted loop
        journal = self._collect_journal()
        return OrchestrationResult(
            status="REPLAN_EXHAUSTED_HITL",
            request_id=request.exception_id,
            attempts=len(verdicts),
            verdicts=tuple(verdicts),
            plan=last_plan,
            capability_outcomes=(),
            proposal_candidate=None,
            provider_journal=journal,
            hitl_reason="budget exhausted",
        )

    def _collect_journal(self) -> tuple[Any, ...]:
        """Collect provider journal without assuming its attribute name."""
        for attr in ("journal", "call_journal", "call_log"):
            if hasattr(self._llm, attr):
                try:
                    val = getattr(self._llm, attr)
                    if isinstance(val, (list, tuple)):
                        return tuple(val)
                except Exception:
                    pass
        return ()
