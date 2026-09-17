"""LangfuseTracer: production tracing backed by Langfuse SDK v4.

All langfuse imports are lazy — the SDK is only loaded when this class
is instantiated (which only happens when LANGFUSE_PUBLIC_KEY is set).

Implementation notes:
    - Uses ``start_as_current_observation()`` for tool/guardrail/span
    - Uses ``start_as_current_generation()`` for model/usage metrics
    - Truncates ``hypothesis_text`` to 500 chars and ``args`` values to
      100 chars to stay within Langfuse payload limits.
"""

from __future__ import annotations

import logging
from typing import Any

from shared.tracing.protocol import TraceContext
from shared.tracing.redaction import sanitize_args, sanitize_input, sanitize_output

logger = logging.getLogger(__name__)

_HYPOTHESIS_MAX = 500
_ARG_VALUE_MAX = 100


def _truncate(text: str, limit: int) -> str:
    """Truncate *text* to *limit* chars, appending ``…`` when clipped."""
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _truncate_args(args: dict[str, Any]) -> dict[str, Any]:
    """Recursively truncate string values inside *args* to ``_ARG_VALUE_MAX``."""
    out: dict[str, Any] = {}
    for k, v in args.items():
        if isinstance(v, str):
            out[k] = _truncate(v, _ARG_VALUE_MAX)
        else:
            out[k] = v
    return out


class LangfuseTracer:
    """TracerProtocol implementation backed by Langfuse SDK v4."""

    def __init__(
        self,
        public_key: str,
        secret_key: str,
        host: str = "https://cloud.langfuse.com",
    ) -> None:
        """Lazy-import and configure the Langfuse SDK.

        Args:
            public_key: Langfuse public key.
            secret_key: Langfuse secret key.
            host: Langfuse backend URL.
        """
        # Lazy import — only loaded when the tracer is actually created.
        from langfuse import Langfuse  # noqa: PLC0415

        self._langfuse = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=host,
        )
        logger.debug("LangfuseTracer initialised (host=%s)", host)

    # ------------------------------------------------------------------
    # TracerProtocol
    # ------------------------------------------------------------------

    def trace(self, exception_id: str, tenant_id: str, exception_type: str) -> TraceContext:
        """Start a root trace observation and return a ``TraceContext``."""
        self._langfuse.start_as_current_observation(
            name="exception_resolution",
            as_type="span",
            input={
                "exception_id": exception_id,
                "tenant_id": tenant_id,
                "exception_type": exception_type,
            },
            metadata={
                "tenant_id": tenant_id,
                "exception_type": exception_type,
            },
        )
        # obs is a LangfuseSpan wrapping a TraceContext internally.
        # Retrieve the SDK TraceContext so child observations can attach.
        sdk_ctx = self._langfuse.get_trace_context()
        return TraceContext(trace_id=sdk_ctx.trace_id, _ref=sdk_ctx)

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
        """Record an LLM generation under the given trace (sanitized)."""
        safe_input = sanitize_input(dict(input_data))
        if "hypothesis_text" in safe_input:
            safe_input["hypothesis_text"] = _truncate(
                str(safe_input["hypothesis_text"]), _HYPOTHESIS_MAX
            )
        safe_output = sanitize_output(dict(output))

        with self._langfuse.start_as_current_observation(
            name=name,
            as_type="generation",
            trace_context=trace_ctx._ref,
            input=safe_input,
            output=safe_output,
            model=model,
            usage_details=usage,
            metadata=metadata or {},
        ):
            pass  # context-manager exit calls .end()

    def tool(
        self,
        trace_ctx: TraceContext,
        name: str,
        input_data: dict[str, Any],
        output: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a deterministic tool call (sanitized, no Gmail bodies)."""
        # Extract capability name from tool name (e.g. capability:search_gmail)
        cap = name.split(":", 1)[-1] if ":" in name else None
        safe_input: dict[str, Any]
        if isinstance(input_data, dict):
            # If input looks like args, sanitize as args; else generic sanitize
            safe_input = sanitize_args(dict(input_data), capability=cap)
            # Also apply generic input sanitization for free-text fields
            safe_input = sanitize_input(safe_input, capability=cap)
        else:
            safe_input = {}
        safe_output = sanitize_output(dict(output)) if isinstance(output, dict) else {}

        with self._langfuse.start_as_current_observation(
            name=name,
            as_type="tool",
            trace_context=trace_ctx._ref,
            input=safe_input,
            output=safe_output,
            metadata=metadata or {},
        ):
            pass

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
        """Record a guardrail check result (sanitized)."""
        merged_meta = dict(metadata or {})
        merged_meta["passed"] = passed
        merged_meta["reasons"] = reasons

        with self._langfuse.start_as_current_observation(
            name=f"guardrail:{stage}",
            as_type="guardrail",
            trace_context=trace_ctx._ref,
            input=sanitize_input(dict(input_data)),
            output=sanitize_output(dict(output)),
            metadata=merged_meta,
        ):
            pass

    def span(
        self,
        trace_ctx: TraceContext,
        name: str,
        input_data: dict[str, Any],
        output: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a generic span (sanitized)."""
        with self._langfuse.start_as_current_observation(
            name=name,
            as_type="span",
            trace_context=trace_ctx._ref,
            input=sanitize_input(dict(input_data)),
            output=sanitize_output(dict(output)),
            metadata=metadata or {},
        ):
            pass

    def flush(self) -> None:
        """Flush all buffered observations to Langfuse."""
        self._langfuse.flush()
