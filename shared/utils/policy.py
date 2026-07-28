"""Policy engine — Autonomy Policy Matrix.

Determines routing decisions and autonomy levels based on:
- Assertion confidence (deterministic)
- Degraded modes present
- Assertion types involved
- Data quality status

Autonomy Levels:
- FULLY_AUTONOMOUS: confidence >= 0.8, no degraded modes, no causal/action claims
- ANALYST_IN_THE_LOOP: confidence >= 0.6, minor degraded modes, or comparative/causal claims
- MANAGER_APPROVAL: confidence >= 0.4, degraded modes present, or action claims
- CFO_APPROVAL: confidence < 0.4, critical degraded modes, or high-impact actions
"""

from enum import Enum
from typing import Any

from shared.models.assertions import Assertion, AssertionType, SupportLevel
from shared.models.degraded_mode import DegradedMode


class AutonomyLevel(str, Enum):
    FULLY_AUTONOMOUS = "fully_autonomous"
    ANALYST_IN_THE_LOOP = "analyst_in_the_loop"
    MANAGER_APPROVAL = "manager_approval"
    CFO_APPROVAL = "cfo_approval"


class PolicyDecision:
    """Result of a policy evaluation."""

    def __init__(
        self,
        autonomy_level: AutonomyLevel,
        routing_target: str,
        reasons: list[str] | None = None,
        requires_review: bool = False,
        blocked_actions: list[str] | None = None,
        confidence: float = 0.0,
    ):
        self.autonomy_level = autonomy_level
        self.routing_target = routing_target
        self.reasons = reasons or []
        self.requires_review = requires_review
        self.blocked_actions = blocked_actions or []
        self.confidence = confidence

    def to_dict(self) -> dict:
        return {
            "autonomy_level": self.autonomy_level.value,
            "routing_target": self.routing_target,
            "reasons": self.reasons,
            "requires_review": self.requires_review,
            "blocked_actions": self.blocked_actions,
            "confidence": self.confidence,
        }


def evaluate_policy(
    assertions: list[Assertion],
    degraded_modes: list[str] | None = None,
    has_causal_claims: bool = False,
    has_action_claims: bool = False,
) -> PolicyDecision:
    """Evaluate the Autonomy Policy Matrix for a set of assertions.

    Returns a PolicyDecision with autonomy level, routing target, and reasons.
    """
    if not assertions:
        return PolicyDecision(
            autonomy_level=AutonomyLevel.ANALYST_IN_THE_LOOP,
            routing_target="review",
            reasons=["No assertions to evaluate"],
            requires_review=True,
            confidence=0.0,
        )

    degraded_modes = degraded_modes or []
    reasons: list[str] = []
    blocked_actions: list[str] = []

    # Compute aggregate confidence
    avg_confidence = sum(a.confidence for a in assertions) / len(assertions)
    min_confidence = min(a.confidence for a in assertions)

    # Check for critical degraded modes
    has_critical_degraded = any(
        dm
        in (
            DegradedMode.LOW_COVERAGE.value,
            DegradedMode.STALE_SOURCE.value,
            DegradedMode.INSUFFICIENT_CAUSAL_EVIDENCE.value,
        )
        for dm in degraded_modes
    )
    has_minor_degraded = len(degraded_modes) > 0 and not has_critical_degraded

    # Check for action claims that might be blocked
    for a in assertions:
        if a.type == AssertionType.ACTION:
            action = (a.metadata or {}).get("action", "")
            impact = (a.metadata or {}).get("impact_quantified", False)
            if not impact and avg_confidence < 0.6:
                blocked_actions.append(
                    f"Action '{action}' blocked: impact not quantified and confidence < 0.6"
                )

    # Determine autonomy level
    if (
        avg_confidence >= 0.8
        and min_confidence >= 0.6
        and not has_critical_degraded
        and not has_action_claims
        and not has_causal_claims
        and not degraded_modes
    ):
        level = AutonomyLevel.FULLY_AUTONOMOUS
        routing_target = "auto_publish"
        reasons.append(
            f"High confidence ({avg_confidence:.0%}), no degraded modes, fact-only assertions"
        )

    elif (
        avg_confidence >= 0.6
        and not has_critical_degraded
        and not blocked_actions
    ):
        level = AutonomyLevel.ANALYST_IN_THE_LOOP
        routing_target = "review"
        reasons.append(f"Adequate confidence ({avg_confidence:.0%})")
        if has_minor_degraded:
            reasons.append(f"Minor degraded modes: {', '.join(degraded_modes)}")
        if has_causal_claims:
            reasons.append("Causal claims present — require analyst review")

    elif (
        avg_confidence >= 0.4
        or (has_critical_degraded and avg_confidence >= 0.5)
    ):
        level = AutonomyLevel.MANAGER_APPROVAL
        routing_target = "manager_review"
        reasons.append(f"Moderate confidence ({avg_confidence:.0%})")
        if has_critical_degraded:
            critical_dms = [
                dm
                for dm in degraded_modes
                if dm
                in (
                    DegradedMode.LOW_COVERAGE.value,
                    DegradedMode.STALE_SOURCE.value,
                    DegradedMode.INSUFFICIENT_CAUSAL_EVIDENCE.value,
                )
            ]
            reasons.append(f"Critical degraded modes: {', '.join(critical_dms)}")
        if blocked_actions:
            reasons.extend(blocked_actions)

    else:
        level = AutonomyLevel.CFO_APPROVAL
        routing_target = "cfo_review"
        reasons.append(f"Low confidence ({avg_confidence:.0%}) requires CFO review")
        if degraded_modes:
            reasons.append(f"Degraded modes: {', '.join(degraded_modes)}")
        if blocked_actions:
            reasons.extend(blocked_actions)

    return PolicyDecision(
        autonomy_level=level,
        routing_target=routing_target,
        reasons=reasons,
        requires_review=level != AutonomyLevel.FULLY_AUTONOMOUS,
        blocked_actions=blocked_actions,
        confidence=avg_confidence,
    )


def evaluate_from_pipeline_result(
    pipeline_result: "AssertionPipelineResult",  # noqa: F821
    degraded_modes: list[str] | None = None,
) -> PolicyDecision:
    """Evaluate policy using an AssertionPipelineResult directly."""
    has_causal = any(a.type == AssertionType.CAUSAL for a in pipeline_result.assertions)
    has_action = any(a.type == AssertionType.ACTION for a in pipeline_result.assertions)

    return evaluate_policy(
        assertions=pipeline_result.assertions,
        degraded_modes=degraded_modes or pipeline_result.degraded_modes,
        has_causal_claims=has_causal,
        has_action_claims=has_action,
    )


def get_route(state: dict[str, Any]) -> str:
    """Determine the next routing target from PipelineState.

    Reads data_quality and assertions from state to determine route.
    This integrates with the LangGraph router.
    """
    degraded_modes: list[str] = state.get("degraded_modes", [])
    assertions: list[Assertion] = state.get("assertions", [])
    variances: list[Any] = state.get("variances", [])

    # If no material variances, skip to commentary
    if variances and not any(v.is_material for v in variances):
        return "commentary"

    if not assertions:
        return "root_cause"

    decision = evaluate_policy(
        assertions=assertions,
        degraded_modes=degraded_modes,
    )

    return decision.routing_target
