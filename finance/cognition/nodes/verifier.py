from __future__ import annotations

from statistics import mean
from typing import Any

from finance.cognition.state.action import ActionStatus
from finance.cognition.state.models import ReasoningState
from finance.cognition.state.node import NodeResult
from shared.models.assertions import SupportLevel


class VerifierNode:
    """Verify assertions and action results.

    Evaluates every assertion in the state and flags those that need
    revision based on confidence, support level, missing evidence, and
    contradictions.  Also verifies the action_plan if present, checking
    each action for success/failure and recording action_verifications.
    """

    MIN_CONFIDENCE_THRESHOLD = 0.5

    def execute(self, state: ReasoningState) -> NodeResult:
        assertions = state.assertions

        low_confidence = [
            a for a in assertions if a.confidence < self.MIN_CONFIDENCE_THRESHOLD
        ]
        unsupported = [
            a
            for a in assertions
            if a.support_level in (SupportLevel.WEAK, SupportLevel.INSUFFICIENT)
        ]
        missing_evidence = [a for a in assertions if a.missing_evidence]
        contradicted = [a for a in assertions if a.contradictions]
        verified = [
            a
            for a in assertions
            if a.support_level == SupportLevel.VERIFIED
        ]

        avg_confidence = mean([a.confidence for a in assertions]) if assertions else 0.0
        issues = len(low_confidence) + len(unsupported)
        needs_revision = issues > 0

        message_parts: list[str] = []
        if assertions:
            message_parts.append(
                f"{len(verified)}/{len(assertions)} verified"
            )
            if low_confidence:
                message_parts.append(f"{len(low_confidence)} low-confidence")
            if unsupported:
                message_parts.append(
                    f"{len(unsupported)} unsupported"
                )
            if missing_evidence:
                message_parts.append(
                    f"{len(missing_evidence)} missing evidence"
                )
            if contradicted:
                message_parts.append(
                    f"{len(contradicted)} contradicted"
                )
        else:
            message_parts.append("no assertions")

        state_updates: dict[str, Any] = {
            "needs_revision": needs_revision,
            "overall_confidence": round(avg_confidence, 4),
            "verified_count": len(verified),
            "low_confidence_count": len(low_confidence),
            "unsupported_count": len(unsupported),
            "missing_evidence_count": len(missing_evidence),
            "contradicted_count": len(contradicted),
        }

        # ── Action verification ───────────────────────────────────────────
        action_verifications: list[dict[str, Any]] = list(
            state.context.get("action_verifications", [])
        )
        actions_passed = 0
        actions_total = 0

        if state.action_plan is not None:
            from finance.cognition.state.action import ActionPlan
            plan: ActionPlan | None = (
                state.action_plan
                if isinstance(state.action_plan, ActionPlan)
                else None
            )
            if plan is not None:
                for action in plan.actions:
                    actions_total += 1
                    has_outputs = bool(action.outputs)
                    has_evidence = bool(action.evidence_ids)
                    passed = action.status == ActionStatus.SUCCESS and (
                        has_outputs or has_evidence
                    )
                    if passed:
                        actions_passed += 1

                    action_verifications.append({
                        "action_id": action.id,
                        "objective": action.objective,
                        "status": action.status.value,
                        "passed": passed,
                        "has_outputs": has_outputs,
                        "has_evidence": has_evidence,
                    })

        state_updates["action_verifications"] = action_verifications
        if actions_total > 0:
            state_updates["actions_total"] = actions_total
            state_updates["actions_passed"] = actions_passed

        return NodeResult(
            node_name="verifier",
            success=True,
            state_updates=state_updates,
            confidence=avg_confidence,
            message=", ".join(message_parts),
        )
