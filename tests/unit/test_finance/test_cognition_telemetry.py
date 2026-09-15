from __future__ import annotations

import json
import tempfile
from pathlib import Path


class TestReasoningTelemetry:
    def test_telemetry_captures_trace(self) -> None:
        from finance.cognition.state.models import ReasoningState
        from finance.cognition.telemetry import ReasoningTelemetry

        with tempfile.TemporaryDirectory() as tmp:
            telemetry = ReasoningTelemetry(output_dir=tmp)
            state = ReasoningState(query="test query")
            state.record_step(
                node_name="planner", result={"plan": ["a"]}, confidence=0.5
            )
            state.overall_confidence = 0.85
            state.loop_decision = "finalize"
            path = telemetry.capture(run_id="test_run_001", state=state)
            assert path.exists()
            data = json.loads(path.read_text())
            assert data["run_id"] == "test_run_001"
            assert data["query"] == "test query"
            assert data["overall_confidence"] == 0.85
            assert data["loop_decision"] == "finalize"
            assert len(data["trace"]) == 1

    def test_telemetry_directory_created(self) -> None:
        from finance.cognition.state.models import ReasoningState
        from finance.cognition.telemetry import ReasoningTelemetry

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "traces"
            telemetry = ReasoningTelemetry(output_dir=str(output_dir))
            state = ReasoningState(query="test")
            path = telemetry.capture(run_id="test_dir", state=state)
            assert output_dir.exists()
            assert path.parent == output_dir

    def test_telemetry_includes_assertions(self) -> None:
        from finance.cognition.state.models import ReasoningState
        from finance.cognition.telemetry import ReasoningTelemetry
        from shared.models.assertions import Assertion, AssertionType

        with tempfile.TemporaryDirectory() as tmp:
            telemetry = ReasoningTelemetry(output_dir=tmp)
            state = ReasoningState(query="test")
            state.add_assertions(
                [
                    Assertion(
                        id="a1",
                        type=AssertionType.NUMERIC,
                        text="test",
                        confidence=0.9,
                    ),
                ]
            )
            path = telemetry.capture(run_id="test_assert", state=state)
            data = json.loads(path.read_text())
            assert len(data["assertions"]) == 1
            assert data["assertions"][0]["id"] == "a1"

    def test_telemetry_includes_action_traces(self) -> None:
        from finance.cognition.state.action import ActionPlan, ActionStatus
        from finance.cognition.state.models import ReasoningState
        from finance.cognition.telemetry import ReasoningTelemetry

        with tempfile.TemporaryDirectory() as tmp:
            telemetry = ReasoningTelemetry(output_dir=tmp)
            state = ReasoningState(query="test")
            plan = ActionPlan(iteration=0)
            a = plan.add(objective="determine_revenue_variance")
            a.status = ActionStatus.SUCCESS
            a.tool = "variance_engine"
            a.latency_ms = 42.5
            a.retry_count = 0
            state.action_plan = plan
            state.context["action_traces"] = [{
                "action_id": a.id,
                "objective": a.objective,
                "tool": a.tool,
                "status": "success",
                "latency_ms": 42.5,
                "retries": 0,
                "assertion_count": 2,
                "evidence_count": 0,
                "validation_status": "unchecked",
                "error": "",
            }]
            path = telemetry.capture(run_id="test_traces", state=state)
            data = json.loads(path.read_text())
            assert "action_traces" in data
            assert len(data["action_traces"]) == 1
            assert data["action_traces"][0]["tool"] == "variance_engine"

    def test_telemetry_includes_plan_history(self) -> None:
        from finance.cognition.state.action import ActionPlan
        from finance.cognition.state.models import ReasoningState
        from finance.cognition.telemetry import ReasoningTelemetry

        with tempfile.TemporaryDirectory() as tmp:
            telemetry = ReasoningTelemetry(output_dir=tmp)
            state = ReasoningState(query="test")
            plan1 = ActionPlan(iteration=0)
            plan1.add(objective="first_plan")
            state.plan_history.append(plan1)
            path = telemetry.capture(run_id="test_history", state=state)
            data = json.loads(path.read_text())
            assert "plan_history" in data
            assert len(data["plan_history"]) == 1
            assert data["plan_history"][0]["iteration"] == 0
