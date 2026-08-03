"""Cash-flow feature group (source: ``actuals``).

Produces deterministic, versioned cash-flow features aggregated per
``(entity_id, period)`` from the ``actuals`` finance table, classifying
account ids by their leading digit (the project's chart-of-accounts
convention, shared with ``finance/variance_engine/materiality.py``:
``4*`` revenue / inflows, ``5*`` COGS and ``6*`` OpEx / outflows).

Lineage (source table / column → feature):
    actuals.account_id             → inflow/outflow classification
                                     (``4*`` inflow; ``5*``, ``6*`` outflow)
    actuals.amount                 → ``cashflow_inflow_amount``,
                                     ``cashflow_outflow_amount``,
                                     ``cashflow_net_amount``,
                                     ``cashflow_coverage_ratio``

Note: this is a *deterministic proxy* for operating cash flow derived from
actuals; it is not a statement of cash flows. The builder is pure: it
accepts a polars DataFrame and returns a polars DataFrame. All monetary
columns are ``Decimal`` (never ``float``).
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
SOURCE_TABLE = "actuals"

#: Source columns consumed by :func:`build_cashflow_features`.
SOURCE_COLUMNS = ("entity_id", "period", "account_id", "amount")

#: Key columns that identify a feature row.
KEY_COLUMNS = ("entity_id", "period")

#: Complete output column contract (keys + features), stable across versions.
FEATURE_NAMES = (
    "entity_id",
    "period",
    "cashflow_inflow_amount",
    "cashflow_outflow_amount",
    "cashflow_net_amount",
    "cashflow_coverage_ratio",
)

#: Money columns that must remain ``Decimal``.
_MONEY_COLUMNS = (
    "cashflow_inflow_amount",
    "cashflow_outflow_amount",
    "cashflow_net_amount",
    "cashflow_coverage_ratio",
)

#: Sentinel used to neutralise division-by-zero denominators.
_ZERO = Decimal("0")


def build_cashflow_features(df: pl.DataFrame) -> pl.DataFrame:
    """Build cash-flow proxy features per ``(entity_id, period)``.

    Aggregates the ``actuals`` source frame into one row per
    ``(entity_id, period)``:

    * ``cashflow_inflow_amount`` — sum of amounts on ``4*`` accounts
      (revenue-class inflows);
    * ``cashflow_outflow_amount`` — sum of the *absolute* amounts on
      ``5*`` / ``6*`` accounts (COGS / OpEx outflows);
    * ``cashflow_net_amount`` — inflow − outflow;
    * ``cashflow_coverage_ratio`` — inflow ÷ outflow, ``0`` when outflow is
      ``0`` (deterministic denominator guard; a zero outflow is documented
      as degenerate).

    Args:
        df: ``actuals`` frame with columns ``entity_id``, ``period``,
            ``account_id``, ``amount`` (Decimal).

    Returns:
        A feature frame with ``FEATURE_NAMES`` columns, sorted by
        ``(entity_id, period)``. Money columns are ``Decimal``.

    Raises:
        FeatureStoreError: When required source columns are missing or the
            monetary columns are not ``Decimal``.
    """
    assert_columns(df, SOURCE_COLUMNS)
    assert_money_columns(df, ("amount",))

    inflow = (
        df.filter(pl.col("account_id").str.starts_with("4"))
        .group_by(["entity_id", "period"])
        .agg(pl.col("amount").sum().alias("cashflow_inflow_amount"))
    )
    outflow = (
        df.filter(
            pl.col("account_id").str.starts_with("5")
            | pl.col("account_id").str.starts_with("6")
        )
        .group_by(["entity_id", "period"])
        .agg(pl.col("amount").abs().sum().alias("cashflow_outflow_amount"))
    )

    out = (
        df.select(["entity_id", "period"])
        .unique()
        .join(inflow, on=["entity_id", "period"], how="left")
        .join(outflow, on=["entity_id", "period"], how="left")
        .with_columns(
            pl.col("cashflow_inflow_amount").fill_null(_ZERO),
            pl.col("cashflow_outflow_amount").fill_null(_ZERO),
        )
        .with_columns(
            (pl.col("cashflow_inflow_amount") - pl.col("cashflow_outflow_amount")).alias(
                "cashflow_net_amount"
            ),
            (
                pl.col("cashflow_inflow_amount")
                / pl.col("cashflow_outflow_amount").replace(_ZERO, None)
            )
            .fill_null(_ZERO)
            .alias("cashflow_coverage_ratio"),
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
    "build_cashflow_features",
]
