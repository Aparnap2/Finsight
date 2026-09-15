"""Department-level feature group (source: ``headcount_data``).

Produces deterministic, versioned department features aggregated per
``(entity_id, period, department)`` from the ``headcount_data`` finance
table.

Lineage (source table / column → feature):
    headcount_data.headcount             → ``headcount_total``
    headcount_data.new_hires             → ``headcount_new_hires``
    headcount_data.departures            → ``headcount_departures``,
                                           ``headcount_turnover_rate``
    headcount_data.total_compensation    → ``dept_total_compensation``,
                                           ``dept_comp_per_head``
    headcount_data.department            → key column ``department``

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

#: Physical source table this group derives its features from.
SOURCE_TABLE = "headcount_data"

#: Source columns consumed by :func:`build_department_features`.
SOURCE_COLUMNS = (
    "entity_id",
    "period",
    "department",
    "headcount",
    "new_hires",
    "departures",
    "total_compensation",
)

#: Key columns that identify a feature row.
KEY_COLUMNS = ("entity_id", "period", "department")

#: Complete output column contract (keys + features), stable across versions.
FEATURE_NAMES = (
    "entity_id",
    "period",
    "department",
    "headcount_total",
    "headcount_new_hires",
    "headcount_departures",
    "headcount_net_change",
    "headcount_turnover_rate",
    "dept_total_compensation",
    "dept_comp_per_head",
)

#: Money columns that must remain ``Decimal``.
_MONEY_COLUMNS = (
    "headcount_turnover_rate",
    "dept_total_compensation",
    "dept_comp_per_head",
)

#: Sentinel used to neutralise division-by-zero denominators.
_ZERO = Decimal("0")


def build_department_features(df: pl.DataFrame) -> pl.DataFrame:
    """Build department features per ``(entity_id, period, department)``.

    Aggregates the ``headcount_data`` source frame into one row per
    ``(entity_id, period, department)``:

    * ``headcount_total`` — sum of headcount;
    * ``headcount_new_hires`` / ``headcount_departures`` — sums;
    * ``headcount_net_change`` — new hires − departures;
    * ``headcount_turnover_rate`` — departures ÷ headcount (Decimal),
      ``0`` when headcount is ``0``;
    * ``dept_total_compensation`` — sum of compensation (Decimal);
    * ``dept_comp_per_head`` — compensation ÷ headcount (Decimal), ``0``
      when headcount is ``0``.

    Args:
        df: ``headcount_data`` frame with columns ``entity_id``, ``period``,
            ``department``, ``headcount``, ``new_hires``, ``departures``,
            ``total_compensation`` (Decimal).

    Returns:
        A feature frame with ``FEATURE_NAMES`` columns, sorted by
        ``(entity_id, period, department)``. Money columns are ``Decimal``.

    Raises:
        FeatureStoreError: When required source columns are missing or the
            monetary columns are not ``Decimal``.
    """
    assert_columns(df, SOURCE_COLUMNS)
    assert_money_columns(df, ("total_compensation",))

    out = (
        df.group_by(["entity_id", "period", "department"])
        .agg(
            pl.col("headcount").sum().alias("headcount_total"),
            pl.col("new_hires").sum().alias("headcount_new_hires"),
            pl.col("departures").sum().alias("headcount_departures"),
            pl.col("total_compensation").sum().alias("dept_total_compensation"),
        )
        .with_columns(
            (pl.col("headcount_new_hires") - pl.col("headcount_departures")).alias(
                "headcount_net_change"
            ),
            (
                pl.col("headcount_departures").cast(pl.Decimal(38, 2))
                / pl.col("headcount_total").cast(pl.Decimal(38, 2)).replace(_ZERO, None)
            )
            .fill_null(_ZERO)
            .alias("headcount_turnover_rate"),
            (
                pl.col("dept_total_compensation")
                / pl.col("headcount_total").cast(pl.Decimal(38, 2)).replace(_ZERO, None)
            )
            .fill_null(_ZERO)
            .alias("dept_comp_per_head"),
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
    "build_department_features",
]
