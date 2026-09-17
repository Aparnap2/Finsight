"""Trajectory harness — Fake/Replay/Live/E2E INPUT→...→FINAL runner.

P5-07: drives one investigation through Planner → Verifier → Executor
with bounded replans while recording every step into a tenant-safe
:class:`~agents.trajectory.models.Trajectory` ledger (correlation_id
propagated, no raw bodies, no secrets, no PII).

Modes:

- ``fake``: FakeLLM + real verifier + real executor (no network).
- ``replay``: SequentialReplayProvider + real verifier + real executor.
- ``live``: real Groq provider (gated by ``FINSIGHT_ALLOW_LIVE_LLM=1``,
  max 3 LLM calls per run).
- ``e2e``: live provider + real stores (gated like ``live``).

Tenant isolation is fail-closed: ``request.tenant_id`` must equal the
run ``tenant_id`` or the run raises before any LLM call. The harness
imports only sibling ``agents`` packages plus ``finance`` grounding
helpers — never ``apps``.
"""

from __future__ import annotations

import os
import time
from typing import Any

from agents.capabilities.executor import CapabilityExecutor
from agents.investigation.plan import InvestigationPlan
from agents.investigation.planner import Planner
from agents.investigation.request import InvestigationRequest
from agents.trajectory.models import (
    Trajectory,
    TrajectoryMode,
    TrajectoryStep,
    TrajectoryStepKind,
    generate_correlation_id,
    now_utc,
)
from agents.verification.verifier import Verifier

try:
    from shared.tracing.noop import NoOpTracer
    from shared.tracing.protocol import TraceContext, TracerProtocol
except ImportError:  # pragma: no cover
    TracerProtocol = object  # type: ignore[misc,assignment]
    TraceContext = object  # type: ignore[misc,assignment]
    NoOpTracer = object  # type: ignore[misc,assignment]

_LIVE_ENV_VAR = "FINSIGHT_ALLOW_LIVE_LLM"
_MAX_LLM_CALLS = 3
_MAX_REPLANS = 2


class TrajectoryTenantError(ValueError):
    """Run tenant does not match the request tenant (fail-closed)."""


class TrajectoryLiveError(RuntimeError):
    """Live/E2E mode requested without the explicit opt-in env gate."""


def is_live_allowed() -> bool:
    """Return True iff the operator opted into real LLM calls."""
    return os.environ.get(_LIVE_ENV_VAR, "") == "1"


