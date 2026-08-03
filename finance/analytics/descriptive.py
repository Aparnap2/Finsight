"""Descriptive analytics — the base of the prescriptive pyramid.

Deterministic descriptive statistics over the finance tables, computed
with polars: totals, period-over-period changes, and ratios. Every
function is Decimal-safe — monetary inputs stay ``decimal.Decimal`` and
ratios are computed with Decimal arithmetic (never ``float``).

The pyramid this module anchors:
    descriptive (this module) → diagnostic (``diagnostic.py``) →
    predictive (``predictive.py``, thin ML contract).
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

import polars as pl

from finance.feature_store.base import assert_columns, assert_money_columns

#: Sentinel used to neutralise division-by-zero denominators.
_ZERO = Decimal("0")


def compute_totals(
    df: pl.DataFrame,
    group_cols: Sequence[str],
    value_cols: Sequence[str],
) -> pl.DataFrame:
    """Return grouped totals for ``value_cols``.

    Groups ``df`` by ``group_cols`` and sums each ``value_col``. Monetary
    value columns must be ``Decimal``; the resulting totals stay Decimal.

    Args:
        df: Source frame.
        group_cols: Columns to group by.
        value_cols: Columns to sum. Monetary columns must be Decimal.

    Returns:
        Frame with ``group_cols`` plus one ``<col>_total`` column per
        ``value_col``, sorted by ``group_cols``.

    Raises:
        FeatureStoreError: When required columns are missing or a monetary
            ``value_col`` is not Decimal.
    """
    required = [*group_cols, *value_cols]
    assert_columns(df, required)
    assert_money_columns(df, value_cols)

    aggregates = [pl.col(col).sum().alias(f"{col}_total") for col in value_cols]
    return (
        df.group_by(list(group_cols))
        .agg(aggregates)
        .sort(list(group_cols))
    )


def compute_period_over_period(
    df: pl.DataFrame,
    entity_col: str,
    period_col: str,
    value_cols: Sequence[str],
) -> pl.DataFrame:
    """Return period-over-period deltas and growth for ``value_cols``.

    Requires ``period_col`` to sort chronologically within each entity.
    For each row, adds ``<col>_prior`` (previous period value),
    ``<col>_delta`` (current − prior), and ``<col>_growth``
    (delta ÷ |prior|). Growth is ``null`` when there is no prior period
    and ``0`` when the prior value is ``0`` (deterministic denominator
    guard, documented as degenerate).

    Args:
        df: Source frame.
        entity_col: Entity key column (e.g. ``entity_id``).
        period_col: Period column, sorted ascending within entity.
        value_cols: Monetary columns to compare (must be Decimal).

    Returns:
        Frame with the original columns plus prior/delta/growth columns
        for each ``value_col``.

    Raises:
        FeatureStoreError: When required columns are missing or a
            ``value_col`` is not Decimal.
    """
    required = [entity_col, period_col, *value_cols]
    assert_columns(df, required)
    assert_money_columns(df, value_cols)

    ordered = df.sort([entity_col, period_col])
    expressions: list[pl.Expr] = []
    for col in value_cols:
        prior = pl.col(col).shift(1).over(entity_col)
        delta = (pl.col(col) - prior).alias(f"{col}_delta")
        growth = (
            pl.when(prior.is_null())
            .then(None)
            .when(prior == _ZERO)
            .then(_ZERO)
            .otherwise(
                (pl.col(col) - prior) / prior.abs().replace(_ZERO, None)
            )
        ).alias(f"{col}_growth")
        expressions.append(prior.alias(f"{col}_prior"))
        expressions.append(delta)
        expressions.append(growth)
    return ordered.with_columns(expressions)


def compute_ratio(
    df: pl.DataFrame,
    numerator_col: str,
    denominator_col: str,
    out_col: str = "ratio",
) -> pl.DataFrame:
    """Return ``df`` with a Decimal ratio column appended.

    The ratio is ``numerator_col ÷ denominator_col`` with ``0`` when the
    denominator is ``0`` (deterministic denominator guard, documented as
    degenerate).

    Args:
        df: Source frame.
        numerator_col: Decimal monetary column.
        denominator_col: Decimal monetary column.
        out_col: Name of the appended ratio column.

    Returns:
        Frame with the original columns plus ``out_col``.

    Raises:
        FeatureStoreError: When either input column is missing or not
            Decimal.
    """
    assert_columns(df, [numerator_col, denominator_col])
    assert_money_columns(df, [numerator_col, denominator_col])
    return df.with_columns(
        (pl.col(numerator_col) / pl.col(denominator_col).replace(_ZERO, None))
        .fill_null(_ZERO)
        .alias(out_col)
    )


__all__ = ["compute_period_over_period", "compute_ratio", "compute_totals"]
