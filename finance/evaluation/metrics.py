"""Evaluation metrics for comparing pipeline output against golden data.

Two families of metrics live here:

1. **Score metrics** (``[0.0, 1.0]``) — the existing business/runtime metrics
   plus :class:`PrecisionAtK` for anomaly and duplicate detection.
2. **Error metrics** — :class:`MeanAbsoluteError`, :class:`RootMeanSquaredError`
   and :class:`MeanAbsolutePercentageError` for forecast evaluation.  These
   operate on ``Decimal`` money-safe values and return ``None`` for degenerate
   (empty / all-zero denominator) input rather than inventing a score.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from finance.cognition.state.action import Action, ActionPlan, ActionStatus

# ── Business Metrics (existing) ──────────────────────────────────────────────


class VarianceAccuracy:
    """Compares expected variance records to actual pipeline output.

    Matching is performed by ``account_id``.  A record counts as a match
    when both ``variance_amount`` and ``variance_pct`` are equal.
    """

    @staticmethod
    def compute(expected: list[dict[str, Any]], actual: list[dict[str, Any]]) -> float:
        if not expected:
            return 0.0

        matched = 0
        for exp in expected:
            for act in actual:
                if exp.get("account_id") == act.get("account_id"):
                    if (
                        exp.get("variance_amount") == act.get("variance_amount")
                        and exp.get("variance_pct") == act.get("variance_pct")
                    ):
                        matched += 1
                    break

        return matched / len(expected)


class KPIAccuracy:
    """Compares expected KPI records to actual pipeline output.

    Matching is performed by ``name``.  When a ``tolerance`` is configured,
    values within that absolute tolerance count as a match.
    """

    def __init__(self, tolerance: Decimal | None = None) -> None:
        self.tolerance = tolerance

    def compute(self, expected: list[dict[str, Any]], actual: list[dict[str, Any]]) -> float:
        if not expected:
            return 0.0

        matched = 0
        for exp in expected:
            for act in actual:
                if exp.get("name") == act.get("name"):
                    exp_val = exp.get("value")
                    act_val = act.get("value")
                    if self.tolerance is not None:
                        try:
                            diff = abs(Decimal(str(act_val)) - Decimal(str(exp_val)))
                            if diff <= self.tolerance:
                                matched += 1
                        except (ValueError, TypeError):
                            pass
                    else:
                        try:
                            if Decimal(str(act_val)) == Decimal(str(exp_val)):
                                matched += 1
                        except (ValueError, TypeError):
                            if act_val == exp_val:
                                matched += 1
                    break

        return matched / len(expected)


class ReportCoverage:
    """Checks that expected substrings appear in actual report sections.

    Comparisons are case-insensitive.  Each expected section key is looked
    up in the actual content dictionary.
    """

    @staticmethod
    def compute(
        expected_sections: dict[str, str],
        actual_content: dict[str, str],
    ) -> float:
        if not expected_sections:
            return 0.0

        matched = 0
        for section_key, expected_text in expected_sections.items():
            actual_text = actual_content.get(section_key, "")
            if expected_text.lower() in actual_text.lower():
                matched += 1

        return matched / len(expected_sections)


# ── Business Metrics (new) ──────────────────────────────────────────────────


class UnsupportedClaimRate:
    """Measures the proportion of assertions with insufficient support.

    A score of 1.0 means all assertions are VERIFIED or PROBABLE.
    Renamed from HallucinationRate — this measures unsupported claims,
    not model hallucination, because the runtime is deterministic.
    """

    @staticmethod
    def compute(assertions: list[Any]) -> float:
        if not assertions:
            return 1.0
        supported = sum(
            1 for a in assertions
            if a.support_level in ("verified", "probable")
        )
        return supported / len(assertions)


class EvidenceCoverage:
    """Average number of evidence items per assertion, normalised to a target.

    Returns the ratio of actual avg evidence to the target, capped at 1.0.
    """

    def __init__(self, min_evidence_target: int = 1) -> None:
        self._target = min_evidence_target

    def compute(self, assertions: list[Any]) -> float:
        if not assertions:
            return 0.0
        total_evidence = sum(len(a.evidence_ids) for a in assertions)
        avg = total_evidence / len(assertions)
        return min(avg / self._target, 1.0)


class PolicyCompliance:
    """Fraction of assertions whose max_allowed_action was respected."""

    @staticmethod
    def compute(assertions: list[Any]) -> float:
        if not assertions:
            return 1.0
        blocked = {"block", "escalate"}
        compliant = sum(
            1 for a in assertions
            if a.max_allowed_action not in blocked
            or a.max_allowed_action == "route_for_review"
        )
        return compliant / len(assertions)


# ── Runtime Metrics ─────────────────────────────────────────────────────────


class PlanningAccuracy:
    """Measures whether the planner produced required intents and avoided forbidden ones."""

    @staticmethod
    def compute(
        required_intents: list[str],
        forbidden_intents: list[str],
        action_plan: ActionPlan | None,
    ) -> float:
        if not required_intents and not forbidden_intents:
            return 1.0

        if action_plan is None:
            return 0.0

        action_objectives = [a.objective.lower() for a in action_plan.actions]

        if required_intents:
            found_required = sum(
                1 for r in required_intents
                if any(r.lower() in obj for obj in action_objectives)
            )
            required_score = found_required / len(required_intents)
        else:
            required_score = 1.0

        if forbidden_intents:
            found_forbidden = sum(
                1 for f in forbidden_intents
                if any(f.lower() in obj for obj in action_objectives)
            )
            forbidden_score = 1.0 - (found_forbidden / len(forbidden_intents))
        else:
            forbidden_score = 1.0

        return (required_score + forbidden_score) / 2.0


class ReplanningFrequency:
    """Compares actual replanning count vs expected max_replans.

    1.0 = no replanning needed (or within budget).
    0.0 = exceeded max replans.
    """

    @staticmethod
    def compute(max_replans: int, plan_history: list[Any]) -> float:
        replan_count = max(0, len(plan_history) - 1)
        if max_replans == 0:
            return 1.0 if replan_count == 0 else 0.0
        ratio = replan_count / (max_replans + 1)
        return max(0.0, 1.0 - ratio)


class ActionSuccessRate:
    """Fraction of actions that completed successfully."""

    @staticmethod
    def compute(actions: list[Action]) -> float:
        if not actions:
            return 0.0
        successful = sum(1 for a in actions if a.status == ActionStatus.SUCCESS)
        return successful / len(actions)


class RetryRate:
    """Total retries / total actions. 0 retries = score of 1.0."""

    @staticmethod
    def compute(actions: list[Action]) -> float:
        if not actions:
            return 0.0
        total_retries = sum(a.retry_count for a in actions)
        avg_retries = total_retries / len(actions)
        return max(0.0, 1.0 - avg_retries)


class AverageLatency:
    """Mean action latency in ms. Score is 1.0 if under budget, degrading beyond."""

    def __init__(self, budget_ms: int = 1000) -> None:
        self._budget_ms = budget_ms

    def compute(self, actions: list[Action]) -> float:
        if not actions:
            return 0.0
        avg_latency = sum(a.latency_ms for a in actions) / len(actions)
        if avg_latency <= self._budget_ms:
            return 1.0
        if avg_latency >= self._budget_ms * 2:
            return 0.0
        return 1.0 - (avg_latency - self._budget_ms) / self._budget_ms


class ToolFailureRate:
    """Fraction of tool calls that failed. 0 failures = score of 1.0."""

    @staticmethod
    def compute(actions: list[Action]) -> float:
        if not actions:
            return 0.0
        failed = sum(1 for a in actions if a.status == ActionStatus.FAILED)
        return 1.0 - (failed / len(actions))


# ── Forecast Error Metrics (money-safe, Decimal) ─────────────────────────────


def _as_decimal(value: Decimal | int | str) -> Decimal:
    """Normalise a money-safe value to Decimal.

    Floats are intentionally rejected — monetary values must be Decimal
    (or int/str which convert losslessly).  This mirrors the ``MoneyDecimal``
    boundary used across the platform.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        raise TypeError(
            "Float values are not allowed for monetary metrics. "
            "Use decimal.Decimal, int, or str instead."
        )
    return Decimal(str(value))


