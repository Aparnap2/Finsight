"""Tests for the State Machine module.

Covers the StateMachine base class, transition validation,
guard conditions, the registry, and all 8 state machine
implementations.
"""

from __future__ import annotations

import pytest

from business.state_machines.models import (
    GuardCondition,
    StateMachine,
    StateMachineRegistry,
    TransitionError,
)
from business.state_machines.registry import (
    ACTION_ITEM_SM,
    AGENT_RUN_SM,
    COMMENTARY_SM,
    FISCAL_PERIOD_SM,
    JOB_SM,
    PIPELINE_RUN_SM,
    RECOMMENDATION_SM,
    STATE_MACHINE_REGISTRY,
    SUPPORT_LEVEL_LATTICE,
)


class TestStateMachineBase:
    """Tests for the base StateMachine model."""

    def test_create_simple_machine(self) -> None:
        """A simple state machine can be created with states and transitions."""
        sm = StateMachine(
            name="Simple",
            states={"a", "b", "c"},
            transitions={"a": ["b"], "b": ["c"]},
        )
        assert sm.name == "Simple"
        assert sm.states == {"a", "b", "c"}

    def test_initial_states(self) -> None:
        """States not reachable from any other state are initial."""
        sm = StateMachine(
            name="Simple",
            states={"a", "b", "c"},
            transitions={"a": ["b"], "b": ["c"]},
        )
        assert sm.initial_states == {"a"}

    def test_terminal_states(self) -> None:
        """States with no outgoing transitions are terminal."""
        sm = StateMachine(
            name="Simple",
            states={"a", "b", "c"},
            transitions={"a": ["b"], "b": ["c"]},
        )
        assert sm.terminal_states == {"c"}

    def test_is_legal_transition(self) -> None:
        """A defined transition is legal."""
        sm = StateMachine(
            name="Simple",
            states={"a", "b"},
            transitions={"a": ["b"]},
        )
        assert sm.is_legal("a", "b") is True

    def test_is_illegal_transition(self) -> None:
        """An undefined transition is illegal."""
        sm = StateMachine(
            name="Simple",
            states={"a", "b"},
            transitions={"a": ["b"]},
        )
        assert sm.is_legal("b", "a") is False

    def test_assert_legal_passes(self) -> None:
        """assert_legal does not raise for a legal transition."""
        sm = StateMachine(
            name="Simple",
            states={"a", "b"},
            transitions={"a": ["b"]},
        )
        sm.assert_legal("a", "b")  # should not raise

    def test_assert_legal_raises(self) -> None:
        """assert_legal raises TransitionError for illegal transition."""
        sm = StateMachine(
            name="Simple",
            states={"a", "b"},
            transitions={"a": ["b"]},
        )
        with pytest.raises(TransitionError):
            sm.assert_legal("b", "a")

    def test_transition_error_message(self) -> None:
        """TransitionError includes entity name and states."""
        sm = StateMachine(
            name="Simple",
            states={"a", "b"},
            transitions={"a": ["b"]},
        )
        try:
            sm.assert_legal("b", "a", entity="TestEntity")
        except TransitionError as exc:
            assert "TestEntity" in str(exc)
            assert "b" in str(exc)
            assert "a" in str(exc)

    def test_get_guards(self) -> None:
        """get_guards returns only guards that apply to the transition."""
        guard = GuardCondition(
            name="test_guard",
            description="Test guard condition",
            applies_to=[("a", "b")],
            condition_fn="True",
        )
        sm = StateMachine(
            name="Guarded",
            states={"a", "b"},
            transitions={"a": ["b"]},
            guard_conditions=[guard],
        )
        applicable = sm.get_guards("a", "b")
        not_applicable = sm.get_guards("b", "a")
        assert len(applicable) == 1
        assert applicable[0].name == "test_guard"
        assert len(not_applicable) == 0

    def test_self_transition(self) -> None:
        """Self-transitions are only legal if explicitly defined."""
        sm = StateMachine(
            name="NoSelf",
            states={"a", "b"},
            transitions={"a": ["b"]},
        )
        assert sm.is_legal("a", "a") is False


