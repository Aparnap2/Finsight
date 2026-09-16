"""PhoenixTracer: OTel backend via phoenix.otel.register.

Wraps ``phoenix.otel.register`` (TracerProvider, OTel, project_name,
endpoint ``http://localhost:6006/v1/traces``, auto_instrument, batch)
behind :class:`shared.tracing.protocol.TracerProtocol`.

Design constraints:
- Credential-safe: all payloads pass through ``shared.tracing.redaction``
  before export — no secrets, emails, or unrestricted Gmail bodies.
- No financial authority: read-only observability seam. Never mutates
  ledger, budget, or approval state; only records spans.
- Vendors are replaceable (NoOpTracer | PhoenixTracer | LangfuseTracer)
  behind the same protocol; callers must not branch on backend.
- Local deployment: default endpoint is ``http://localhost:6006/v1/traces``
  (docker-compose.phoenix.yml, no SaaS account, reproducible).

OTel mapping:
- ``trace`` → root span ``exception_resolution``
- ``generation`` → span ``as_type=generation`` (LLM)
- ``tool`` → span ``as_type=tool``
- ``guardrail`` → span ``as_type=guardrail``
- ``span`` → generic span
- ``flush`` → ``TracerProvider.force_flush()`` (batch) or no-op

All ``phoenix`` / ``opentelemetry`` imports are lazy — the SDK is only
loaded when this class is instantiated (which only happens when
``PHOENIX_COLLECTOR_ENDPOINT`` is set). Unit tests mock
``phoenix.otel.register`` so no real collector is required.
"""

from __future__ import annotations

import contextlib
import json
import logging
from typing import Any

from shared.tracing.protocol import TraceContext
from shared.tracing.redaction import sanitize_args, sanitize_input, sanitize_output

logger = logging.getLogger(__name__)

DEFAULT_ENDPOINT = "http://localhost:6006/v1/traces"
DEFAULT_PROJECT = "finsight"


def _safe_json(value: Any) -> str:
    """JSON-serialize *value* with fallback for non-serializable types."""
    try:
        return json.dumps(value, default=str, ensure_ascii=False)
    except Exception:
        return str(value)


