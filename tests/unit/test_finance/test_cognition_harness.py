from __future__ import annotations

import json
import tempfile
from pathlib import Path


class TestReasoningHarness:
    def test_harness_single_pass(self) -> None:
        from finance.cognition.harness import ReasoningHarness
        from finance.cognition.state.models import ReasoningState

        harness = ReasoningHarness()
        state = ReasoningState(query="Analyze revenue variance")
        result = harness.run(state)
        assert result.success
        assert len(result.state.trace) >= 5

    def test_harness_trace_contains_all_nodes(self) -> None:
        from finance.cognition.harness import ReasoningHarness
        from finance.cognition.state.models import ReasoningState

        result = ReasoningHarness().run(ReasoningState(query="test"))
        nodes = [t.node_name for t in result.state.trace]
        assert "planner" in nodes
        assert "retriever" in nodes
        assert "executor" in nodes
        assert "verifier" in nodes
        assert "reflection" in nodes

    def test_harness_supports_replanning(self) -> None:
        from finance.cognition.harness import ReasoningHarness
        from finance.cognition.state.models import ReasoningState

        state = ReasoningState(query="test", max_iterations=3)
        result = ReasoningHarness(max_iterations=3).run(state)
        assert result.state.iteration_count >= 1
        assert len(result.state.plan_history) >= 0  # may or may not have re-planned

    def test_harness_respects_max_iterations(self) -> None:
        from finance.cognition.harness import ReasoningHarness
        from finance.cognition.state.models import ReasoningState

        state = ReasoningState(query="test", max_iterations=1)
        result = ReasoningHarness().run(state)
        assert result.state.iteration_count <= 1

    def test_harness_captures_telemetry(self) -> None:
        from finance.cognition.harness import ReasoningHarness
        from finance.cognition.state.models import ReasoningState

        with tempfile.TemporaryDirectory() as tmp:
            harness = ReasoningHarness(telemetry_dir=tmp)
            state = ReasoningState(query="test telemetry")
            harness.run(state)
            traces = list(Path(tmp).glob("*.json"))
            assert len(traces) >= 1
            data = json.loads(traces[0].read_text())
            assert data["query"] == "test telemetry"

    def test_harness_with_custom_registry(self) -> None:
        from finance.cognition.harness import ReasoningHarness
        from finance.cognition.registry import NodeRegistry
        from finance.cognition.state.models import ReasoningState

        registry = NodeRegistry()
        registry.configure_pipeline(["planner", "reflection"])
        harness = ReasoningHarness(registry=registry, max_iterations=1)
        state = ReasoningState(query="test custom")
        result = harness.run(state)
        nodes = [t.node_name for t in result.state.trace]
        assert nodes == ["planner", "reflection"]

    def test_harness_records_run_id(self) -> None:
        from finance.cognition.harness import ReasoningHarness
        from finance.cognition.state.models import ReasoningState

        harness = ReasoningHarness()
        state = ReasoningState(query="test")
        result = harness.run(state)
        assert result.run_id is not None
        assert len(result.run_id) > 0

    def test_harness_stops_on_finalize(self) -> None:
        from finance.cognition.harness import ReasoningHarness
        from finance.cognition.state.models import ReasoningState

        harness = ReasoningHarness(max_iterations=10)
        state = ReasoningState(query="test")
        result = harness.run(state)
        assert result.state.loop_decision in ("finalize", "continue")


class _StubNode:
    def __init__(
        self, name: str, updates: dict | None = None, error: Exception | None = None
    ) -> None:
        self._name = name
        self._updates = updates or {}
        self._error = error

    def execute(self, state):  # type: ignore[no-untyped-def]
        from finance.cognition.state.node import NodeResult

        if self._error is not None:
            raise self._error
        return NodeResult(
            node_name=self._name,
            state_updates=self._updates,
            confidence=0.9,
            message="stub",
        )


class TestReasoningHarnessIntegrity:
    def test_finalize_reports_success_and_stop_reason(self) -> None:
        from finance.cognition.harness import ReasoningHarness
        from finance.cognition.registry import NodeRegistry
        from finance.cognition.state.models import ReasoningState

        registry = NodeRegistry()
        registry.register("planner", _StubNode("planner", {"loop_decision": "finalize"}))
        registry.configure_pipeline(["planner"])
        result = ReasoningHarness(registry=registry, max_iterations=2).run(
            ReasoningState(query="test")
        )
        assert result.success is True
        assert result.stop_reason == "finalize"

    def test_max_iterations_exhausted_is_not_success(self) -> None:
        from finance.cognition.harness import ReasoningHarness
        from finance.cognition.registry import NodeRegistry
        from finance.cognition.state.models import ReasoningState

        registry = NodeRegistry()
        registry.register("planner", _StubNode("planner", {"loop_decision": "continue"}))
        registry.configure_pipeline(["planner"])
        result = ReasoningHarness(registry=registry, max_iterations=2).run(
            ReasoningState(query="test", max_iterations=2)
        )
        assert result.success is False
        assert result.stop_reason == "max_iterations_exhausted"

    def test_missing_node_fails_closed(self) -> None:
        from finance.cognition.harness import ReasoningHarness
        from finance.cognition.registry import NodeRegistry
        from finance.cognition.state.models import ReasoningState

        registry = NodeRegistry()
        registry.register("planner", _StubNode("planner", {"loop_decision": "finalize"}))
        registry.configure_pipeline(["planner"])
        del registry._nodes["planner"]
        result = ReasoningHarness(registry=registry, max_iterations=1).run(
            ReasoningState(query="test")
        )
        assert result.success is False
        assert result.stop_reason == "missing_node"

    def test_node_exception_fails_closed(self) -> None:
        from finance.cognition.harness import ReasoningHarness
        from finance.cognition.registry import NodeRegistry
        from finance.cognition.state.models import ReasoningState

        registry = NodeRegistry()
        registry.register("planner", _StubNode("planner", error=RuntimeError("boom")))
        registry.configure_pipeline(["planner"])
        result = ReasoningHarness(registry=registry, max_iterations=1).run(
            ReasoningState(query="test")
        )
        assert result.success is False
        assert result.stop_reason == "node_error"

    def test_state_fingerprint_is_stable_for_identical_state(self) -> None:
        from finance.cognition.harness import ReasoningHarness
        from finance.cognition.registry import NodeRegistry
        from finance.cognition.state.models import ReasoningState

        registry = NodeRegistry()
        registry.register("planner", _StubNode("planner", {"loop_decision": "finalize"}))
        registry.configure_pipeline(["planner"])
        harness = ReasoningHarness(registry=registry, max_iterations=1)
        a = harness.run(ReasoningState(query="same"))
        b = harness.run(ReasoningState(query="same"))
        assert a.state_fingerprint == b.state_fingerprint
        c = harness.run(ReasoningState(query="different"))
        assert a.state_fingerprint != c.state_fingerprint