class TestStateMachineRegistry:
    """Tests for the StateMachineRegistry."""

    def test_register_and_lookup(self) -> None:
        """Machines can be registered and looked up by name."""
        registry = StateMachineRegistry()
        sm = StateMachine(
            name="TestSM",
            states={"x", "y"},
            transitions={"x": ["y"]},
        )
        registry.register(sm)
        assert registry.get("TestSM") is sm
        assert registry.get("NonExistent") is None

    def test_count(self) -> None:
        """Count returns the number of registered machines."""
        registry = StateMachineRegistry()
        assert registry.count == 0
        registry.register(StateMachine(name="SM1", states={"a"}, transitions={}))
        registry.register(StateMachine(name="SM2", states={"a"}, transitions={}))
        assert registry.count == 2

    def test_list_names(self) -> None:
        """list_names returns all registered machine names."""
        registry = StateMachineRegistry()
        registry.register(StateMachine(name="SM1", states={"a"}, transitions={}))
        registry.register(StateMachine(name="SM2", states={"a"}, transitions={}))
        assert sorted(registry.list_names()) == ["SM1", "SM2"]


class TestPipelineRunSM:
    """Tests for the PipelineRun state machine."""

    def test_legal_transitions(self) -> None:
        """All defined transitions are legal."""
        assert PIPELINE_RUN_SM.is_legal("pending", "running")
        assert PIPELINE_RUN_SM.is_legal("pending", "cancelled")
        assert PIPELINE_RUN_SM.is_legal("running", "success")
        assert PIPELINE_RUN_SM.is_legal("running", "failed")
        assert PIPELINE_RUN_SM.is_legal("failed", "retrying")
        assert PIPELINE_RUN_SM.is_legal("retrying", "running")
        assert PIPELINE_RUN_SM.is_legal("retrying", "failed")

    def test_illegal_transitions(self) -> None:
        """Transitions not in the map raise TransitionError."""
        with pytest.raises(TransitionError):
            PIPELINE_RUN_SM.assert_legal("pending", "success")
        with pytest.raises(TransitionError):
            PIPELINE_RUN_SM.assert_legal("success", "running")
        with pytest.raises(TransitionError):
            PIPELINE_RUN_SM.assert_legal("cancelled", "pending")

    def test_initial_state(self) -> None:
        """PipelineRun starts in pending."""
        assert "pending" in PIPELINE_RUN_SM.initial_states

    def test_terminal_states(self) -> None:
        """Success and cancelled are terminal states."""
        assert "success" in PIPELINE_RUN_SM.terminal_states
        assert "cancelled" in PIPELINE_RUN_SM.terminal_states
        assert "running" not in PIPELINE_RUN_SM.terminal_states

    def test_business_context(self) -> None:
        """PipelineRun has a business context description."""
        assert "pipeline lifecycle" in PIPELINE_RUN_SM.business_context.lower()


class TestAgentRunSM:
    """Tests for the AgentRun state machine."""

    def test_legal_transitions(self) -> None:
        """All defined AgentRun transitions are legal."""
        assert AGENT_RUN_SM.is_legal("pending", "running")
        assert AGENT_RUN_SM.is_legal("running", "success")
        assert AGENT_RUN_SM.is_legal("running", "failed")
        assert AGENT_RUN_SM.is_legal("failed", "retrying")
        assert AGENT_RUN_SM.is_legal("retrying", "running")

    def test_illegal_skip_to_success(self) -> None:
        """AgentRun cannot skip from pending to success."""
        with pytest.raises(TransitionError):
            AGENT_RUN_SM.assert_legal("pending", "success")


class TestJobSM:
    """Tests for the Job state machine."""

    def test_legal_transitions(self) -> None:
        """All defined Job transitions are legal."""
        assert JOB_SM.is_legal("queued", "running")
        assert JOB_SM.is_legal("running", "validating")
        assert JOB_SM.is_legal("validating", "executing")
        assert JOB_SM.is_legal("executing", "exporting")
        assert JOB_SM.is_legal("exporting", "success")
        assert JOB_SM.is_legal("failed", "retrying")
        assert JOB_SM.is_legal("retrying", "running")

    def test_illegal_skip_exporting(self) -> None:
        """Job cannot skip from executing to success."""
        with pytest.raises(TransitionError):
            JOB_SM.assert_legal("executing", "success")

    def test_initial_state(self) -> None:
        """Job starts in queued."""
        assert "queued" in JOB_SM.initial_states

    def test_terminal_states(self) -> None:
        """Success and cancelled are terminal for Job."""
        assert "success" in JOB_SM.terminal_states
        assert "cancelled" in JOB_SM.terminal_states


