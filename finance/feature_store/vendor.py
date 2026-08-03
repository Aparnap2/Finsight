"""Vendor-level feature group (source: ``vendor_invoices``).

Produces deterministic, versioned vendor features aggregated per
``(entity_id, period)`` from the ``vendor_invoices`` finance table.

Lineage (source table / column → feature):
    vendor_invoices.vendor_name    → ``vendor_count``
    vendor_invoices (row count)    → ``vendor_invoice_count``
    vendor_invoices.amount         → ``vendor_total_amount``,
                                     ``vendor_avg_invoice_amount``,
                                     ``vendor_paid_amount``,
                                     ``vendor_open_amount``,
                                     ``vendor_concentration_ratio``
    vendor_invoices.status         → ``vendor_paid_amount`` (status == "paid"),
                                     ``vendor_open_amount`` (status != "paid")

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
SOURCE_TABLE = "vendor_invoices"

#: Source columns consumed by :func:`build_vendor_features`.
SOURCE_COLUMNS = ("entity_id", "period", "vendor_name", "amount", "status")

#: Key columns that identify a feature row.
KEY_COLUMNS = ("entity_id", "period")

#: Complete output column contract (keys + features), stable across versions.
FEATURE_NAMES = (
    "entity_id",
    "period",
    "vendor_count",
    "vendor_invoice_count",
    "vendor_total_amount",
    "vendor_avg_invoice_amount",
    "vendor_paid_amount",
    "vendor_open_amount",
    "vendor_concentration_ratio",
)

#: Money columns that must remain ``Decimal``.
_MONEY_COLUMNS = (
    "vendor_total_amount",
    "vendor_avg_invoice_amount",
    "vendor_paid_amount",
    "vendor_open_amount",
    "vendor_concentration_ratio",
)

#: Statuses treated as "open" (not yet paid). Everything else (e.g. "paid")
#: is not included in the open total.
_OPEN_STATUSES = ("draft", "approved", "open")

#: Sentinel used to neutralise division-by-zero denominators.
_ZERO = Decimal("0")


def build_vendor_features(df: pl.DataFrame) -> pl.DataFrame:
    """Build vendor-level features per ``(entity_id, period)``.

    Aggregates the ``vendor_invoices`` source frame into one row per
    ``(entity_id, period)``:

    * ``vendor_count`` — distinct vendor names;
    * ``vendor_invoice_count`` — total invoice rows;
    * ``vendor_total_amount`` — sum of invoice amounts (Decimal);
    * ``vendor_avg_invoice_amount`` — total / invoice count (Decimal);
    * ``vendor_paid_amount`` — sum where ``status == "paid"``;
    * ``vendor_open_amount`` — sum where status is one of
      ``draft``/``approved``/``open``;
    * ``vendor_concentration_ratio`` — largest vendor's spend ÷ period
      total, ``0`` when the total is ``0`` (deterministic denominator
      guard; documented because a zero total is degenerate).

    Args:
        df: ``vendor_invoices`` frame with columns ``entity_id``, ``period``,
            ``vendor_name``, ``amount`` (Decimal), ``status``.

    Returns:
        A feature frame with ``FEATURE_NAMES`` columns, sorted by
        ``(entity_id, period)``. Money columns are ``Decimal``.

    Raises:
        FeatureStoreError: When required source columns are missing or the
            monetary columns are not ``Decimal``.
    """
    assert_columns(df, SOURCE_COLUMNS)
    assert_money_columns(df, ("amount",))

    invoice_counts = df.group_by(["entity_id", "period"]).agg(
        pl.len().cast(pl.Int64).alias("vendor_invoice_count")
    )

    vendor_totals = df.group_by(["entity_id", "period", "vendor_name"]).agg(
        pl.col("amount").sum().alias("_vendor_amount")
    )

    features = vendor_totals.group_by(["entity_id", "period"]).agg(
        pl.len().cast(pl.Int64).alias("vendor_count"),
        pl.col("_vendor_amount").sum().alias("vendor_total_amount"),
        pl.col("_vendor_amount").max().alias("_top_vendor_amount"),
    )

    status_totals = df.group_by(["entity_id", "period"]).agg(
        pl.col("amount")
        .filter(pl.col("status") == "paid")
        .sum()
        .alias("vendor_paid_amount"),
        pl.col("amount")
        .filter(pl.col("status").is_in(_OPEN_STATUSES))
        .sum()
        .alias("vendor_open_amount"),
    )

    out = (
        features.join(invoice_counts, on=["entity_id", "period"], how="left")
        .join(status_totals, on=["entity_id", "period"], how="left")
        .with_columns(
            pl.col("vendor_paid_amount").fill_null(_ZERO),
            pl.col("vendor_open_amount").fill_null(_ZERO),
            (pl.col("vendor_total_amount") / pl.col("vendor_invoice_count"))
            .alias("vendor_avg_invoice_amount"),
            (pl.col("_top_vendor_amount") / pl.col("vendor_total_amount").replace(_ZERO, None))
            .fill_null(_ZERO)
            .alias("vendor_concentration_ratio"),
        )
        .drop("_top_vendor_amount")
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
    "build_vendor_features",
]
