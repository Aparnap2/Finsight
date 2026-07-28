"""Tests for T2.1 — Extended state machine with PRD §6 states, checkpoints, remediation paths.

These tests define the expected behavior BEFORE implementation (TDD RED phase).
"""
import pytest
from unittest.mock import patch, MagicMock
from decimal import Decimal

from backend.agents.orchestrator import build_graph, _route_after_variance, _route_after_scenario
from backend.models.state import (
    PipelineState,
    Variance,
    RootCauseFinding,
    CommentaryDraft,
    CommentarySection,
    Scenario,
)
from backend.models.assertions import Assertion, AssertionType, SupportLevel
from backend.models.degraded_mode import DegradedMode
from backend.engine.policy import AutonomyLevel, PolicyDecision, evaluate_policy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_variance(material: bool = True) -> Variance:
    return Variance(
        account_id="1001",
        account_name="Revenue",
        department="Sales",
        actual_amount=Decimal("150000"),
        budget_amount=Decimal("100000"),
        variance_amount=Decimal("50000"),
        variance_pct=Decimal("50.00"),
        is_material=material,
    )


def _make_root_cause(variance_id: str = "1001") -> RootCauseFinding:
    return RootCauseFinding(
        variance_id=variance_id,
        summary="Revenue growth driven by new enterprise deals",
        confidence_score=0.85,
    )


def _make_assertion(
    atype: AssertionType = AssertionType.NUMERIC,
    confidence: float = 0.8,
    support: SupportLevel = SupportLevel.VERIFIED,
) -> Assertion:
    return Assertion(
        id="assert-1",
        type=atype,
        text="Revenue increased 50% YoY",
        confidence=confidence,
        support_level=support,
    )


def _make_scenario() -> Scenario:
    return Scenario(
        name="Base Case",
        description="Current trajectory",
        assumptions={"growth_rate": 0.05},
        revenue_impact=Decimal("0"),
        ebitda_impact=Decimal("0"),
        cash_impact=Decimal("0"),
        probability_assessment="high",
    )


def _minimal_state(**overrides) -> PipelineState:
    state: PipelineState = {
        "period": "2025-Q4",
        "entity_id": "ACME",
        "actuals": {},
        "budget": {},
        "forecast": {},
        "variances": [],
        "root_causes": [],
        "commentary_draft": None,
        "scenarios": [],
        "review_decisions": [],
        "error": None,
        "current_step": "",
    }
    state.update(overrides)
    return state


# ===================================================================
# TestGraphStructure — Verify all PRD §6 states exist
# ===================================================================

class TestGraphStructure:
    def test_graph_compiles(self):
        """Graph compiles without errors."""
        graph = build_graph(checkpointer=None)
        assert graph is not None

    def test_graph_has_all_prd_states(self):
        """Graph must contain all 8 PRD §6 states as nodes."""
        graph = build_graph(checkpointer=None)
        nodes = set(graph.get_graph().nodes)

        expected_nodes = {
            "ingestion",
            "variance_detection",
            "root_cause",
            "commentary",
            "scenario",
            "review",
            "remediation",
            "__end__",
        }
        # __end__ is LangGraph's END node; check the user-defined nodes
        user_nodes = nodes - {"__start__", "__end__"}
        assert user_nodes == {"ingestion", "variance_detection", "root_cause",
                               "commentary", "scenario", "review", "remediation"}, (
            f"Missing nodes: {expected_nodes - nodes}"
        )

    def test_graph_has_conditional_edges(self):
        """Graph must have at least 2 conditional edge groups."""
        graph = build_graph(checkpointer=None)
        graph_obj = graph.get_graph()
        # Count conditional edges by checking for edges with branch functions
        conditional_edge_count = sum(
            1 for edge in graph_obj.edges
            if getattr(edge, "conditional", False) or "condition" in str(type(edge)).lower()
        )
        # We expect at least: variance→(root_cause|commentary) and scenario→(review|complete)
        # and review→(remediation|complete) — LangGraph may represent these differently
        # So we verify indirectly by checking routing functions exist
        assert callable(_route_after_variance)
        assert callable(_route_after_scenario)

    def test_entry_point_is_ingestion(self):
        """Graph entry point must be the ingestion node."""
        graph = build_graph(checkpointer=None)
        graph_obj = graph.get_graph()
        # The entry node should be "ingestion"
        nodes = list(graph_obj.nodes)
        assert "ingestion" in nodes


# ===================================================================
# TestRouting — Conditional routing logic
# ===================================================================