class TestActionItemSM:
    """Tests for the ActionItem state machine."""

    def test_legal_transitions(self) -> None:
        """All defined ActionItem transitions are legal."""
        assert ACTION_ITEM_SM.is_legal("proposed", "approved")
        assert ACTION_ITEM_SM.is_legal("proposed", "blocked")
        assert ACTION_ITEM_SM.is_legal("proposed", "rejected")
        assert ACTION_ITEM_SM.is_legal("approved", "in_progress")
        assert ACTION_ITEM_SM.is_legal("in_progress", "completed")
        assert ACTION_ITEM_SM.is_legal("blocked", "proposed")

    def test_illegal_skip_to_completed(self) -> None:
        """ActionItem cannot go directly from proposed to completed."""
        with pytest.raises(TransitionError):
            ACTION_ITEM_SM.assert_legal("proposed", "completed")

    def test_illegal_reversal(self) -> None:
        """Completed actions cannot transition back."""
        with pytest.raises(TransitionError):
            ACTION_ITEM_SM.assert_legal("completed", "in_progress")

    def test_no_initial_state(self) -> None:
        """ActionItem has no pure initial state because proposed
        is reachable from blocked (unblocked action)."""
        assert ACTION_ITEM_SM.initial_states == set()

    def test_guard_exists(self) -> None:
        """ActionItemSM has guard conditions."""
        guards = ACTION_ITEM_SM.guard_conditions
        assert len(guards) >= 3


class TestRecommendationSM:
    """Tests for the Recommendation state machine."""

    def test_legal_transitions(self) -> None:
        """All defined Recommendation transitions are legal."""
        assert RECOMMENDATION_SM.is_legal("proposed", "reviewed")
        assert RECOMMENDATION_SM.is_legal("reviewed", "approved")
        assert RECOMMENDATION_SM.is_legal("approved", "implemented")
        assert RECOMMENDATION_SM.is_legal("proposed", "rejected")
        assert RECOMMENDATION_SM.is_legal("reviewed", "rejected")

    def test_illegal_skip_review(self) -> None:
        """Recommendation cannot go from proposed to approved directly."""
        with pytest.raises(TransitionError):
            RECOMMENDATION_SM.assert_legal("proposed", "approved")

    def test_terminal_states(self) -> None:
        """Implemented and rejected are terminal."""
        assert "implemented" in RECOMMENDATION_SM.terminal_states
        assert "rejected" in RECOMMENDATION_SM.terminal_states


class TestCommentarySM:
    """Tests for the Commentary state machine."""

    def test_legal_transitions(self) -> None:
        """All defined Commentary transitions are legal."""
        assert COMMENTARY_SM.is_legal("draft", "reviewing")
        assert COMMENTARY_SM.is_legal("draft", "draft")
        assert COMMENTARY_SM.is_legal("reviewing", "approved")
        assert COMMENTARY_SM.is_legal("reviewing", "rejected")
        assert COMMENTARY_SM.is_legal("approved", "published")
        assert COMMENTARY_SM.is_legal("approved", "draft")

    def test_illegal_publish_from_draft(self) -> None:
        """Draft cannot be published directly without review."""
        with pytest.raises(TransitionError):
            COMMENTARY_SM.assert_legal("draft", "published")

    def test_no_initial_state(self) -> None:
        """Commentary has no pure initial state because draft
        is reachable from approved (revision requested) and from itself."""
        assert COMMENTARY_SM.initial_states == set()


