"""Unit tests for the NoOpTracer.

Verifies singleton behaviour, no-op semantics, absence of langfuse imports,
and flush safety.  All tests are pure-logic — zero network, zero SDK.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from shared.tracing.noop import NoOpTracer
from shared.tracing.protocol import TraceContext

# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    """NoOpTracer must be a true singleton."""

    def test_same_instance_on_repeated_instantiation(self) -> None:
        a = NoOpTracer()
        b = NoOpTracer()
        assert a is b

    def test_isinstance_check(self) -> None:
        assert isinstance(NoOpTracer(), NoOpTracer)


# ---------------------------------------------------------------------------
# trace() return value
# ---------------------------------------------------------------------------


class TestTraceContext:
    """trace() must return a _NoOpContext with the exception_id."""

    def test_returns_noop_context(self) -> None:
        ctx = NoOpTracer().trace("exc-1", "t-1", "RevenueDecline")
        assert isinstance(ctx, TraceContext)

    def test_trace_id_matches_exception_id(self) -> None:
        ctx = NoOpTracer().trace("exc-42", "t-99", "SomeError")
        assert ctx.trace_id == "exc-42"

    def test_context_is_frozen(self) -> None:
        ctx = NoOpTracer().trace("exc-1", "t-1", "E")
        with pytest.raises(AttributeError):
            ctx.trace_id = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# No-op methods
# ---------------------------------------------------------------------------


class TestNoOpMethods:
    """All observation methods return None silently."""

    def setup_method(self) -> None:
        self.tracer = NoOpTracer()
        self.ctx = self.tracer.trace("exc-1", "t-1", "E")

    def test_generation_returns_none(self) -> None:
        self.tracer.generation(self.ctx, "plan", "gpt-4", {"q": "hi"}, {"a": "ok"}, {"tokens": 10})

    def test_tool_returns_none(self) -> None:
        self.tracer.tool(self.ctx, "sql_query", {"sql": "SELECT 1"}, {"rows": 1})

    def test_guardrail_returns_none(self) -> None:
        self.tracer.guardrail(
            self.ctx,
            "policy_check",
            {"claim": "x"},
            {"result": "pass"},
            True,
            ["no violations"],
        )

    def test_span_returns_none(self) -> None:
        self.tracer.span(self.ctx, "planner_step", {"step": 1}, {"done": True})

    def test_flush_returns_none(self) -> None:
        self.tracer.flush()


# ---------------------------------------------------------------------------
# flush() safety
# ---------------------------------------------------------------------------


class TestFlushSafety:
    """flush() must be callable at any time, even without prior traces."""

    def test_flush_without_trace(self) -> None:
        NoOpTracer().flush()  # must not raise

    def test_flush_after_trace(self) -> None:
        t = NoOpTracer()
        t.trace("e", "t", "E")
        t.flush()  # must not raise


# ---------------------------------------------------------------------------
# Zero langfuse imports (AST scan)
# ---------------------------------------------------------------------------


class TestNoLangfuseImports:
    """noop.py must NEVER import langfuse — verified via AST."""

    def test_no_langfuse_import_in_source(self) -> None:
        source_path = Path(inspect.getfile(NoOpTracer))
        source = source_path.read_text()
        tree = ast.parse(source)

        langfuse_refs: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if "langfuse" in alias.name.lower():
                        langfuse_refs.append(f"import {alias.name}")
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module
                and "langfuse" in node.module.lower()
            ):
                langfuse_refs.append(f"from {node.module} import ...")

        assert langfuse_refs == [], f"noop.py must not import langfuse, found: {langfuse_refs}"