class PhoenixTracer:
    """TracerProtocol implementation backed by Arize Phoenix OTel.

    Args:
        endpoint: OTLP HTTP endpoint. Defaults to
            ``http://localhost:6006/v1/traces`` (local compose).
        project_name: Phoenix project name. Defaults to ``finsight``.
        auto_instrument: Whether Phoenix auto-instruments LLM frameworks.
        batch: Whether to use batch span processor (buffered export).

    Attributes:
        endpoint: Effective collector endpoint.
        project_name: Effective project name.
    """

    def __init__(
        self,
        endpoint: str = DEFAULT_ENDPOINT,
        project_name: str = DEFAULT_PROJECT,
        *,
        auto_instrument: bool = True,
        batch: bool = True,
    ) -> None:
        self.endpoint = endpoint or DEFAULT_ENDPOINT
        self.project_name = project_name or DEFAULT_PROJECT
        self._auto_instrument = auto_instrument
        self._batch = batch

        # Lazy import — only loaded when Phoenix is actually requested.
        try:
            from phoenix.otel import register  # noqa: PLC0415
        except ImportError as exc:
            msg = (
                "arize-phoenix with OTel extras is required for PhoenixTracer. "
                "Install with: uv pip install arize-phoenix opentelemetry-exporter-otlp"
            )
            raise ImportError(msg) from exc

        # phoenix.otel.register signature varies across versions — tolerate
        # missing `batch` kwarg.
        try:
            self._provider = register(
                project_name=self.project_name,
                endpoint=self.endpoint,
                auto_instrument=self._auto_instrument,
                batch=self._batch,
            )
        except TypeError:
            # Older phoenix without `batch` param
            self._provider = register(
                project_name=self.project_name,
                endpoint=self.endpoint,
                auto_instrument=self._auto_instrument,
            )

        # Resolve OTel tracer from the provider.
        self._tracer: Any = None
        try:
            from opentelemetry import trace as otel_trace  # noqa: PLC0415

            # Phoenix register sets the global TracerProvider; use it.
            self._tracer = otel_trace.get_tracer(__name__)
        except Exception:
            # Fallback: keep provider but no tracer (tests mock this path)
            self._tracer = None

        # In-memory capture for inspectability in tests (bounded, no PII).
        self._spans: list[dict[str, Any]] = []

        logger.debug(
            "PhoenixTracer initialised project=%s endpoint=%s auto_instrument=%s batch=%s",
            self.project_name,
            self.endpoint,
            self._auto_instrument,
            self._batch,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _record(
        self,
        kind: str,
        name: str,
        trace_ctx: TraceContext | None,
        input_data: dict[str, Any],
        output: dict[str, Any],
        metadata: dict[str, Any] | None,
    ) -> None:
        """Record a span via OTel and capture bounded copy for tests."""
        safe_input = sanitize_input(dict(input_data)) if isinstance(input_data, dict) else {}
        safe_output = sanitize_output(dict(output)) if isinstance(output, dict) else {}
        meta = dict(metadata or {})

        # Enforce bounded context: evidence lists, free text already truncated
        # by redaction helpers. Capture for test inspectability.
        self._spans.append(
            {
                "kind": kind,
                "name": name,
                "input": safe_input,
                "output": safe_output,
                "metadata": meta,
                "trace_id": trace_ctx.trace_id if trace_ctx else None,
            }
        )

        # Attempt real OTel export when tracer is available (mocked in tests).
        if self._tracer is None:
            return
        try:
            # Use start_as_current_span when available; fall back to start_span.
            span_cm = None
            if hasattr(self._tracer, "start_as_current_span"):
                span_cm = self._tracer.start_as_current_span(name)
            elif hasattr(self._tracer, "start_span"):
                span_cm = self._tracer.start_span(name)

            if span_cm is None:
                return

            # span_cm may be a context manager or a Span object.
            if hasattr(span_cm, "__enter__"):
                with span_cm as span:
                    self._set_span_attributes(span, kind, safe_input, safe_output, meta)
            else:
                span = span_cm
                self._set_span_attributes(span, kind, safe_input, safe_output, meta)
                with contextlib.suppress(Exception):
                    span.end()
        except Exception as exc:
            logger.debug("PhoenixTracer OTel export failed (non-fatal): %s", exc)

    def _set_span_attributes(
        self,
        span: Any,
        kind: str,
        safe_input: dict[str, Any],
        safe_output: dict[str, Any],
        metadata: dict[str, Any],
    ) -> None:
        """Set tenant-safe attributes on an OTel span."""
        try:
            span.set_attribute("finsight.kind", kind)
            span.set_attribute("finsight.input", _safe_json(safe_input)[:4000])
            span.set_attribute("finsight.output", _safe_json(safe_output)[:4000])
            for k, v in metadata.items():
                # Only scalar metadata as attributes (OTel restriction)
                if isinstance(v, (str, int, float, bool)):
                    span.set_attribute(f"finsight.{k}", v)
                else:
                    span.set_attribute(f"finsight.{k}", _safe_json(v)[:1000])
        except Exception:
            pass

    # ------------------------------------------------------------------
    # TracerProtocol
    # ------------------------------------------------------------------

    def trace(self, exception_id: str, tenant_id: str, exception_type: str) -> TraceContext:
        """Start a root trace and return an opaque handle.

        The public ``trace_id`` is the tenant-safe ``exception_id``
        (e.g. ``CASE-1027``) so the trajectory is queryable by
        correlation_id. The OTel span context is stored in ``_ref`` for
        child observations — callers MUST NOT inspect it.
        """
        # Sanitize root attributes (no PII beyond tenant/case)
        safe_input = sanitize_input(
            {
                "exception_id": exception_id,
                "tenant_id": tenant_id,
                "exception_type": exception_type,
            }
        )
        # Record root span for 13-hop completeness (queryable by correlation_id)
        root_trace_ctx = TraceContext(trace_id=exception_id, _ref=None)
        self._record(
            "span",
            "exception_resolution",
            root_trace_ctx,
            safe_input,
            {"status": "started"},
            {
                "correlation_id": exception_id,
                "tenant_id": tenant_id,
                "case_id": exception_id,
                "exception_type": exception_type,
            },
        )

        # Create a root OTel span for correlation when tracer exists.
        root_ctx: Any = None
        if self._tracer is not None:
            try:
                if hasattr(self._tracer, "start_span"):
                    root_ctx = self._tracer.start_span("exception_resolution")
                # Keep span open for batch flush; store for child context.
            except Exception:
                root_ctx = None

        return TraceContext(trace_id=exception_id, _ref=root_ctx)

    def generation(
        self,
        trace_ctx: TraceContext,
        name: str,
        model: str,
        input_data: dict[str, Any],
        output: dict[str, Any],
        usage: dict[str, int],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record an LLM generation (sanitized, no secrets)."""
        merged_meta = dict(metadata or {})
        merged_meta.setdefault("model", model)
        if usage:
            merged_meta["usage"] = dict(usage)
        self._record("generation", name, trace_ctx, dict(input_data), dict(output), merged_meta)

    def tool(
        self,
        trace_ctx: TraceContext,
        name: str,
        input_data: dict[str, Any],
        output: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a deterministic tool / capability call (sanitized)."""
        cap = name.split(":", 1)[-1] if ":" in name else None
        if isinstance(input_data, dict):
            safe_in = sanitize_args(dict(input_data), capability=cap)
        else:
            safe_in = {}
        # Ensure generic sanitization as well (PII, bodies)
        safe_in = sanitize_input(safe_in, capability=cap)
        safe_out = sanitize_output(dict(output)) if isinstance(output, dict) else {}
        self._record("tool", name, trace_ctx, safe_in, safe_out, metadata)

    def guardrail(
        self,
        trace_ctx: TraceContext,
        stage: str,
        input_data: dict[str, Any],
        output: dict[str, Any],
        passed: bool,
        reasons: list[str],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a guardrail / policy / verifier gate (sanitized)."""
        merged_meta = dict(metadata or {})
        merged_meta["passed"] = passed
        merged_meta["reasons"] = list(reasons or [])
        self._record(
            "guardrail",
            f"guardrail:{stage}",
            trace_ctx,
            dict(input_data),
            dict(output),
            merged_meta,
        )

    def span(
        self,
        trace_ctx: TraceContext,
        name: str,
        input_data: dict[str, Any],
        output: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a generic span (sanitized, bounded)."""
        self._record("span", name, trace_ctx, dict(input_data), dict(output), metadata)

    def flush(self) -> None:
        """Flush buffered spans via the TracerProvider (batch export)."""
        try:
            if hasattr(self._provider, "force_flush"):
                self._provider.force_flush()
            elif hasattr(self._provider, "flush"):
                self._provider.flush()
        except Exception as exc:
            logger.debug("PhoenixTracer flush failed (non-fatal): %s", exc)

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------

    @property
    def spans(self) -> list[dict[str, Any]]:
        """Bounded in-memory span capture for tests (no PII)."""
        return list(self._spans)

    @property
    def otel_endpoint(self) -> str:
        """OTel collector endpoint (inspectable for deployment test)."""
        return self.endpoint
