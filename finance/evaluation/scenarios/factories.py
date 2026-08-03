"""Golden dataset factory functions for the FinSight evaluation framework.

Each factory loads a base configuration from the corresponding JSON file in
``finance/evaluation/datasets/``, applies optional modifier keys, deep-merges
field-level overrides, and returns a validated ``GoldenDataset`` instance.

Usage::

    from finance.evaluation.scenarios import revenue_growth

    ds = revenue_growth()
    ds = revenue_growth(scale=2.0)
    ds = revenue_growth(currency="EUR", difficulty="advanced")
    ds = revenue_growth(overrides={"input.context.accounts.0.actual": 999999})
"""

from __future__ import annotations

import json
import random
from copy import deepcopy
from pathlib import Path
from typing import Any

from finance.evaluation.dataset import (
    DatasetInput,
    DatasetMetadata,
    ExecutionExpectation,
    ExpectedBehaviour,
    GoldenDataset,
    OutputExpectation,
    PlanningExpectation,
    ReflectionExpectation,
    VerificationExpectation,
)

_DATASETS_DIR = Path(__file__).resolve().parent.parent / "datasets"


# ── Internal helpers ──────────────────────────────────────────────────────


def _load_json(dataset_id: str) -> dict[str, Any]:
    """Load a JSON dataset file by its id (searches all subdirectories)."""
    for path in _DATASETS_DIR.rglob(f"{dataset_id}.json"):
        data: dict[str, Any] = json.loads(path.read_text())
        return data
    raise FileNotFoundError(
        f"Dataset '{dataset_id}' not found in {_DATASETS_DIR}"
    )


def _apply_overrides(raw: dict[str, Any], overrides: dict[str, Any] | None) -> dict[str, Any]:
    """Deep-merge dot-separated overrides into a raw dataset dict.

    Nested keys are expressed as dotted paths. Numeric parts index into
    lists; all other parts index into dicts::

        overrides={"input.context.accounts.0.actual": 999999}
    """
    if not overrides:
        return raw
    result = deepcopy(raw)
    for key, value in overrides.items():
        parts = key.split(".")
        target: Any = result
        for part in parts[:-1]:
            if isinstance(target, dict):
                target = target.setdefault(part, {} if not part.isdigit() else [])
            elif isinstance(target, list):
                idx = int(part)
                # Extend list if necessary
                while len(target) <= idx:
                    target.append({})
                target = target[idx]
        if isinstance(target, dict):
            target[parts[-1]] = value
        elif isinstance(target, list):
            idx = int(parts[-1])
            while len(target) <= idx:
                target.append({})
            target[idx] = value
    return result


def _build_dataset(raw: dict[str, Any]) -> GoldenDataset:
    """Parse a raw dictionary into a validated GoldenDataset instance."""
    meta = DatasetMetadata(**raw["metadata"])
    inp = DatasetInput(**raw.get("input", {}))
    raw_exp = raw.get("expected", {})
    exp = ExpectedBehaviour(
        planning=PlanningExpectation(**raw_exp.get("planning", {})),
        execution=ExecutionExpectation(**raw_exp.get("execution", {})),
        verification=VerificationExpectation(**raw_exp.get("verification", {})),
        reflection=ReflectionExpectation(**raw_exp.get("reflection", {})),
        output=OutputExpectation(**raw_exp.get("output", {})),
    )
    return GoldenDataset(metadata=meta, input=inp, expected=exp)


def _apply_modifiers(raw: dict[str, Any], **modifiers: Any) -> dict[str, Any]:
    """Apply common modifier keys to a raw dataset dictionary.

    Supported modifiers
    -------------------
    currency : str
        Set ``currency`` on every account in ``input.context.accounts``.
    noise : float
        Jitter *actual* and *budget* values by ``±noise * 100`` percent.
    scale : float
        Multiply all *actual* and *budget* values by this factor.
    difficulty : str
        Override ``metadata.difficulty`` (e.g. ``"basic"``, ``"advanced"``).
    """
    result = deepcopy(raw)

    currency = modifiers.get("currency")
    if currency:
        for acct in result.get("input", {}).get("context", {}).get("accounts", []):
            if isinstance(acct, dict):
                acct["currency"] = currency

    noise = modifiers.get("noise", 0.0)
    if noise > 0:
        for acct in result.get("input", {}).get("context", {}).get("accounts", []):
            if isinstance(acct, dict):
                _jitter_value(acct, "actual", noise)
                _jitter_value(acct, "budget", noise)

    scale = modifiers.get("scale")
    if scale is not None:
        for acct in result.get("input", {}).get("context", {}).get("accounts", []):
            if isinstance(acct, dict):
                _scale_value(acct, "actual", scale)
                _scale_value(acct, "budget", scale)

    difficulty = modifiers.get("difficulty")
    if difficulty:
        result.setdefault("metadata", {})["difficulty"] = difficulty

    return result


def _jitter_value(acct: dict[str, Any], field: str, noise: float) -> None:
    """Multiply *field* in *acct* by a random factor in ``[1-noise, 1+noise]``."""
    val = acct.get(field)
    if val is not None and isinstance(val, (int, float)):
        acct[field] = round(val * (1 + random.uniform(-noise, noise)), 2)


def _scale_value(acct: dict[str, Any], field: str, scale: float) -> None:
    """Multiply *field* in *acct* by *scale*."""
    val = acct.get(field)
    if val is not None and isinstance(val, (int, float)):
        acct[field] = round(val * scale, 2)


# ── Recipe: Factory template helper ───────────────────────────────────────


