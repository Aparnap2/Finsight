"""Anomaly-detection feature group (sources: ``actuals`` × ``budget_lines``).

Produces deterministic, versioned anomaly features per
``(entity_id, period, account_id)`` from a pre-joined actuals-vs-budget
frame. The input frame is expected to have one row per account with both
``actual_amount`` and ``budget_amount``.

Lineage (source table / column → feature):
    actuals.amount                 → ``actual_amount``
    budget_lines.amount            → ``budget_amount``
    (actual − budget)              → ``variance_amount``,
                                     ``variance_pct``,
                                     ``anomaly_abs_deviation``,
                                     ``anomaly_deviation_ratio``
    derived thresholds             → ``anomaly_flag_spike``,
                                     ``anomaly_flag_deficit``,
                                     ``anomaly_flag_material``

The builder is pure: it accepts a polars DataFrame and returns a polars
DataFrame. All monetary columns are ``Decimal`` (never ``float``).
"""

from __future__ import annotations

from decimal import Decimal

import polars as pl

from finance.feature_store.base import (
    assert_columns,
    assert_money_columns,
)

#: Semantic version of this feature group's feature set.
FEATURE_VERSION = "1.0.0"

#: Physical source tables this group derives its features from.
SOURCE_TABLE = "actuals x budget_lines"

#: Source columns consumed by :func:`build_anomaly_features`.
SOURCE_COLUMNS = (
    "entity_id",
    "period",
    "account_id",
    "department",
    "actual_amount",
    "budget_amount",
)

#: Key columns that identify a feature row.
KEY_COLUMNS = ("entity_id", "period", "account_id")

#: Complete output column contract (keys + features), stable across versions.
FEATURE_NAMES = (
    "entity_id",
    "period",
    "account_id",
    "department",
    "actual_amount",
    "budget_amount",
    "variance_amount",
    "variance_pct",
    "anomaly_abs_deviation",
    "anomaly_deviation_ratio",
    "anomaly_flag_spike",
    "anomaly_flag_deficit",
    "anomaly_flag_material",
)

#: Money columns that must remain ``Decimal``.
_MONEY_COLUMNS = (
    "actual_amount",
    "budget_amount",
    "variance_amount",
    "variance_pct",
    "anomaly_abs_deviation",
    "anomaly_deviation_ratio",
)

#: Sentinel used to neutralise division-by-zero denominators.
_ZERO = Decimal("0")

#: Spike flag: actual exceeds budget by more than this multiple (50% over).
_SPIKE_MULTIPLIER = Decimal("1.5")

#: Deficit flag: actual falls below budget by more than this multiple (50% under).
_DEFICIT_MULTIPLIER = Decimal("0.5")

#: Materiality threshold used by the anomaly flag (deterministic default).
_MATERIAL_PCT = Decimal("10")  # percentage points

#: Materiality threshold used by the anomaly flag (deterministic default).
_MATERIAL_ABS = Decimal("250000")


def build_anomaly_features(df: pl.DataFrame) -> pl.DataFrame:
    """Build anomaly features per ``(entity_id, period, account_id)``.

    The input frame must already join actuals with budget lines (one row
    per account). Missing budget lines surface as ``budget_amount == 0``
    (documented; a missing plan is degenerate).

    * ``variance_amount`` — actual − budget (Decimal);
    * ``variance_pct`` — (actual − budget) ÷ |budget| × 100, ``0`` when the
      budget is ``0`` (matches the variance-engine percent convention);
    * ``anomaly_abs_deviation`` — |variance_amount| (Decimal);
    * ``anomaly_deviation_ratio`` — deviation ÷ |budget|, ``0`` when the
      budget is ``0``;
    * ``anomaly_flag_spike`` — actual > budget × 1.5 (50% over plan);
    * ``anomaly_flag_deficit`` — actual < budget × 0.5 (50% under plan);
    * ``anomaly_flag_material`` — |variance_pct| > 10 **or**
      |variance_amount| > 250,000 (deterministic defaults; the
      variance engine's tiered materiality can refine this later).

    Args:
        df: joined frame with columns ``entity_id``, ``period``,
            ``account_id``, ``department`` (nullable), ``actual_amount``
            (Decimal), ``budget_amount`` (Decimal).

    Returns:
        A feature frame with ``FEATURE_NAMES`` columns, sorted by
        ``(entity_id, period, account_id)``. Money columns are ``Decimal``.

    Raises:
        FeatureStoreError: When required source columns are missing or the
            monetary columns are not ``Decimal``.
    """
    assert_columns(df, SOURCE_COLUMNS)
    assert_money_columns(df, ("actual_amount", "budget_amount"))

    out = (
        df.with_columns(
            (pl.col("actual_amount") - pl.col("budget_amount")).alias("variance_amount"),
            (
                (pl.col("actual_amount") - pl.col("budget_amount"))
                / pl.col("budget_amount").abs().replace(_ZERO, None)
                * Decimal("100")
            )
            .fill_null(_ZERO)
            .alias("variance_pct"),
        )
        .with_columns(
            pl.col("variance_amount").abs().alias("anomaly_abs_deviation"),
            (
                pl.col("variance_amount").abs()
                / pl.col("budget_amount").abs().replace(_ZERO, None)
            )
            .fill_null(_ZERO)
            .alias("anomaly_deviation_ratio"),
            (pl.col("actual_amount") > pl.col("budget_amount") * _SPIKE_MULTIPLIER).alias(
                "anomaly_flag_spike"
            ),
            (pl.col("actual_amount") < pl.col("budget_amount") * _DEFICIT_MULTIPLIER).alias(
                "anomaly_flag_deficit"
            ),
            (
                (pl.col("variance_pct").abs() > _MATERIAL_PCT)
                | (pl.col("variance_amount").abs() > _MATERIAL_ABS)
            ).alias("anomaly_flag_material"),
        )
        .select(list(FEATURE_NAMES))
        .sort(KEY_COLUMNS)
    )

    assert_money_columns(out, _MONEY_COLUMNS)
    return out


__all__ = [
    "FEATURE_NAMES",
    "FEATURE_VERSION",
    "KEY_COLUMNS",
    "SOURCE_COLUMNS",
    "SOURCE_TABLE",
    "build_anomaly_features",
]