class MeanAbsoluteError:
    """Mean absolute error between a forecast and observed actuals.

    Money-safe (Decimal).  Returns ``None`` when either series is empty
    or the two series have different lengths (degenerate input).
    """

    @staticmethod
    def compute(
        actual: Sequence[Decimal | int | str],
        predicted: Sequence[Decimal | int | str],
    ) -> Decimal | None:
        if not actual or not predicted or len(actual) != len(predicted):
            return None
        total = Decimal("0")
        for a, p in zip(actual, predicted, strict=True):
            total += abs(_as_decimal(a) - _as_decimal(p))
        return total / Decimal(len(actual))


class RootMeanSquaredError:
    """Root mean squared error between a forecast and observed actuals.

    Money-safe (Decimal).  Returns ``None`` for empty or length-mismatched
    input.  Penalises large errors more heavily than :class:`MeanAbsoluteError`.
    """

    @staticmethod
    def compute(
        actual: Sequence[Decimal | int | str],
        predicted: Sequence[Decimal | int | str],
    ) -> Decimal | None:
        if not actual or not predicted or len(actual) != len(predicted):
            return None
        total = Decimal("0")
        for a, p in zip(actual, predicted, strict=True):
            diff = _as_decimal(a) - _as_decimal(p)
            total += diff * diff
        mean_sq = total / Decimal(len(actual))
        return mean_sq.sqrt()


