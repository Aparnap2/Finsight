from __future__ import annotations

from typing import Any

from finance.cognition.state.models import ReasoningState
from finance.cognition.state.node import NodeResult
from shared.models.assertions import SupportLevel


class ReflectionNode:
    """Analyse pipeline state to decide whether to finalise, revise, or continue.

    Inspects:
    - overall confidence
    - validation failures (from validation_report in context)
    - assertions with missing evidence or contradictions
    - unsupported assertions (WEAK or INSUFFICIENT support level)
    - iteration count vs max iterations
    - action verification results
    - action plan completeness (e.g. missing KPIs)
    """

    CONFIDENCE_THRESHOLD = 0.7

    def execute(self, state: ReasoningState) -> NodeResult:
        ctx = state.context
        overall = ctx.get("overall_confidence", state.overall_confidence)
        valid_report = ctx.get("validation_report", {})

        gaps: list[str] = []

        # ── Check validation failures ─────────────────────────────────
        if isinstance(valid_report, dict):
            failed = valid_report.get("failed_count", 0)
            if failed > 0:
                gaps.append(f"{failed} validation check(s) failed")

        # ── Check unsupported assertions ──────────────────────────────
        unsupported = [
            a
            for a in state.assertions
            if a.support_level in (SupportLevel.WEAK, SupportLevel.INSUFFICIENT)
        ]
        if unsupported:
            gaps.append(f"{len(unsupported)} unsupported assertion(s)")

        # ── Check missing evidence ────────────────────────────────────
        missing_evidence = [a for a in state.assertions if a.missing_evidence]
        if missing_evidence:
            gaps.append(
                f"{len(missing_evidence)} assertion(s) with missing evidence"
            )

        # ── Check contradictions ──────────────────────────────────────
        contradicted = [a for a in state.assertions if a.contradictions]
        if contradicted:
            gaps.append(
                f"{len(contradicted)} assertion(s) have contradictions"
            )

        # ── Check evidence items on context ───────────────────────────
        evidence_items = ctx.get("evidence_items", [])
        evidence = ctx.get("evidence", [])
        if not evidence_items and not evidence:
            gaps.append("No evidence items collected")

        # ── Check action verification results ─────────────────────────
        action_verifications: list[dict[str, Any]] = ctx.get(
            "action_verifications", []
        )
        for av in action_verifications:
            if not av.get("passed", True):
                gaps.append(
                    f"Action '{av.get('objective', 'unknown')}' "
                    f"failed verification"
                )

        # ── Check action plan for missing KPI coverage ────────────────
        if state.action_plan is not None:
            from finance.cognition.state.action import ActionPlan
            plan: ActionPlan | None = (
                state.action_plan
                if isinstance(state.action_plan, ActionPlan)
                else None
            )
            if plan is not None:
                objectives = [a.objective.lower() for a in plan.actions]
                if not any("kpi" in o or "performance" in o for o in objectives):
                    gaps.append("No KPI analysis in action plan")
                if not any("variance" in o for o in objectives):
                    gaps.append("No variance analysis in action plan")

        # ── Decision ──────────────────────────────────────────────────
        iteration_remaining = state.max_iterations - state.iteration_count

        if not gaps and overall >= self.CONFIDENCE_THRESHOLD:
            decision = "finalize"
        elif gaps and iteration_remaining > 0:
            decision = "revise"
        else:
            decision = "finalize"

        return NodeResult(
            node_name="reflection",
            success=True,
            state_updates={
                "loop_decision": decision,
                "gaps": gaps,
                "reflection_confidence": overall,
            },
            confidence=overall,
            message=(
                f"Decision: {decision} "
                f"(confidence={overall:.2f}, gaps={len(gaps)}, "
                f"iterations_remaining={iteration_remaining})"
            ),
        )
