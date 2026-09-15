"""NoOpTracer: zero-cost tracing seam for development and testing.

Every method is a silent no-op.  Zero imports of langfuse — this module
is safe to import unconditionally.  ``NoOpTracer`` is a singleton;
multiple calls to the module-level ``_INSTANCE`` return the same object.
"""

from __future__ import annotations

from typing import Any

from shared.tracing.protocol import TraceContext


class NoOpTracer:
    """TracerProtocol implementation that discards everything.

    Used when ``LANGFUSE_PUBLIC_KEY`` is unset (local dev, unit tests).
    """

    _instance: NoOpTracer | None = None

    def __new__(cls) -> NoOpTracer:
        """Singleton — every instantiation returns the same object."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def trace(self, exception_id: str, tenant_id: str, exception_type: str) -> TraceContext:
        """Return a detached context with the exception_id as trace_id."""
        return TraceContext(trace_id=exception_id, _ref=None)

    def generation(
        self,
        trace_ctx: Any,
        name: str,
        model: str,
        input_data: dict[str, Any],
        output: dict[str, Any],
        usage: dict[str, int],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """No-op: discard generation data."""

    def tool(
        self,
        trace_ctx: Any,
        name: str,
        input_data: dict[str, Any],
        output: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """No-op: discard tool data."""

    def guardrail(
        self,
        trace_ctx: Any,
        stage: str,
        input_data: dict[str, Any],
        output: dict[str, Any],
        passed: bool,
        reasons: list[str],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """No-op: discard guardrail data."""

    def span(
        self,
        trace_ctx: Any,
        name: str,
        input_data: dict[str, Any],
        output: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """No-op: discard span data."""

    def flush(self) -> None:
        """No-op: nothing to flush."""
