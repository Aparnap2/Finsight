"""Orchestrator — LangGraph pipeline with full PRD §6 states.

State machine:
  ingestion → variance_detection → root_cause (if material) → commentary → scenario
  → review (if HITL) → complete
  ↓ commentary (immaterial)   ↓ skip   ↓ remediation → scenario (retry)

Added states:
  - review: HITL review based on PolicyDecision
  - remediation: corrective action when review fails

Added routing:
  - _route_after_variance: material → root_cause, immaterial/commentary, degraded → commentary
  - _route_after_scenario: HITL required → review, autonomous → complete
  - _route_after_review: approved → complete, rejected → remediation
"""

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph

from shared.models.degraded_mode import DegradedMode
from shared.models.state import PipelineState

# ---------------------------------------------------------------------------
# Routing functions
# ---------------------------------------------------------------------------

CRITICAL_DEGRADED_MODES = {
    DegradedMode.LOW_COVERAGE.value,
    DegradedMode.STALE_SOURCE.value,
    DegradedMode.INSUFFICIENT_CAUSAL_EVIDENCE.value,
}


def _route_after_variance(state: PipelineState) -> str:
    """Route after variance detection.

    Returns:
        "root_cause" — if material variances exist and data quality is sufficient
        "commentary" — if no material variances OR if degraded modes are critical
    """
    # Check for critical degraded modes — skip root cause if data is insufficient
    degraded_modes: list[str] = state.get("degraded_modes", [])
    if any(dm in CRITICAL_DEGRADED_MODES for dm in degraded_modes):
        return "commentary"

    material_variances = [v for v in state.get("variances", []) if v.is_material]
    if not material_variances:
        return "commentary"
    return "root_cause"


def _route_after_scenario(state: PipelineState) -> str:
    """Route after scenario modeling based on policy decision.

    Returns:
        "review" — if HITL review is required (any non-fully-autonomous level)
        "complete" — if fully autonomous
    """
    policy_decision = state.get("policy_decision")
    if policy_decision and policy_decision.get("requires_review", False):
        return "review"
    return "complete"


def _route_after_review(state: PipelineState) -> str:
    """Route after HITL review.

    Returns:
        "complete" — if review approved
        "remediation" — if review rejected
    """
    review_decisions = state.get("review_decisions", [])
    if not review_decisions:
        return "complete"

    last_decision = review_decisions[-1]
    if last_decision.get("decision") == "rejected":
        return "remediation"
    return "complete"


# ---------------------------------------------------------------------------
# Review and remediation nodes
# ---------------------------------------------------------------------------

def review_node(state: PipelineState) -> dict[str, Any]:
    """HITL review node — records the review decision.

    In production, this would integrate with a human review system.
    For now, it sets a default 'pending' state if no decision exists.
    """
    review_decisions = state.get("review_decisions", [])
    if not review_decisions:
        # No decision yet — mark as pending (in real system, this would wait)
        return {
            "review_decisions": [{"decision": "pending", "reviewer": "system"}],
            "current_step": "review_pending",
        }
    return {"current_step": "review_complete"}


def remediation_node(state: PipelineState) -> dict[str, Any]:
    """Remediation node — applies corrective actions for rejected reviews.

    In production, this would:
    1. Analyze rejection reasons
    2. Apply corrective actions (e.g., re-run with adjusted parameters)
    3. Log remediation actions

    For now, it logs the remediation attempt and clears the error.
    """
    review_decisions = state.get("review_decisions", [])
    last_rejection = None
    for d in reversed(review_decisions):
        if d.get("decision") == "rejected":
            last_rejection = d
            break

    remediation_log = {
        "action": "remediation_applied",
        "reason": last_rejection.get("reason", "Unknown") if last_rejection else "Unknown",
        "step": state.get("current_step", "unknown"),
    }

    return {
        "review_decisions": [remediation_log],
        "current_step": "remediation_complete",
        "error": None,  # Clear any prior error after remediation
    }


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_graph(
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph[PipelineState, Any]:
    """Build the full PRD §6 state graph with checkpoint support.

    States: ingestion → variance_detection → root_cause → commentary → scenario
    → review → remediation → complete
    """
    from langgraph.graph import END, StateGraph

    from agents.commentary.commentary_agent import commentary_node
    from agents.driver.root_cause_agent import root_cause_node
    from agents.scenario import scenario_node
    from agents.variance.variance_agent import variance_node
    from finance.ingestion.ingestion_agent import ingestion_node

    builder = StateGraph(PipelineState)

    # --- Nodes ---
    builder.add_node("ingestion", ingestion_node)
    builder.add_node("variance_detection", variance_node)
    builder.add_node("root_cause", root_cause_node)
    builder.add_node("commentary", commentary_node)
    builder.add_node("scenario", scenario_node)
    builder.add_node("review", review_node)
    builder.add_node("remediation", remediation_node)

    # --- Entry ---
    builder.set_entry_point("ingestion")

    # --- Edges ---
    builder.add_edge("ingestion", "variance_detection")

    # Variance → root_cause or commentary (conditional: material + data quality)
    builder.add_conditional_edges(
        "variance_detection",
        _route_after_variance,
        {"root_cause": "root_cause", "commentary": "commentary"},
    )

    # Root cause always flows to commentary
    builder.add_edge("root_cause", "commentary")

    # Commentary always flows to scenario
    builder.add_edge("commentary", "scenario")

    # Scenario → review or complete (conditional: HITL policy)
    builder.add_conditional_edges(
        "scenario",
        _route_after_scenario,
        {"review": "review", "complete": END},
    )

    # Review → complete or remediation (conditional: approval result)
    builder.add_conditional_edges(
        "review",
        _route_after_review,
        {"complete": END, "remediation": "remediation"},
    )

    # Remediation → scenario (retry loop)
    builder.add_edge("remediation", "scenario")

    # --- Compile ---
    if checkpointer:
        return builder.compile(checkpointer=checkpointer)
    return builder.compile()