def _factory(
    dataset_id: str, overrides: dict[str, Any] | None = None, **modifiers: Any
) -> GoldenDataset:
    """Generic factory that any dataset can be built from.

    This is the shared implementation used by all public factories below.
    """
    raw = _load_json(dataset_id)
    raw = _apply_modifiers(raw, **modifiers)
    raw = _apply_overrides(raw, overrides)
    return _build_dataset(raw)


# ══════════════════════════════════════════════════════════════════════════
# Financial Logic — 7 datasets
# ══════════════════════════════════════════════════════════════════════════


def revenue_growth(overrides: dict[str, Any] | None = None, **modifiers: Any) -> GoldenDataset:
    """Standard revenue growth scenario with a clear positive variance."""
    return _factory("revenue_growth", overrides, **modifiers)


def margin_decline(overrides: dict[str, Any] | None = None, **modifiers: Any) -> GoldenDataset:
    """Revenue grew but costs grew faster, compressing margins."""
    return _factory("margin_decline", overrides, **modifiers)


def budget_variance(overrides: dict[str, Any] | None = None, **modifiers: Any) -> GoldenDataset:
    """Standard multi-account budget variance analysis."""
    return _factory("budget_variance", overrides, **modifiers)


def negative_revenue(overrides: dict[str, Any] | None = None, **modifiers: Any) -> GoldenDataset:
    """Revenue reversal due to returns and credits."""
    return _factory("negative_revenue", overrides, **modifiers)


def zero_budget(overrides: dict[str, Any] | None = None, **modifiers: Any) -> GoldenDataset:
    """Accounts with zero budget allocation showing actual spend."""
    return _factory("zero_budget", overrides, **modifiers)


def seasonality(overrides: dict[str, Any] | None = None, **modifiers: Any) -> GoldenDataset:
    """Revenue with strong seasonal patterns across Q1."""
    return _factory("seasonality", overrides, **modifiers)


def fx_impact(overrides: dict[str, Any] | None = None, **modifiers: Any) -> GoldenDataset:
    """International revenue affected by unfavourable FX rate movements."""
    return _factory("fx_impact", overrides, **modifiers)


# ══════════════════════════════════════════════════════════════════════════
# Data Quality — 5 datasets
# ══════════════════════════════════════════════════════════════════════════


def missing_data(overrides: dict[str, Any] | None = None, **modifiers: Any) -> GoldenDataset:
    """Some accounts have null values for actual or budget."""
    return _factory("missing_values", overrides, **modifiers)


def duplicate_rows(overrides: dict[str, Any] | None = None, **modifiers: Any) -> GoldenDataset:
    """Accounts with duplicate entries requiring deduplication."""
    return _factory("duplicate_rows", overrides, **modifiers)


def malformed_spreadsheet(
    overrides: dict[str, Any] | None = None, **modifiers: Any
) -> GoldenDataset:
    """Spreadsheet data with malformed rows and invalid values."""
    return _factory("malformed_spreadsheet", overrides, **modifiers)


def currency_mismatch(overrides: dict[str, Any] | None = None, **modifiers: Any) -> GoldenDataset:
    """Accounts denominated in different currencies requiring conversion."""
    return _factory("currency_mismatch", overrides, **modifiers)


def invalid_periods(overrides: dict[str, Any] | None = None, **modifiers: Any) -> GoldenDataset:
    """Accounts referencing invalid or non-existent fiscal periods."""
    return _factory("invalid_periods", overrides, **modifiers)


# ══════════════════════════════════════════════════════════════════════════
# Runtime Behaviour — 4 datasets
# ══════════════════════════════════════════════════════════════════════════


def retry_scenario(overrides: dict[str, Any] | None = None, **modifiers: Any) -> GoldenDataset:
    """Transient data-source failures requiring retry logic."""
    return _factory("retry_scenario", overrides, **modifiers)


def replanning_scenario(overrides: dict[str, Any] | None = None, **modifiers: Any) -> GoldenDataset:
    """Initial plan fails, requiring dynamic replanning."""
    return _factory("replanning_scenario", overrides, **modifiers)


def missing_evidence(overrides: dict[str, Any] | None = None, **modifiers: Any) -> GoldenDataset:
    """Claims lack sufficient supporting evidence."""
    return _factory("missing_evidence", overrides, **modifiers)


def unsupported_assertions(
    overrides: dict[str, Any] | None = None, **modifiers: Any
) -> GoldenDataset:
    """Some assertions produced without full data backing."""
    return _factory("unsupported_assertions", overrides, **modifiers)


# ══════════════════════════════════════════════════════════════════════════
# Governance — 4 datasets
# ══════════════════════════════════════════════════════════════════════════


def policy_violation(overrides: dict[str, Any] | None = None, **modifiers: Any) -> GoldenDataset:
    """Accounts with policy-restricted spending limits exceeded."""
    return _factory("policy_violation", overrides, **modifiers)


def contradictory_evidence(
    overrides: dict[str, Any] | None = None, **modifiers: Any
) -> GoldenDataset:
    """Conflicting values from different data sources."""
    return _factory("contradictory_evidence", overrides, **modifiers)


def forbidden_claim(overrides: dict[str, Any] | None = None, **modifiers: Any) -> GoldenDataset:
    """Scenario testing that definitive causal claims are avoided."""
    return _factory("forbidden_claim", overrides, **modifiers)


def low_confidence(overrides: dict[str, Any] | None = None, **modifiers: Any) -> GoldenDataset:
    """Multiple data quality issues resulting in low overall confidence."""
    return _factory("low_confidence", overrides, **modifiers)