class TrajectoryHarness:
    """Runs one investigation and records the tenant-safe ledger."""

    def __init__(
        self,
        llm: Any,
        executor: CapabilityExecutor,
        verifier: Verifier | None = None,
        mode: TrajectoryMode = "fake",
        correlation_id: str | None = None,
        tracer: TracerProtocol | None = None,
    ) -> None:
        """Bind the provider, executor, verifier, and mode.

        Args:
            llm: Any LLMProvider (FakeLLM, SequentialReplayProvider, Groq).
            executor: Deterministic capability executor (real, always).
            verifier: Deterministic plan gate (defaults to ``Verifier()``).
            mode: One of fake/replay/live/e2e. live/e2e require the
                ``FINSIGHT_ALLOW_LIVE_LLM=1`` gate at :meth:`run` time.
            correlation_id: Tenant-safe id propagated to every step
                (generated when omitted).
            tracer: Optional ``TracerProtocol`` (defaults to NoOp).

        Raises:
            TypeError: If llm or executor is None.
            ValueError: If mode is unknown.
        """
        if llm is None:
            raise TypeError("llm must be an LLM provider, got None.")
        if executor is None:
            raise TypeError("executor must be a CapabilityExecutor, got None.")
        if mode not in ("fake", "replay", "live", "e2e"):
            raise ValueError(f"unknown trajectory mode: {mode!r}.")
        self._llm = llm
        self._executor = executor
        self._verifier = verifier or Verifier()
        self._mode: TrajectoryMode = mode
        self._correlation_id = correlation_id or generate_correlation_id()
        try:
            self._tracer: TracerProtocol = tracer or NoOpTracer()  # type: ignore[operator]
        except Exception:
            self._tracer = tracer  # type: ignore[assignment]
        self._planner = Planner(llm, tracer=tracer)
        self._llm_calls = 0

    @property
    def mode(self) -> TrajectoryMode:
        """Return the harness mode."""
        return self._mode

    @property
    def correlation_id(self) -> str:
        """Return the run correlation id."""
        return self._correlation_id

    @property
    def llm_calls(self) -> int:
        """Return the number of LLM calls made by this harness."""
        return self._llm_calls

    def _record(
        self,
        steps: list[TrajectoryStep],
        kind: TrajectoryStepKind,
        *,
        tenant_id: str,
        status: str = "",
        evidence_ids: tuple[str, ...] = (),
        capability: str | None = None,
        reason_codes: tuple[str, ...] = (),
        attempt: int = 0,
        latency_ms: float | None = None,
    ) -> None:
        """Append one tenant-safe step (no bodies, no secrets)."""
        steps.append(
            TrajectoryStep(
                kind=kind,
                correlation_id=self._correlation_id,
                tenant_id=tenant_id,
                timestamp=now_utc(),
                latency_ms=latency_ms,
                status=status[:64],
                evidence_ids=evidence_ids[:32],
                capability=capability,
                reason_codes=tuple(r[:64] for r in reason_codes[:8]),
                attempt=attempt,
            )
        )

    def _check_tenant(self, request: InvestigationRequest, tenant_id: str) -> None:
        """Fail closed when the run tenant differs from the request tenant."""
        if request.tenant_id != tenant_id:
            raise TrajectoryTenantError(
                f"tenant_mismatch: request {request.tenant_id!r} != run {tenant_id!r}."
            )

    def run(self, request: InvestigationRequest, tenant_id: str) -> Trajectory:
        """Run Planner → Verifier → Executor with bounded replans.

        Args:
            request: Validated planner input (tenant/actor already set).
            tenant_id: Run scope; must equal ``request.tenant_id``.

        Returns:
            The complete INPUT→...→FINAL :class:`Trajectory`.

        Raises:
            TrajectoryTenantError: Tenant mismatch (before any LLM call).
            TrajectoryLiveError: live/e2e without the env opt-in gate.
        """
        self._check_tenant(request, tenant_id)
        if self._mode in ("live", "e2e") and not is_live_allowed():
            raise TrajectoryLiveError(
                f"mode {self._mode!r} requires {_LIVE_ENV_VAR}=1."
            )
        started = now_utc()
        steps: list[TrajectoryStep] = []
        self._record(steps, "INPUT", tenant_id=tenant_id, status="received",
                     evidence_ids=tuple(request.evidence_ids))

        final_status = "REJECTED_REPLAN"
        attempt = 0
        plan: InvestigationPlan | None = None
        while attempt <= _MAX_REPLANS:
            if self._llm_calls >= _MAX_LLM_CALLS:
                self._record(
                    steps, "FINAL", tenant_id=tenant_id,
                    status="BUDGET_EXHAUSTED",
                    reason_codes=("budget_exhausted:llm_calls",),
                    attempt=attempt,
                )
                final_status = "BUDGET_EXHAUSTED"
                break
            # MODEL_OUTPUT via the planner (one LLM call). Planner-side
            # structural rejection is a replan-eligible outcome, not an
            # escape: the harness stays total and always returns a ledger.
            call_started = time.monotonic()
            try:
                plan = self._planner.plan(request)
            except Exception as exc:
                self._llm_calls += 1
                latency = (time.monotonic() - call_started) * 1000.0
                code = f"planner_rejected:{type(exc).__name__}"
                self._record(
                    steps, "VERIFIER", tenant_id=tenant_id,
                    status="REJECTED_REPLAN", reason_codes=(code,),
                    attempt=attempt, latency_ms=latency,
                )
                attempt += 1
                if attempt > _MAX_REPLANS:
                    final_status = "REJECTED_REPLAN"
                    break
                continue
            self._llm_calls += 1
            latency = (time.monotonic() - call_started) * 1000.0
            kind: TrajectoryStepKind = "MODEL_OUTPUT" if attempt == 0 else "NEXT_OUTPUT"
            self._record(
                steps, kind, tenant_id=tenant_id, status="planned",
                evidence_ids=tuple(plan.evidence_required),
                attempt=attempt, latency_ms=latency,
            )
            # VERIFIER (deterministic, no LLM).
            verdict = self._verifier.verify(plan, set(request.evidence_ids))
            self._record(
                steps, "VERIFIER", tenant_id=tenant_id, status=verdict.status,
                evidence_ids=tuple(plan.evidence_required),
                reason_codes=tuple(verdict.reasons),
                attempt=attempt,
            )
            if verdict.status == "ACCEPTED":
                # TOOL + TOOL_RESULT via the deterministic executor.
                for call in sorted(plan.capability_calls,
                                   key=lambda c: c.order_index):
                    self._record(
                        steps, "TOOL", tenant_id=tenant_id, status="called",
                        capability=call.capability, attempt=attempt,
                    )
                outcomes = self._executor.execute(plan, tenant_id)
                for outcome in outcomes:
                    self._record(
                        steps, "TOOL_RESULT", tenant_id=tenant_id,
                        status="ok" if outcome.success else "empty",
                        capability=outcome.capability, attempt=attempt,
                    )
                final_status = "ACCEPTED"
                break
            if verdict.status == "ESCALATE_HITL":
                final_status = "ESCALATE_HITL"
                break
            attempt += 1
            if attempt > _MAX_REPLANS:
                final_status = "REJECTED_REPLAN"
                break
            # Loop continues: the next iteration records NEXT_OUTPUT.
        self._record(steps, "FINAL", tenant_id=tenant_id, status=final_status,
                     attempt=attempt)
        return Trajectory(
            trajectory_id=f"traj-{self._correlation_id}",
            correlation_id=self._correlation_id,
            tenant_id=tenant_id,
            exception_id=request.exception_id,
            mode=self._mode,
            created_at=started,
            steps=tuple(steps),
            final_status=final_status,
        )
