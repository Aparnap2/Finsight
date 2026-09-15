"""RiskProvider wiring — model confidence to risk decision.

Implements the ``RiskProvider`` protocol on top of any underlying provider
(rule set, ML model, or hybrid) and adds a deterministic decision layer.

Decision semantics mirror ``MaterialityEngine`` OR semantics
(``combined_rule="any"``, see ``finance/variance_engine/materiality.py``):
an entity is HIGH risk when its score exceeds the high threshold **or** its
score exceeds the review threshold while confidence is high. REVIEW when the
score crosses the review threshold **or** confidence is too low (uncertainty
routes to human review). LOW otherwise. Deterministic — no randomness.
"""

from __future__ import annotations

from typing import Any

from finance.ml.protocol import (
    ModelMetadata,
    RiskDecision,
    RiskEvaluation,
    RiskLevel,
    RiskProvider,
)


class RiskDecisionProvider(RiskProvider):
    """Wraps a :class:`RiskProvider` and adds OR-semantics risk decisions.

    The wrapper is itself a :class:`RiskProvider` so agents can keep calling
    ``evaluate()`` — the decision is attached to the evaluation metadata and
    is also available standalone via :meth:`decide`.
    """

    DEFAULT_ACTION_BY_LEVEL: dict[RiskLevel, str] = {
        RiskLevel.LOW: "auto_approve",
        RiskLevel.REVIEW: "route_for_review",
        RiskLevel.HIGH: "escalate",
    }

    def __init__(
        self,
        provider: RiskProvider,
        *,
        high_score: float = 0.7,
        review_score: float = 0.4,
        high_confidence: float = 0.8,
        low_confidence: float = 0.3,
        action_by_level: dict[RiskLevel, str] | None = None,
    ) -> None:
        self._provider = provider
        self.model_id = provider.model_id
        self.version = provider.version
        self._high_score = high_score
        self._review_score = review_score
        self._high_confidence = high_confidence
        self._low_confidence = low_confidence
        self._action_by_level = action_by_level or self.DEFAULT_ACTION_BY_LEVEL

    # ------------------------------------------------------------------
    # RiskProvider
    # ------------------------------------------------------------------

    def evaluate(self, context: dict[str, Any]) -> RiskEvaluation:
        """Evaluate the wrapped provider and attach the decision to metadata."""
        evaluation = self._provider.evaluate(context)
        decision = self.decide(evaluation)
        evaluation.metadata["risk_decision"] = decision.model_dump(mode="json")
        return evaluation

    def metadata(self) -> ModelMetadata:
        """Delegate metadata to the wrapped provider."""
        return self._provider.metadata()

    # ------------------------------------------------------------------
    # Decision layer
    # ------------------------------------------------------------------

    def decide(self, evaluation: RiskEvaluation) -> RiskDecision:
        """Convert an evaluation's score + confidence into a risk decision.

        OR semantics (mirrors ``MaterialityRule.combined_rule="any"``):
        high risk when ``score >= high_score`` OR
        ``score >= review_score AND confidence >= high_confidence``;
        review when ``score >= review_score`` OR ``confidence < low_confidence``.
        """
        score = evaluation.score
        confidence = evaluation.confidence
        reasons: list[str] = []

        if score >= self._high_score:
            reasons.append(
                f"score {score:.2f} >= high threshold {self._high_score:.2f}"
            )
        if score >= self._review_score and confidence >= self._high_confidence:
            reasons.append(
                f"score {score:.2f} >= review threshold {self._review_score:.2f} "
                f"with confidence {confidence:.2f} >= {self._high_confidence:.2f}"
            )
        if confidence < self._low_confidence:
            reasons.append(
                f"confidence {confidence:.2f} below {self._low_confidence:.2f} — "
                "insufficient signal for automation"
            )

        if score >= self._high_score or (
            score >= self._review_score and confidence >= self._high_confidence
        ):
            level = RiskLevel.HIGH
        elif score >= self._review_score or confidence < self._low_confidence:
            level = RiskLevel.REVIEW
        else:
            level = RiskLevel.LOW

        return RiskDecision(
            provider_id=self.model_id,
            entity_id=evaluation.entity_id,
            level=level,
            action=self._action_by_level[level],
            score=score,
            confidence=confidence,
            reasons=reasons,
            evaluated_at=evaluation.evaluated_at,
        )


def wrap_risk(provider: RiskProvider, **kwargs: Any) -> RiskDecisionProvider:
    """Convenience factory: wrap any provider with the decision layer."""
    return RiskDecisionProvider(provider, **kwargs)
