"""Observability abstraction: case → verification trace with correlation_id.

Wires the 13-hop trace
``case → context assembly → planner → LLM generation → verifier →
capability call → capability result → replan → final candidate → policy →
approval → execution → verification`` through ``TracerProtocol`` with
``correlation_id`` (webhook fingerprint/idempotency_key → S3 ObjectMeta.key
→ LLM → execution), tenant-safe identifiers (no PII beyond tenant/case),
case identifier, timestamp, latency, status, and bounded evidence references.

All payloads are sanitized via ``shared.tracing.redaction`` before export:
no unrestricted Gmail bodies, Sheets free text, legacy rejections, or
full provider JSON are captured. The Langfuse adapter is optional and
lazy: when ``LANGFUSE_PUBLIC_KEY`` is unset, ``NoOpTracer`` yields
identical financial/policy outcomes with no network call.

Usage::

    from shared.tracing import create_tracer
    from shared.tracing.observability import ObservabilityTrace

    tracer = create_tracer()
    obs = ObservabilityTrace(tracer, correlation_id="CASE-1027",
                             tenant_id="tenant-a", case_id="CASE-1027",
                             exception_type="I-REFUND-LAG")
    ctx = obs.start_case()
    obs.context_assembly(ctx, evidence_ids=("ev-1", "ev-2"), latency_ms=5.2, status="ok")
    obs.llm_generation(ctx, name="planner", model="groq", ...)
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from shared.tracing.correlation import validate_correlation_id
from shared.tracing.protocol import TraceContext, TracerProtocol
from shared.tracing.redaction import sanitize_args, sanitize_input, sanitize_output


def _now() -> datetime:
    return datetime.now(UTC)


def _meta(
    correlation_id: str,
    tenant_id: str,
    case_id: str,
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "correlation_id": correlation_id,
        "tenant_id": tenant_id,
        "case_id": case_id,
    }
    if extra:
        base.update(extra)
    return base


class ObservabilityTrace:
    """High-level 13-hop trace facade over ``TracerProtocol``.

    Each hop records a distinct observation with correlation_id/tenant/case
    in metadata, sanitized inputs/outputs, timestamp, latency, and status.
    No PII beyond tenant/case is retained; free-text bodies are redacted.

    The trace is queryable by ``correlation_id`` (the root ``trace_id``)
    to reconstruct ``CASE-1027 → agent → legacy batch → S3 → ingestion →
    reconciliation``.

    Attributes:
        tracer: Underlying ``TracerProtocol`` (NoOp or Langfuse).
        correlation_id: Unified correlation identifier (tenant-safe).
        tenant_id: Tenant scope (tenant-safe).
        case_id: Case/exception identifier (tenant-safe).
        exception_type: Exception class (e.g. I-REFUND-LAG).
    """

    def __init__(
        self,
        tracer: TracerProtocol,
        *,
        correlation_id: str,
        tenant_id: str,
        case_id: str,
        exception_type: str,
    ) -> None:
        """Bind the trace identity and tracer seam.

        Args:
            tracer: ``TracerProtocol`` seam (NoOp when Langfuse unset).
            correlation_id: Unified correlation_id (webhook → S3 → LLM → exec).
            tenant_id: Tenant scope.
            case_id: Case/exception id (often equals correlation_id).
            exception_type: Exception class for root trace.

        Raises:
            ValueError: If any id violates tenant-safe pattern.
            TypeError: If tracer is None.
        """
        if tracer is None:
            raise TypeError("tracer must be a TracerProtocol, got None.")
        self._tracer = tracer
        self.correlation_id = validate_correlation_id(correlation_id)
        self.tenant_id = validate_correlation_id(tenant_id)
        self.case_id = validate_correlation_id(case_id)
        if not isinstance(exception_type, str) or not exception_type.strip():
            raise ValueError("exception_type must be a non-blank string.")
        self.exception_type = exception_type.strip()
        self._start_ts = _now()

    # ------------------------------------------------------------------
    # Root
    # ------------------------------------------------------------------

    def start_case(self) -> TraceContext:
        """Start the root trace for the case.

        Returns:
            ``TraceContext`` whose ``trace_id`` is the correlation_id (NoOp)
            or an opaque SDK trace_id. All child observations attach via
            this handle.
        """
        ctx = self._tracer.trace(
            exception_id=self.case_id,
            tenant_id=self.tenant_id,
            exception_type=self.exception_type,
        )
        # Record case span with correlation lineage for audit reconstruction
        # (NoOpTracer drops it; Langfuse records it as the root span)
        self._tracer.span(
            ctx,
            "case",
            sanitize_input(
                {
                    "correlation_id": self.correlation_id,
                    "case_id": self.case_id,
                    "exception_type": self.exception_type,
                    "s3_key": f"{self.tenant_id}/{self.case_id}/evidence.json",
                }
            ),
            {"status": "started", "timestamp": _now().isoformat()},
            _meta(
                self.correlation_id,
                self.tenant_id,
                self.case_id,
                extra={"latency_ms": 0, "status": "started"},
            ),
        )
        return ctx

    # ------------------------------------------------------------------
    # Context assembly
    # ------------------------------------------------------------------

    def context_assembly(
        self,
        ctx: TraceContext,
        *,
        evidence_ids: tuple[str, ...] | list[str],
        latency_ms: float | None = None,
        status: str = "ok",
        truncated: bool = False,
    ) -> None:
        """Record the deterministic context-assembly hop.

        Args:
            ctx: Root trace handle.
            evidence_ids: Bounded evidence references (no bodies).
            latency_ms: Assembly latency when measured.
            status: ok|truncated|error.
            truncated: Whether context was truncated (flagged, never silent).
        """
        self._tracer.span(
            ctx,
            "context_assembly",
            sanitize_input(
                {
                    "correlation_id": self.correlation_id,
                    "evidence_ids": list(evidence_ids)[:32],
                    "evidence_count": len(evidence_ids),
                    "truncated": truncated,
                }
            ),
            {"status": status, "timestamp": _now().isoformat()},
            _meta(
                self.correlation_id,
                self.tenant_id,
                self.case_id,
                extra={"latency_ms": latency_ms or 0, "status": status},
            ),
        )

    # ------------------------------------------------------------------
    # Planner
    # ------------------------------------------------------------------

    def planner(
        self,
        ctx: TraceContext,
        *,
        evidence_ids: tuple[str, ...] | list[str] | None = None,
        allowlist: tuple[str, ...] | list[str] | None = None,
        latency_ms: float | None = None,
        status: str = "planned",
    ) -> None:
        """Record the planner invocation (typed selection only)."""
        self._tracer.span(
            ctx,
            "planner",
            sanitize_input(
                {
                    "correlation_id": self.correlation_id,
                    "evidence_ids": list(evidence_ids or [])[:32],
                    "allowlist": list(allowlist or [])[:8],
                }
            ),
            {"status": status, "timestamp": _now().isoformat()},
            _meta(
                self.correlation_id,
                self.tenant_id,
                self.case_id,
                extra={"latency_ms": latency_ms or 0, "status": status},
            ),
        )

    # ------------------------------------------------------------------
    # LLM generation
    # ------------------------------------------------------------------

    def llm_generation(
        self,
        ctx: TraceContext,
        *,
        name: str,
        model: str,
        input_data: dict[str, Any],
        output: dict[str, Any],
        usage: dict[str, int] | None = None,
        latency_ms: float | None = None,
        status: str = "ok",
    ) -> None:
        """Record a bounded LLM generation (no bodies, no secrets)."""
        sanitized_in = sanitize_input(input_data)
        # Never log raw hypothesis bodies beyond 500 chars
        if "hypothesis_text" in sanitized_in:
            from shared.tracing.redaction import redact_pii

            val = sanitized_in["hypothesis_text"]
            if isinstance(val, str) and len(val) > 500:
                sanitized_in["hypothesis_text"] = val[:499] + "…"
            if isinstance(val, str):
                sanitized_in["hypothesis_text"] = redact_pii(sanitized_in["hypothesis_text"])
        sanitized_out = sanitize_output(output)
        self._tracer.generation(
            ctx,
            name,
            model,
            sanitized_in,
            sanitized_out,
            usage or {},
            _meta(
                self.correlation_id,
                self.tenant_id,
                self.case_id,
                extra={"latency_ms": latency_ms or 0, "status": status},
            ),
        )

    # ------------------------------------------------------------------
    # Verifier
    # ------------------------------------------------------------------

    def verifier(
        self,
        ctx: TraceContext,
        *,
        status: str,
        reason_codes: tuple[str, ...] | list[str] | None = None,
        attempt: int = 0,
        latency_ms: float | None = None,
    ) -> None:
        """Record a deterministic verifier gate (pure)."""
        self._tracer.guardrail(
            ctx,
            "verifier",
            sanitize_input(
                {
                    "correlation_id": self.correlation_id,
                    "attempt": attempt,
                    "reason_codes": list(reason_codes or [])[:16],
                }
            ),
            {"status": status, "timestamp": _now().isoformat()},
            passed=(status == "ACCEPTED"),
            reasons=list(reason_codes or []),
            metadata=_meta(
                self.correlation_id,
                self.tenant_id,
                self.case_id,
                extra={"latency_ms": latency_ms or 0, "status": status, "attempt": attempt},
            ),
        )

    # ------------------------------------------------------------------
    # Capability call / result
    # ------------------------------------------------------------------

    def capability_call(
        self,
        ctx: TraceContext,
        *,
        capability: str,
        args: dict[str, Any],
        order_index: int,
        latency_ms: float | None = None,
    ) -> None:
        """Record a capability call (selection only, redacted args)."""
        self._tracer.tool(
            ctx,
            f"capability:{capability}",
            sanitize_args(dict(args), capability=capability),
            {"order_index": order_index, "timestamp": _now().isoformat()},
            _meta(
                self.correlation_id,
                self.tenant_id,
                self.case_id,
                extra={"latency_ms": latency_ms or 0, "capability": capability},
            ),
        )

    def capability_result(
        self,
        ctx: TraceContext,
        *,
        capability: str,
        result_summary: dict[str, Any],
        success: bool,
        latency_ms: float | None = None,
    ) -> None:
        """Record a capability result (metadata only, never raw bodies)."""
        self._tracer.tool(
            ctx,
            f"capability_result:{capability}",
            sanitize_input({"correlation_id": self.correlation_id, "capability": capability}),
            sanitize_output(
                {
                    "success": success,
                    "summary": sanitize_input(result_summary),
                    "timestamp": _now().isoformat(),
                }
            ),
            _meta(
                self.correlation_id,
                self.tenant_id,
                self.case_id,
                extra={"latency_ms": latency_ms or 0, "success": success},
            ),
        )

    # ------------------------------------------------------------------
    # Replan
    # ------------------------------------------------------------------

    def replan(
        self,
        ctx: TraceContext,
        *,
        attempt: int,
        reason_codes: tuple[str, ...] | list[str] | None = None,
        latency_ms: float | None = None,
    ) -> None:
        """Record a bounded replan (identical bounds every attempt)."""
        self._tracer.span(
            ctx,
            "replan",
            sanitize_input(
                {
                    "correlation_id": self.correlation_id,
                    "attempt": attempt,
                    "reason_codes": list(reason_codes or [])[:16],
                }
            ),
            {"status": "replan", "timestamp": _now().isoformat()},
            _meta(
                self.correlation_id,
                self.tenant_id,
                self.case_id,
                extra={"latency_ms": latency_ms or 0, "attempt": attempt},
            ),
        )

    def final_candidate(
        self,
        ctx: TraceContext,
        *,
        hypothesis_ref: str | None = None,
        evidence_required: tuple[str, ...] | list[str] | None = None,
        latency_ms: float | None = None,
        status: str = "candidate",
    ) -> None:
        """Record the final candidate (bounded refs, no bodies)."""
        self._tracer.span(
            ctx,
            "final_candidate",
            sanitize_input(
                {
                    "correlation_id": self.correlation_id,
                    "hypothesis_ref": (hypothesis_ref or "")[:100],
                    "evidence_required": list(evidence_required or [])[:32],
                }
            ),
            {"status": status, "timestamp": _now().isoformat()},
            _meta(
                self.correlation_id,
                self.tenant_id,
                self.case_id,
                extra={"latency_ms": latency_ms or 0, "status": status},
            ),
        )

    # ------------------------------------------------------------------
    # Policy / Approval / Execution / Verification
    # ------------------------------------------------------------------

    def policy(
        self,
        ctx: TraceContext,
        *,
        decision: str,
        reason_codes: tuple[str, ...] | list[str] | None = None,
        latency_ms: float | None = None,
    ) -> None:
        """Record a deterministic policy gate (no financial truth change)."""
        self._tracer.guardrail(
            ctx,
            "policy",
            sanitize_input({"correlation_id": self.correlation_id, "decision": decision}),
            {"status": decision, "timestamp": _now().isoformat()},
            passed=(decision == "ALLOW"),
            reasons=list(reason_codes or []),
            metadata=_meta(
                self.correlation_id,
                self.tenant_id,
                self.case_id,
                extra={"latency_ms": latency_ms or 0, "decision": decision},
            ),
        )

    def approval(
        self,
        ctx: TraceContext,
        *,
        decision: str,
        approver_ref: str | None = None,
        idempotency_key: str | None = None,
        latency_ms: float | None = None,
    ) -> None:
        """Record HITL approval (tenant-safe refs only, no PII)."""
        # idempotency_key is already tenant-safe; sanitize but keep full
        safe_key: str | None = None
        if idempotency_key is not None:
            try:
                validate_correlation_id(idempotency_key)
                safe_key = idempotency_key
            except ValueError:
                safe_key = "[REDACTED]"
        self._tracer.guardrail(
            ctx,
            "approval",
            sanitize_input(
                {
                    "correlation_id": self.correlation_id,
                    "decision": decision,
                    "approver_ref": (approver_ref or "")[:32],
                    "idempotency_key": safe_key,
                }
            ),
            {"status": decision, "timestamp": _now().isoformat()},
            passed=(decision == "APPROVED"),
            reasons=[],
            metadata=_meta(
                self.correlation_id,
                self.tenant_id,
                self.case_id,
                extra={"latency_ms": latency_ms or 0, "decision": decision},
            ),
        )

    def execution(
        self,
        ctx: TraceContext,
        *,
        idempotency_key: str | None = None,
        status: str = "executed",
        latency_ms: float | None = None,
    ) -> None:
        """Record guarded execution (sandbox only, idempotency lineage)."""
        safe_key: str | None = None
        if idempotency_key is not None:
            try:
                validate_correlation_id(idempotency_key)
                safe_key = idempotency_key
            except ValueError:
                safe_key = "[REDACTED]"
        self._tracer.span(
            ctx,
            "execution",
            sanitize_input(
                {
                    "correlation_id": self.correlation_id,
                    "idempotency_key": safe_key,
                    "status": status,
                }
            ),
            {"status": status, "timestamp": _now().isoformat()},
            _meta(
                self.correlation_id,
                self.tenant_id,
                self.case_id,
                extra={"latency_ms": latency_ms or 0, "status": status},
            ),
        )

    def verification(
        self,
        ctx: TraceContext,
        *,
        status: str,
        latency_ms: float | None = None,
    ) -> None:
        """Record post-execution verification (mandatory tripwire)."""
        self._tracer.guardrail(
            ctx,
            "verification",
            sanitize_input({"correlation_id": self.correlation_id}),
            {"status": status, "timestamp": _now().isoformat()},
            passed=(status == "VERIFIED"),
            reasons=[],
            metadata=_meta(
                self.correlation_id,
                self.tenant_id,
                self.case_id,
                extra={"latency_ms": latency_ms or 0, "status": status},
            ),
        )

    def flush(self) -> None:
        """Flush buffered observations (NoOp drops, Langfuse exports)."""
        self._tracer.flush()

    # ------------------------------------------------------------------
    # Timing helper
    # ------------------------------------------------------------------

    def timed(self) -> _Timer:
        """Return a timing helper for latency measurement."""
        return _Timer()


class _Timer:
    """Simple monotonic timer for latency_ms."""

    def __init__(self) -> None:
        self._start = time.monotonic()

    def elapsed_ms(self) -> float:
        """Return elapsed milliseconds since creation."""
        return (time.monotonic() - self._start) * 1000.0