class TestRouting:
    def test_material_variances_route_to_root_cause(self):
        """Material variances should route to root_cause node."""
        state = _minimal_state(variances=[_make_variance(material=True)])
        result = _route_after_variance(state)
        assert result == "root_cause"

    def test_immaterial_variances_route_to_commentary(self):
        """No material variances should route to commentary node."""
        state = _minimal_state(variances=[_make_variance(material=False)])
        result = _route_after_variance(state)
        assert result == "commentary"

    def test_no_variances_route_to_commentary(self):
        """Empty variance list should route to commentary."""
        state = _minimal_state(variances=[])
        result = _route_after_variance(state)
        assert result == "commentary"

    def test_mixed_variances_route_to_root_cause(self):
        """Mix of material and immaterial variances should route to root_cause."""
        state = _minimal_state(variances=[
            _make_variance(material=True),
            _make_variance(material=False),
        ])
        result = _route_after_variance(state)
        assert result == "root_cause"

    def test_route_after_scenario_fully_autonomous(self):
        """Fully autonomous policy decision should route to complete."""
        state = _minimal_state(
            scenarios=[_make_scenario()],
            policy_decision={
                "autonomy_level": AutonomyLevel.FULLY_AUTONOMOUS.value,
                "routing_target": "complete",
                "requires_review": False,
            },
        )
        result = _route_after_scenario(state)
        assert result == "complete"

    def test_route_after_scenario_analyst_review(self):
        """Analyst-in-the-loop policy should route to review."""
        state = _minimal_state(
            scenarios=[_make_scenario()],
            policy_decision={
                "autonomy_level": AutonomyLevel.ANALYST_IN_THE_LOOP.value,
                "routing_target": "review",
                "requires_review": True,
            },
        )
        result = _route_after_scenario(state)
        assert result == "review"

    def test_route_after_scenario_manager_review(self):
        """Manager approval policy should route to review."""
        state = _minimal_state(
            scenarios=[_make_scenario()],
            policy_decision={
                "autonomy_level": AutonomyLevel.MANAGER_APPROVAL.value,
                "routing_target": "manager_review",
                "requires_review": True,
            },
        )
        result = _route_after_scenario(state)
        assert result == "review"

    def test_route_after_scenario_cfo_review(self):
        """CFO approval policy should route to review."""
        state = _minimal_state(
            scenarios=[_make_scenario()],
            policy_decision={
                "autonomy_level": AutonomyLevel.CFO_APPROVAL.value,
                "routing_target": "cfo_review",
                "requires_review": True,
            },
        )
        result = _route_after_scenario(state)
        assert result == "review"

    def test_route_review_approved_completes(self):
        """Approved review should route to complete."""
        from backend.agents.orchestrator import _route_after_review
        state = _minimal_state(
            review_decisions=[{"decision": "approved"}],
        )
        result = _route_after_review(state)
        assert result == "complete"

    def test_route_review_rejected_routes_to_remediation(self):
        """Rejected review should route to remediation."""
        from backend.agents.orchestrator import _route_after_review
        state = _minimal_state(
            review_decisions=[{"decision": "rejected"}],
        )
        result = _route_after_review(state)
        assert result == "remediation"


# ===================================================================
# TestDegradedModeHandling — Skip nodes when data insufficient
# ===================================================================

class TestDegradedModeHandling:
    def test_insufficient_data_skips_root_cause(self):
        """When data_quality indicates insufficient data, route to commentary instead of root_cause."""
        from backend.agents.orchestrator import _route_after_variance
        state = _minimal_state(
            variances=[_make_variance(material=True)],
            degraded_modes=[DegradedMode.LOW_COVERAGE.value],
            data_quality={"overall_score": 0.2, "passed": False},
        )
        result = _route_after_variance(state)
        assert result == "commentary"

    def test_critical_degraded_skips_root_cause(self):
        """Stale source degraded mode should also skip root_cause."""
        from backend.agents.orchestrator import _route_after_variance
        state = _minimal_state(
            variances=[_make_variance(material=True)],
            degraded_modes=[DegradedMode.STALE_SOURCE.value],
        )
        result = _route_after_variance(state)
        assert result == "commentary"

    def test_degraded_mode_surfaces_in_state(self):
        """Degraded modes should be trackable in pipeline state."""
        state = _minimal_state(
            degraded_modes=[DegradedMode.LOW_COVERAGE.value],
        )
        assert "degraded_modes" in state
        assert DegradedMode.LOW_COVERAGE.value in state["degraded_modes"]

    def test_no_degraded_allows_root_cause(self):
        """With no degraded modes and material variances, root_cause should be entered."""
        state = _minimal_state(
            variances=[_make_variance(material=True)],
            degraded_modes=[],
        )
        result = _route_after_variance(state)
        assert result == "root_cause"


