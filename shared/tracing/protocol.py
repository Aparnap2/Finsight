"""TracerProtocol: the single seam for all tracing calls.

Domain and agent code MUST depend on this protocol only — no direct SDK
imports.  The protocol is intentionally minimal: five observation methods
(trace, generation, tool, guardrail, span) plus a flush gate.

``TraceContext`` is a frozen dataclass carrying a public trace_id and an
opaque internal reference (the Langfuse ``TraceContext`` object) that
callers must not inspect.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Protocol, runtime_checkable


@dataclasses.dataclass(frozen=True)
class TraceContext:
    """Opaque handle returned by :meth:`TracerProtocol.trace`.

    Attributes:
        trace_id: Public identifier safe to log and surface in UIs.
        _ref: Internal SDK reference — callers MUST NOT inspect or pass
            this to any API other than the originating tracer.
    """

    trace_id: str
    _ref: Any = dataclasses.field(repr=False, compare=False)


@runtime_checkable
class TracerProtocol(Protocol):
    """Swappable tracing backend.  All methods are credential-safe."""

    def trace(self, exception_id: str, tenant_id: str, exception_type: str) -> TraceContext:
        """Start a root trace and return a handle for child observations."""
        ...

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
        """Record an LLM generation (model, tokens, latency)."""
        ...

    def tool(
        self,
        trace_ctx: TraceContext,
        name: str,
        input_data: dict[str, Any],
        output: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a deterministic tool / SQL / API call."""
        ...

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
        """Record a guardrail check (policy, validation, assertion)."""
        ...

    def span(
        self,
        trace_ctx: TraceContext,
        name: str,
        input_data: dict[str, Any],
        output: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a generic span (planner step, reasoning, etc.)."""
        ...

    def flush(self) -> None:
        """Ensure all buffered observations are exported."""
        ...