class TestFiscalPeriodSM:
    """Tests for the FiscalPeriod state machine."""

    def test_legal_transitions(self) -> None:
        """All defined FiscalPeriod transitions are legal."""
        assert FISCAL_PERIOD_SM.is_legal("open", "closing")
        assert FISCAL_PERIOD_SM.is_legal("closing", "closed")
        assert FISCAL_PERIOD_SM.is_legal("closed", "reopened")
        assert FISCAL_PERIOD_SM.is_legal("closed", "archived")
        assert FISCAL_PERIOD_SM.is_legal("reopened", "open")
        assert FISCAL_PERIOD_SM.is_legal("reopened", "archived")

    def test_illegal_skip_to_archived(self) -> None:
        """Period cannot go from open to archived directly."""
        with pytest.raises(TransitionError):
            FISCAL_PERIOD_SM.assert_legal("open", "archived")

    def test_business_context(self) -> None:
        """FiscalPeriod has a meaningful business context."""
        assert "fiscal period lifecycle" in FISCAL_PERIOD_SM.business_context.lower()


class TestSupportLevelLattice:
    """Tests for the SupportLevel lattice."""

    def test_downward_transitions_legal(self) -> None:
        """Downward moves in the confidence lattice are legal."""
        assert SUPPORT_LEVEL_LATTICE.is_legal("verified", "probable")
        assert SUPPORT_LEVEL_LATTICE.is_legal("verified", "weak")
        assert SUPPORT_LEVEL_LATTICE.is_legal("verified", "insufficient")
        assert SUPPORT_LEVEL_LATTICE.is_legal("probable", "weak")
        assert SUPPORT_LEVEL_LATTICE.is_legal("probable", "insufficient")
        assert SUPPORT_LEVEL_LATTICE.is_legal("weak", "insufficient")

    def test_upward_transitions_illegal(self) -> None:
        """Upward moves in the confidence lattice are illegal."""
        assert SUPPORT_LEVEL_LATTICE.is_legal("probable", "verified") is False
        assert SUPPORT_LEVEL_LATTICE.is_legal("weak", "verified") is False
        assert SUPPORT_LEVEL_LATTICE.is_legal("weak", "probable") is False
        assert SUPPORT_LEVEL_LATTICE.is_legal("insufficient", "weak") is False
        assert SUPPORT_LEVEL_LATTICE.is_legal("insufficient", "probable") is False
        assert SUPPORT_LEVEL_LATTICE.is_legal("insufficient", "verified") is False

    def test_no_self_transition_defined(self) -> None:
        """Self-transitions are not defined for the lattice."""
        assert SUPPORT_LEVEL_LATTICE.is_legal("verified", "verified") is False

    def test_initial_state(self) -> None:
        """Verified is the highest confidence and is initial."""
        assert "verified" in SUPPORT_LEVEL_LATTICE.initial_states

    def test_insufficient_is_terminal(self) -> None:
        """Insufficient has no outgoing transitions (lattice bottom)."""
        assert "insufficient" in SUPPORT_LEVEL_LATTICE.terminal_states

    def test_guard_conditions_present(self) -> None:
        """Both guard conditions exist on the lattice."""
        names = {g.name for g in SUPPORT_LEVEL_LATTICE.guard_conditions}
        assert "lattice_downgrade_only" in names
        assert "no_upward_transitions" in names


class TestFullRegistry:
    """Tests for the global STATE_MACHINE_REGISTRY singleton."""

    def test_registry_has_all_8_machines(self) -> None:
        """The global registry contains all 8 state machines."""
        assert STATE_MACHINE_REGISTRY.count == 8

    def test_all_machines_present(self) -> None:
        """Each expected machine is in the registry."""
        names = STATE_MACHINE_REGISTRY.list_names()
        assert "PipelineRun" in names
        assert "AgentRun" in names
        assert "Job" in names
        assert "ActionItem" in names
        assert "Recommendation" in names
        assert "Commentary" in names
        assert "FiscalPeriod" in names
        assert "SupportLevel" in names

    def test_each_machine_has_states(self) -> None:
        """Every registered machine has at least 3 states."""
        for name in STATE_MACHINE_REGISTRY.list_names():
            machine = STATE_MACHINE_REGISTRY.get(name)
            assert machine is not None
            assert len(machine.states) >= 3, f"{name} has fewer than 3 states"

    def test_no_machine_has_empty_transitions(self) -> None:
        """Every registered machine defines at least one transition."""
        for name in STATE_MACHINE_REGISTRY.list_names():
            machine = STATE_MACHINE_REGISTRY.get(name)
            assert machine is not None
            assert len(machine.transitions) >= 1, f"{name} has no transitions"