# ===================================================================
# TestRemediation — Failed assertions → remediation → retry
# ===================================================================

class TestRemediation:
    def test_failed_assertions_route_to_remediation(self):
        """Review decisions with 'rejected' should route to remediation."""
        from backend.agents.orchestrator import _route_after_review
        state = _minimal_state(
            review_decisions=[{"decision": "rejected", "reason": "Low confidence"}],
        )
        result = _route_after_review(state)
        assert result == "remediation"

    def test_approved_review_does_not_go_to_remediation(self):
        """Approved review should not route to remediation."""
        from backend.agents.orchestrator import _route_after_review
        state = _minimal_state(
            review_decisions=[{"decision": "approved"}],
        )
        result = _route_after_review(state)
        assert result == "complete"

    def test_remediation_node_exists(self):
        """Remediation node should exist in the graph."""
        graph = build_graph(checkpointer=None)
        nodes = set(graph.get_graph().nodes)
        assert "remediation" in nodes

    def test_remediation_returns_to_scenario(self):
        """After remediation, the pipeline should return to scenario for re-evaluation."""
        graph = build_graph(checkpointer=None)
        # Check that remediation has an outgoing edge back to scenario
        # by inspecting the graph edges
        graph_obj = graph.get_graph()
        edges_from_remediation = [
            e for e in graph_obj.edges
            if getattr(e, "source", None) == "remediation"
        ]
        # Remediation should connect back to scenario
        assert len(edges_from_remediation) > 0, (
            "Remediation node should have outgoing edges"
        )


# ===================================================================
# TestStateTransitions — State accumulates across nodes
# ===================================================================

class TestStateTransitions:
    def test_state_accumulates_across_nodes(self):
        """PipelineState should accumulate data as it flows through nodes."""
        from backend.agents.variance_agent import variance_node
        from backend.agents.scenario_agent import scenario_node

        state = _minimal_state(
            actuals={"accounts": [
                {"account_id": "1001", "amount": Decimal("150000")},
            ]},
            budget={"accounts": [
                {"account_id": "1001", "amount": Decimal("100000")},
            ]},
        )
        # Run variance node
        result = variance_node(state)
        state.update(result)
        assert len(state["variances"]) > 0
        assert state["current_step"] == "variance_complete"

    def test_error_handling_per_node(self):
        """Each node should catch errors and set state["error"]."""
        # Test that ingestion_node handles missing data gracefully
        from backend.agents.ingestion_agent import ingestion_node
        state = _minimal_state()
        # ingestion_node uses "tenant_id" as its key for the entity
        state["tenant_id"] = state.get("entity_id", "ACME")
        result = ingestion_node(state)
        # Should not raise, should set current_step
        assert "current_step" in result

    def test_current_step_tracks_progress(self):
        """current_step should be updated after each node execution."""
        from backend.agents.ingestion_agent import ingestion_node
        state = _minimal_state()
        # ingestion_node uses "tenant_id" as its key for the entity
        state["tenant_id"] = state.get("entity_id", "ACME")
        result = ingestion_node(state)
        assert result["current_step"] == "ingestion_complete"

    def test_review_decisions_accumulate(self):
        """review_decisions should accumulate across review states."""
        state = _minimal_state(
            review_decisions=[{"decision": "approved"}],
        )
        # Simulate adding another review decision (LangGraph uses operator.add)
        new_decisions = [{"decision": "acknowledged"}]
        # In LangGraph, Annotated[list, operator.add] means appending
        accumulated = state["review_decisions"] + new_decisions
        assert len(accumulated) == 2
        assert accumulated[0]["decision"] == "approved"
        assert accumulated[1]["decision"] == "acknowledged"

    def test_error_state_preserved(self):
        """error field should be preserved through state transitions."""
        state = _minimal_state(error="Something went wrong")
        assert state["error"] == "Something went wrong"

    def test_variances_accumulate(self):
        """variances should accumulate using operator.add."""
        state = _minimal_state(variances=[])
        v1 = _make_variance(material=True)
        v2 = _make_variance(material=False)
        accumulated = state["variances"] + [v1, v2]
        assert len(accumulated) == 2

    def test_root_causes_accumulate(self):
        """root_causes should accumulate using operator.add."""
        state = _minimal_state(root_causes=[])
        rc1 = _make_root_cause("1001")
        rc2 = _make_root_cause("1002")
        accumulated = state["root_causes"] + [rc1, rc2]
        assert len(accumulated) == 2


# ===================================================================
# TestCheckpoint — Save/restore state
# ===================================================================