class MeanAbsolutePercentageError:
    """Mean absolute percentage error, returned as a fraction (0.05 == 5%).

    Points where the actual value is zero are excluded because the
    percentage is undefined for a zero denominator.  Returns ``None`` when
    there are no usable points (empty input or all actuals zero).
    """

    @staticmethod
    def compute(
        actual: Sequence[Decimal | int | str],
        predicted: Sequence[Decimal | int | str],
    ) -> Decimal | None:
        if not actual or not predicted or len(actual) != len(predicted):
            return None
        total = Decimal("0")
        count = 0
        for a, p in zip(actual, predicted, strict=True):
            a_dec = _as_decimal(a)
            if a_dec == 0:
                continue
            total += abs(a_dec - _as_decimal(p)) / abs(a_dec)
            count += 1
        if count == 0:
            return None
        return total / Decimal(count)


# ── Ranked Detection Metrics ─────────────────────────────────────────────────


class PrecisionAtK:
    """Precision@K for anomaly / duplicate detection ranking.

    Measures how many of the top-``k`` retrieved records are actually
    relevant (expected).  Returns a float in ``[0.0, 1.0]``.  Degenerate
    inputs (empty detected set, ``k <= 0``) yield ``0.0``.
    """

    @staticmethod
    def compute(
        expected: Sequence[str],
        detected: Sequence[str],
        k: int | None = None,
    ) -> float:
        if k is None:
            k = len(detected)
        if k <= 0 or not detected:
            return 0.0
        expected_set = set(expected)
        top_k = list(detected[:k])
        if not top_k:
            return 0.0
        hits = sum(1 for item in top_k if item in expected_set)
        return hits / len(top_k)


# ── Aggregation ─────────────────────────────────────────────────────────────


class OverallScore:
    """Aggregates individual metric scores into a single overall score.

    The overall is the arithmetic mean of all provided scores.  A result is
    considered *passed* when the overall is >= 0.7.
    """

    @staticmethod
    def compute(scores: dict[str, float]) -> dict[str, Any]:
        if not scores:
            return {"overall": 0.0, "passed": False}
        overall = round(sum(scores.values()) / len(scores), 10)
        passed = overall >= 0.7
        return {"overall": overall, "passed": passed}
