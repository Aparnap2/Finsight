"""Planner cognitive node.

Decomposes the top-level goal into an ActionPlan — a sequence of actions
that guide downstream retrieval, executor dispatch, verification, and
reflection stages.
"""

from finance.cognition.state.action import ActionPlan
from finance.cognition.state.models import ReasoningState
from finance.cognition.state.node import NodeResult


class PlannerNode:
    """Decompose a financial reasoning goal into an ActionPlan."""

    def execute(self, state: ReasoningState) -> NodeResult:  # noqa: ARG002
        query = state.query.lower()
        actions: list[dict[str, str]] = []

        # Parse query for keywords to tailor the plan
        if "variance" in query:
            actions.append({"objective": "determine_revenue_variance"})
        if "kpi" in query or "performance" in query:
            actions.append({"objective": "compute_key_performance_indicators"})
        if "evidence" in query or "support" in query:
            actions.append({"objective": "collect_supporting_evidence"})

        if not actions:
            # Default plan when no keywords match
            actions = [
                {"objective": "determine_revenue_variance"},
                {"objective": "compute_key_performance_indicators"},
                {"objective": "collect_supporting_evidence"},
            ]

        plan = ActionPlan()
        for a in actions:
            plan.add(objective=a["objective"])

        return NodeResult(
            node_name="planner",
            success=True,
            state_updates={
                "action_plan": plan.model_dump(),
                "plan": [a["objective"] for a in actions],
                "current_step": 0,
            },
            confidence=0.5,
            message=f"Decomposed goal into {len(actions)} actions",
        )
