"""Scenario factory functions for the FinSight evaluation framework.

Each factory loads a golden dataset from a JSON file, applies optional
modifiers (``currency``, ``scale``, ``noise``, ``difficulty``) and
dot-path ``overrides``, and returns a validated ``GoldenDataset``.

Usage::

    from finance.evaluation.scenarios import revenue_growth, budget_variance

    ds = revenue_growth()
    ds = budget_variance(scale=2.0, currency="EUR")
    ds = seasonality(overrides={"input.context.accounts.0.actual": 500000})
"""

from finance.evaluation.scenarios.factories import (
    budget_variance,
    contradictory_evidence,
    currency_mismatch,
    duplicate_rows,
    forbidden_claim,
    fx_impact,
    invalid_periods,
    low_confidence,
    malformed_spreadsheet,
    margin_decline,
    missing_data,
    missing_evidence,
    negative_revenue,
    policy_violation,
    replanning_scenario,
    retry_scenario,
    revenue_growth,
    seasonality,
    unsupported_assertions,
    zero_budget,
)

__all__ = [
    "revenue_growth",
    "margin_decline",
    "budget_variance",
    "negative_revenue",
    "zero_budget",
    "seasonality",
    "fx_impact",
    "missing_data",
    "duplicate_rows",
    "malformed_spreadsheet",
    "currency_mismatch",
    "invalid_periods",
    "retry_scenario",
    "replanning_scenario",
    "missing_evidence",
    "unsupported_assertions",
    "policy_violation",
    "contradictory_evidence",
    "forbidden_claim",
    "low_confidence",
]
