"""Forecast feature group (source: ``forecast_lines``).

Produces deterministic, versioned forecast features aggregated per
``(entity_id, period, department)`` from the ``forecast_lines`` finance
table.

Lineage (source table / column → feature):
    forecast_lines (row count)     → ``forecast_line_count``
    forecast_lines.version         → ``forecast_version_max``
    forecast_lines.amount          → ``forecast_amount_total``,
                                     ``forecast_amount_avg``,
                                     ``forecast_latest_amount_total``,
                                     ``forecast_share_of_entity``
    forecast_lines.department      → key column ``department``

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
SOURCE_TABLE = "forecast_lines"

#: Source columns consumed by :func:`build_forecast_features`.
SOURCE_COLUMNS = ("entity_id", "period", "department", "amount", "version")

#: Key columns that identify a feature row.
KEY_COLUMNS = ("entity_id", "period", "department")

#: Complete output column contract (keys + features), stable across versions.
FEATURE_NAMES = (
    "entity_id",
    "period",
    "department",
    "forecast_line_count",
    "forecast_version_max",
    "forecast_amount_total",
    "forecast_amount_avg",
    "forecast_latest_amount_total",
    "forecast_share_of_entity",
)

#: Money columns that must remain ``Decimal``.
_MONEY_COLUMNS = (
    "forecast_amount_total",
    "forecast_amount_avg",
    "forecast_latest_amount_total",
    "forecast_share_of_entity",
)

#: Sentinel used to neutralise division-by-zero denominators.
_ZERO = Decimal("0")


def build_forecast_features(df: pl.DataFrame) -> pl.DataFrame:
    """Build forecast features per ``(entity_id, period, department)``.

    Aggregates the ``forecast_lines`` source frame into one row per
    ``(entity_id, period, department)``:

    * ``forecast_line_count`` — number of forecast lines;
    * ``forecast_version_max`` — highest ``version`` in the group;
    * ``forecast_amount_total`` — sum of all line amounts (Decimal);
    * ``forecast_amount_avg`` — total ÷ line count (Decimal);
    * ``forecast_latest_amount_total`` — sum of amounts on lines whose
      version equals the group maximum (Decimal);
    * ``forecast_share_of_entity`` — department total ÷ entity-period
      total, ``0`` when the entity total is ``0``.

    Args:
        df: ``forecast_lines`` frame with columns ``entity_id``, ``period``,
            ``department``, ``amount`` (Decimal), ``version`` (int).

    Returns:
        A feature frame with ``FEATURE_NAMES`` columns, sorted by
        ``(entity_id, period, department)``. Money columns are ``Decimal``.

    Raises:
        FeatureStoreError: When required source columns are missing or the
            monetary columns are not ``Decimal``.
    """
    assert_columns(df, SOURCE_COLUMNS)
    assert_money_columns(df, ("amount",))

    latest = df.with_columns(
        pl.col("version").max().over(["entity_id", "period", "department"]).alias("_vmax"),
        pl.when(
            pl.col("version")
            == pl.col("version").max().over(["entity_id", "period", "department"])
        )
        .then(pl.col("amount"))
        .otherwise(_ZERO)
        .alias("_latest_amount"),
    )

    out = (
        latest.group_by(["entity_id", "period", "department"])
        .agg(
            pl.len().cast(pl.Int64).alias("forecast_line_count"),
            pl.col("_vmax").max().alias("forecast_version_max"),
            pl.col("amount").sum().alias("forecast_amount_total"),
            (pl.col("amount").sum() / pl.len()).alias("forecast_amount_avg"),
            pl.col("_latest_amount").sum().alias("forecast_latest_amount_total"),
        )
        .with_columns(
            pl.col("forecast_amount_total")
            .sum()
            .over(["entity_id", "period"])
            .alias("_entity_total")
        )
        .with_columns(
            (
                pl.col("forecast_amount_total")
                / pl.col("_entity_total").replace(_ZERO, None)
            )
            .fill_null(_ZERO)
            .alias("forecast_share_of_entity")
        )
        .drop("_entity_total")
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
    "build_forecast_features",
]
