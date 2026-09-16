"""Controlled P4.5 orchestrator (P4.5).

# ruff: noqa: SIM105


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

try:
    from shared.tracing.correlation import derive_correlation_id, validate_correlation_id
    from shared.tracing.noop import NoOpTracer
    from shared.tracing.observability import ObservabilityTrace
    from shared.tracing.protocol import TraceContext, TracerProtocol
except ImportError:  # pragma: no cover
    TracerProtocol = object  # type: ignore[misc,assignment]
    TraceContext = object  # type: ignore[misc,assignment]
    NoOpTracer = object  # type: ignore[misc,assignment]
    ObservabilityTrace = object  # type: ignore[misc,assignment]

    def derive_correlation_id(**kw):  # type: ignore[no-redef]
        return kw.get("exception_id") or "corr"

    def validate_correlation_id(v):  # type: ignore[no-redef]
        return v


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
        tracer: TracerProtocol | None = None,
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
            tracer: Optional ``TracerProtocol`` for observability
                (defaults to ``NoOpTracer``; no network when unset).

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
        # Wire tracer through planner/executor/verifier when possible
        try:
            self._tracer: TracerProtocol = tracer or NoOpTracer()  # type: ignore[operator]
        except Exception:
            self._tracer = tracer  # type: ignore[assignment]
        # Planner owns its tracer; if we have a tracer, inject it
        try:
            if tracer is not None and hasattr(Planner, "tracer"):
                self._planner = Planner(llm, tracer=self._tracer)  # type: ignore[arg-type]
            else:
                self._planner = Planner(llm)
                # Best-effort: set tracer attr if Planner supports it
                if hasattr(self._planner, "_tracer"):
                    self._planner._tracer = self._tracer  # type: ignore[attr-defined]
        except Exception:
            self._planner = Planner(llm)
        self._executor = capability_executor
        # Best-effort inject tracer into executor/verifier
        try:
            if hasattr(self._executor, "_tracer"):
                self._executor._tracer = self._tracer  # type: ignore[attr-defined]
        except Exception:
            pass
        self._verifier = verifier
        try:
            if hasattr(self._verifier, "_tracer"):
                self._verifier._tracer = self._tracer  # type: ignore[attr-defined]
        except Exception:
            pass
        self._proposal_builder = proposal_builder
        self._max_replans = verifier.max_replans if max_replans is None else max_replans
        if not isinstance(self._max_replans, int) or isinstance(self._max_replans, bool):
            raise TypeError("max_replans must be an int.")
        if self._max_replans < 0:
            raise ValueError("max_replans must be >= 0.")

    @property
    def tracer(self) -> TracerProtocol:
        """Return the tracing seam (NoOp when unconfigured)."""
        return self._tracer

    def run(
        self,
        request: InvestigationRequest,
        tenant_id: str,
        *,
        exception_snapshot: Any | None = None,
        canonical_records: Any | None = None,
        correlation_id: str | None = None,
        s3_key: str | None = None,
        fingerprint: str | None = None,
        idempotency_key: str | None = None,
    ) -> OrchestrationResult:
        """Run one bounded investigation with observability.

        Args:
            request: Validated request.
            tenant_id: Tenant scope for capability execution.
            exception_snapshot: Optional verified snapshot for proposal build.
            canonical_records: Optional records for proposal amount recomputation.
            correlation_id: Optional unified correlation_id; when None it is
                derived from ``s3_key``/``fingerprint``/``idempotency_key``/
                ``request.exception_id`` in that precedence.
            s3_key: Optional S3 key for correlation derivation
                (``{tenant}/{case}/...``).
            fingerprint: Optional webhook fingerprint (sha256 hex).
            idempotency_key: Optional execution idempotency key.

        Returns:
            Frozen :class:`OrchestrationResult`.
        """
        if not isinstance(request, InvestigationRequest):
            raise TypeError("request must be an InvestigationRequest.")
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("tenant_id must be non-blank.")
        # ---- Observability: derive correlation_id and start trace ----
        trace_ctx: TraceContext | None = None
        obs: ObservabilityTrace | None = None  # type: ignore[assignment]
        try:
            derived_corr = correlation_id or derive_correlation_id(
                fingerprint=fingerprint,
                idempotency_key=idempotency_key,
                s3_key=s3_key,
                exception_id=request.exception_id,
            )
            validate_correlation_id(derived_corr)
            validate_correlation_id(tenant_id)
            # Use ObservabilityTrace facade when available; fall back to raw tracer
            try:
                obs = ObservabilityTrace(  # type: ignore[operator]
                    self._tracer,
                    correlation_id=derived_corr,
                    tenant_id=tenant_id,
                    case_id=request.exception_id,
                    exception_type=request.exception_type,
                )
                trace_ctx = obs.start_case()
                obs.context_assembly(
                    trace_ctx,
                    evidence_ids=request.evidence_ids,
                    latency_ms=0,
                    status="ok",
                )
                obs.planner(
                    trace_ctx,
                    evidence_ids=request.evidence_ids,
                    allowlist=request.capability_allowlist,
                    status="planned",
                )
            except Exception:
                # Fallback: raw tracer trace
                trace_ctx = self._tracer.trace(  # type: ignore[union-attr]
                    request.exception_id, tenant_id, request.exception_type
                )
        except Exception:
            trace_ctx = None
            obs = None

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
                # Pass trace_ctx when planner supports it
                try:
                    plan = self._planner.plan(request, trace_ctx)  # type: ignore[call-arg]
                except TypeError:
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
            # Wire verifier through tracer when possible
            try:
                verdict = self._verifier.verify(plan, request.evidence_ids, attempt, trace_ctx)  # type: ignore[call-arg]
            except TypeError:
                verdict = self._verifier.verify(plan, request.evidence_ids, attempt)
            verdicts.append(verdict)
            # Observability: verifier + replan hops
            if obs is not None and trace_ctx is not None:
                try:
                    obs.verifier(
                        trace_ctx,
                        status=verdict.status,
                        reason_codes=verdict.reasons,
                        attempt=attempt,
                    )
                    if verdict.status != "ACCEPTED":
                        obs.replan(trace_ctx, attempt=attempt, reason_codes=verdict.reasons)
                except Exception:
                    pass

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
                try:
                    outcomes = self._executor.execute(plan, tenant_id, trace_ctx)  # type: ignore[call-arg]
                except TypeError:
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

            # Observability: final candidate + policy + approval placeholders
            if obs is not None and trace_ctx is not None:
                try:
                    obs.final_candidate(
                        trace_ctx,
                        hypothesis_ref=getattr(plan, "hypothesis_text", "")[:100],
                        evidence_required=getattr(plan, "evidence_required", ()),
                        status="candidate",
                    )
                    # Policy/approval/execution/verification are outside P4.5;
                    # record placeholders so trace is queryable by correlation_id
                    obs.policy(trace_ctx, decision="DEFERRED", reason_codes=("p4.5_no_policy",))
                except Exception:
                    pass
            # Flush observability
            if obs is not None:
                try:
                    obs.flush()
                except Exception:
                    pass
            elif trace_ctx is not None:
                try:
                    self._tracer.flush()  # type: ignore[union-attr]
                except Exception:
                    pass
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
        if obs is not None:
            try:
                obs.flush()
            except Exception:
                pass
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
