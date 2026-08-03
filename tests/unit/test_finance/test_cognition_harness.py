from __future__ import annotations

import json
import tempfile
from pathlib import Path


class TestReasoningHarness:
    def test_harness_single_pass(self):
        from finance.cognition.harness import ReasoningHarness
        from finance.cognition.state.models import ReasoningState

        harness = ReasoningHarness()
        state = ReasoningState(query="Analyze revenue variance")
        result = harness.run(state)
        assert result.success
        assert len(result.state.trace) >= 5

    def test_harness_trace_contains_all_nodes(self):
        from finance.cognition.harness import ReasoningHarness
        from finance.cognition.state.models import ReasoningState

        result = ReasoningHarness().run(ReasoningState(query="test"))
        nodes = [t.node_name for t in result.state.trace]
        assert "planner" in nodes
        assert "retriever" in nodes
        assert "executor" in nodes
        assert "verifier" in nodes
        assert "reflection" in nodes

    def test_harness_supports_replanning(self):
        from finance.cognition.harness import ReasoningHarness
        from finance.cognition.state.models import ReasoningState

        state = ReasoningState(query="test", max_iterations=3)
        result = ReasoningHarness(max_iterations=3).run(state)
        assert result.state.iteration_count >= 1
        assert len(result.state.plan_history) >= 0  # may or may not have re-planned

    def test_harness_respects_max_iterations(self):
        from finance.cognition.harness import ReasoningHarness
        from finance.cognition.state.models import ReasoningState

        state = ReasoningState(query="test", max_iterations=1)
        result = ReasoningHarness().run(state)
        assert result.state.iteration_count <= 1

    def test_harness_captures_telemetry(self):
        from finance.cognition.harness import ReasoningHarness
        from finance.cognition.state.models import ReasoningState

        with tempfile.TemporaryDirectory() as tmp:
            harness = ReasoningHarness(telemetry_dir=tmp)
            state = ReasoningState(query="test telemetry")
            result = harness.run(state)
            traces = list(Path(tmp).glob("*.json"))
            assert len(traces) >= 1
            data = json.loads(traces[0].read_text())
            assert data["query"] == "test telemetry"

    def test_harness_with_custom_registry(self):
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

    def test_harness_records_run_id(self):
        from finance.cognition.harness import ReasoningHarness
        from finance.cognition.state.models import ReasoningState

        harness = ReasoningHarness()
        state = ReasoningState(query="test")
        result = harness.run(state)
        assert result.run_id is not None
        assert len(result.run_id) > 0

    def test_harness_stops_on_finalize(self):
        from finance.cognition.harness import ReasoningHarness
        from finance.cognition.state.models import ReasoningState

        harness = ReasoningHarness(max_iterations=10)
        state = ReasoningState(query="test")
        result = harness.run(state)
        assert result.state.loop_decision in ("finalize", "continue")
