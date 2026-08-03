"""Tests for the cognitive state machine (Task 1.1 + Task 1.2)."""

from __future__ import annotations


class TestReasoningState:
    """Task 1.1 — ReasoningState and TraceEntry models."""

    def test_reasoning_state_creation(self) -> None:
        from finance.cognition.state.models import ReasoningState

        state = ReasoningState(query="Analyze revenue variance")
        assert state.query == "Analyze revenue variance"
        assert state.step == 0
        assert len(state.trace) == 0

    def test_trace_entry_creation(self) -> None:
        from finance.cognition.state.models import TraceEntry

        entry = TraceEntry(
            node_name="planner", execution_order=1, result={"plan": ["a"]}, confidence=0.8
        )
        assert entry.node_name == "planner"
        assert entry.execution_order == 1

    def test_state_start_time_is_set(self) -> None:
        from datetime import datetime

        from finance.cognition.state.models import ReasoningState

        state = ReasoningState(query="test")
        assert isinstance(state.started_at, datetime)
        assert state.started_at.tzinfo is not None

    def test_state_increments_step(self) -> None:
        from finance.cognition.state.models import ReasoningState

        state = ReasoningState(query="test")
        state.record_step(node_name="first", result={"a": 1})
        assert state.step == 1
        assert len(state.trace) == 1
        assert state.trace[0].execution_order == 1

    def test_loop_control_defaults(self) -> None:
        from finance.cognition.state.models import ReasoningState

        state = ReasoningState(query="test")
        assert state.overall_confidence == 0.0
        assert state.iteration_count == 0
        assert state.max_iterations == 5
        assert state.loop_decision == "continue"
        assert state.summary == ""

    def test_state_serialization_with_loop_fields(self) -> None:
        from finance.cognition.state.models import ReasoningState

        state = ReasoningState(
            query="test", loop_decision="finalize", overall_confidence=0.85
        )
        state.record_step(node_name="planner", result={"plan": ["a"]})
        d = state.model_dump()
        restored = ReasoningState.model_validate(d)
        assert restored.loop_decision == "finalize"
        assert restored.overall_confidence == 0.85
        assert len(restored.trace) == 1

    def test_state_adds_assertions(self) -> None:
        from finance.cognition.state.models import ReasoningState
        from shared.models.assertions import Assertion, AssertionType

        state = ReasoningState(query="test")
        state.add_assertions(
            [
                Assertion(
                    id="a1", type=AssertionType.NUMERIC, text="test", confidence=0.5
                ),
            ]
        )
        assert len(state.assertions) == 1


class TestNodeProtocol:
    """Task 1.2 — NodeResult and CognitiveNode protocol."""

    def test_node_result_creation(self) -> None:
        from finance.cognition.state.node import NodeResult

        r = NodeResult(
            node_name="planner", state_updates={"plan": ["a"]}, confidence=0.8
        )
        assert r.success is True
        assert r.state_updates["plan"] == ["a"]

    def test_node_result_defaults(self) -> None:
        from finance.cognition.state.node import NodeResult

        r = NodeResult(node_name="test")
        assert r.success is True
        assert r.state_updates == {}
        assert r.new_assertions == []
        assert r.confidence == 0.0
        assert r.message == ""
        assert r.metadata == {}

    def test_cognitive_node_is_protocol(self) -> None:
        import inspect

        from finance.cognition.state.node import CognitiveNode

        assert inspect.isclass(CognitiveNode)

    def test_node_result_carries_assertions(self) -> None:
        from finance.cognition.state.node import NodeResult
        from shared.models.assertions import Assertion, AssertionType

        r = NodeResult(
            node_name="verifier",
            new_assertions=[
                Assertion(
                    id="v1", type=AssertionType.NUMERIC, text="Verified", confidence=0.9
                ),
            ],
        )
        assert len(r.new_assertions) == 1
        assert r.new_assertions[0].confidence == 0.9


class TestActionModel:
    """Slice 3 — Action and ActionPlan models."""

    def test_action_creation(self) -> None:
        from finance.cognition.state.action import Action, ActionStatus

        action = Action(objective="determine_revenue_variance")
        assert action.objective == "determine_revenue_variance"
        assert action.status == ActionStatus.PENDING
        assert action.id.startswith("act_")
        assert action.retry_count == 0

    def test_action_plan_creation(self) -> None:
        from finance.cognition.state.action import ActionPlan

        plan = ActionPlan()
        assert len(plan.actions) == 0
        assert plan.iteration == 0

    def test_action_plan_add_action(self) -> None:
        from finance.cognition.state.action import ActionPlan

        plan = ActionPlan()
        plan.add(objective="test_objective", inputs={"key": "value"})
        assert len(plan.actions) == 1
        assert plan.actions[0].objective == "test_objective"
        assert plan.actions[0].inputs == {"key": "value"}

    def test_action_plan_tracks_status(self) -> None:
        from finance.cognition.state.action import ActionPlan, ActionStatus

        plan = ActionPlan()
        a1 = plan.add(objective="task1")
        a2 = plan.add(objective="task2")
        a1.status = ActionStatus.SUCCESS
        a2.status = ActionStatus.PENDING
        assert len(plan.completed) == 1
        assert len(plan.pending) == 1

    def test_action_plan_history_preserved_on_replan(self) -> None:
        from finance.cognition.state.action import ActionPlan
        from finance.cognition.state.models import ReasoningState

        state = ReasoningState(query="test")
        plan1 = ActionPlan(iteration=0)
        plan1.add(objective="v1")
        state.action_plan = plan1
        state.plan_history.append(plan1.model_copy())
        plan2 = ActionPlan(iteration=1)
        plan2.add(objective="v2")
        state.action_plan = plan2
        assert len(state.plan_history) == 1
        assert state.plan_history[0].actions[0].objective == "v1"
        assert state.action_plan.actions[0].objective == "v2"