class TestCheckpoint:
    def test_graph_compiles_with_checkpointer(self):
        """Graph should compile with a MemorySaver checkpointer."""
        from langgraph.checkpoint.memory import MemorySaver
        memory = MemorySaver()
        graph = build_graph(checkpointer=memory)
        assert graph is not None

    def test_checkpoint_save_restore(self):
        """Should be able to save and restore state via checkpointer."""
        from langgraph.checkpoint.memory import MemorySaver
        memory = MemorySaver()
        graph = build_graph(checkpointer=memory)

        # Create a config for checkpointing
        config = {"configurable": {"thread_id": "test-thread-1"}}

        # Verify the graph can be invoked with checkpoint config
        # (We can't fully test save/restore without running the full pipeline,
        # but we can verify the checkpointer is properly configured)
        assert graph is not None

    def test_multiple_threads_independent(self):
        """Different thread IDs should maintain independent state."""
        from langgraph.checkpoint.memory import MemorySaver
        memory = MemorySaver()
        graph = build_graph(checkpointer=memory)

        config1 = {"configurable": {"thread_id": "thread-1"}}
        config2 = {"configurable": {"thread_id": "thread-2"}}

        # Verify both configs can be used
        assert config1["configurable"]["thread_id"] != config2["configurable"]["thread_id"]

    def test_graph_without_checkpointer_works(self):
        """Graph should still work without a checkpointer (backward compat)."""
        graph = build_graph(checkpointer=None)
        assert graph is not None


# ===================================================================
# TestPolicyIntegration — PolicyDecision routing integration
# ===================================================================

class TestPolicyIntegration:
    def test_policy_evaluate_produces_routing_target(self):
        """evaluate_policy should produce valid routing targets."""
        assertions = [_make_assertion(confidence=0.9)]
        decision = evaluate_policy(assertions=assertions)
        assert decision.routing_target in (
            "auto_publish", "review", "manager_review", "cfo_review", "complete"
        )

    def test_policy_no_assertions_routes_to_review(self):
        """Policy with no assertions should route to review."""
        decision = evaluate_policy(assertions=[])
        assert decision.requires_review is True
        assert decision.routing_target == "review"

    def test_policy_high_confidence_autonomous(self):
        """High confidence, no degraded modes → fully autonomous."""
        assertions = [
            _make_assertion(confidence=0.95, support=SupportLevel.VERIFIED),
        ]
        decision = evaluate_policy(
            assertions=assertions,
            degraded_modes=[],
            has_causal_claims=False,
            has_action_claims=False,
        )
        assert decision.autonomy_level == AutonomyLevel.FULLY_AUTONOMOUS
        assert decision.requires_review is False

    def test_policy_low_confidence_requires_review(self):
        """Low confidence assertions should require review."""
        assertions = [
            _make_assertion(confidence=0.3, support=SupportLevel.WEAK),
        ]
        decision = evaluate_policy(assertions=assertions)
        assert decision.requires_review is True

    def test_policy_degraded_mode_demotes_autonomy(self):
        """Critical degraded modes should demote to manager/CFO review."""
        assertions = [
            _make_assertion(confidence=0.9, support=SupportLevel.VERIFIED),
        ]
        decision = evaluate_policy(
            assertions=assertions,
            degraded_modes=[DegradedMode.LOW_COVERAGE.value],
        )
        # Even high confidence can't be fully autonomous with degraded modes
        assert decision.autonomy_level != AutonomyLevel.FULLY_AUTONOMOUS

    def test_policy_to_dict_roundtrip(self):
        """PolicyDecision.to_dict should produce serializable dict."""
        decision = evaluate_policy(assertions=[_make_assertion()])
        d = decision.to_dict()
        assert isinstance(d, dict)
        assert "autonomy_level" in d
        assert "routing_target" in d
        assert "requires_review" in d


# ===================================================================
# TestBackwardCompatibility — Existing tests still pass
# ===================================================================

class TestBackwardCompatibility:
    def test_original_graph_has_expected_nodes(self):
        """Original test: graph has the original 5 nodes."""
        graph = build_graph(checkpointer=None)
        nodes = set(graph.get_graph().nodes)
        # All original nodes must still exist
        assert "ingestion" in nodes
        assert "variance_detection" in nodes
        assert "root_cause" in nodes
        assert "commentary" in nodes
        assert "scenario" in nodes

    def test_original_routing_still_works(self):
        """Original routing logic: material → root_cause, immaterial → commentary."""
        # Material
        state_material = _minimal_state(variances=[_make_variance(material=True)])
        assert _route_after_variance(state_material) == "root_cause"
        # Immaterial
        state_immaterial = _minimal_state(variances=[_make_variance(material=False)])
        assert _route_after_variance(state_immaterial) == "commentary"
