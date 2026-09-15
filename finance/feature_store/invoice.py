"""Invoice-book feature group (source: ``vendor_invoices``).

Produces deterministic, versioned invoice features aggregated per
``(entity_id, period)`` from the ``vendor_invoices`` finance table. Unlike
the ``vendor`` group (vendor behaviour), this group describes the invoice
book itself: totals, distribution, and payment shares.

Lineage (source table / column → feature):
    vendor_invoices (row count)    → ``invoice_count_total``
    vendor_invoices.amount         → ``invoice_amount_total``,
                                     ``invoice_amount_avg``,
                                     ``invoice_amount_max``,
                                     ``invoice_amount_min``,
                                     ``invoice_paid_amount``,
                                     ``invoice_share_paid``,
                                     ``invoice_share_draft``
    vendor_invoices.category       → ``invoice_category_count``
    vendor_invoices.status         → ``invoice_status_count``,
                                     ``invoice_paid_amount`` (status "paid"),
                                     ``invoice_share_draft`` (status "draft")

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

#: Source columns consumed by :func:`build_invoice_features`.
SOURCE_COLUMNS = ("entity_id", "period", "amount", "category", "status")

#: Key columns that identify a feature row.
KEY_COLUMNS = ("entity_id", "period")

#: Complete output column contract (keys + features), stable across versions.
FEATURE_NAMES = (
    "entity_id",
    "period",
    "invoice_count_total",
    "invoice_amount_total",
    "invoice_amount_avg",
    "invoice_amount_max",
    "invoice_amount_min",
    "invoice_category_count",
    "invoice_status_count",
    "invoice_paid_amount",
    "invoice_share_paid",
    "invoice_share_draft",
)

#: Money columns that must remain ``Decimal``.
_MONEY_COLUMNS = (
    "invoice_amount_total",
    "invoice_amount_avg",
    "invoice_amount_max",
    "invoice_amount_min",
    "invoice_paid_amount",
    "invoice_share_paid",
    "invoice_share_draft",
)

#: Sentinel used to neutralise division-by-zero denominators.
_ZERO = Decimal("0")


def build_invoice_features(df: pl.DataFrame) -> pl.DataFrame:
    """Build invoice-book features per ``(entity_id, period)``.

    Aggregates the ``vendor_invoices`` source frame into one row per
    ``(entity_id, period)``:

    * counts: ``invoice_count_total``, ``invoice_category_count`` (distinct
      categories), ``invoice_status_count`` (distinct statuses);
    * monetary: ``invoice_amount_total``, ``invoice_amount_avg`` (total ÷
      count), ``invoice_amount_max``, ``invoice_amount_min``,
      ``invoice_paid_amount`` (sum where ``status == "paid"``);
    * shares: ``invoice_share_paid`` and ``invoice_share_draft`` (paid /
      draft amount ÷ total, ``0`` when the total is ``0``).

    Args:
        df: ``vendor_invoices`` frame with columns ``entity_id``, ``period``,
            ``amount`` (Decimal), ``category``, ``status``.

    Returns:
        A feature frame with ``FEATURE_NAMES`` columns, sorted by
        ``(entity_id, period)``. Money columns are ``Decimal``.

    Raises:
        FeatureStoreError: When required source columns are missing or the
            monetary columns are not ``Decimal``.
    """
    assert_columns(df, SOURCE_COLUMNS)
    assert_money_columns(df, ("amount",))

    paid = df.filter(pl.col("status") == "paid").group_by(["entity_id", "period"]).agg(
        pl.col("amount").sum().alias("invoice_paid_amount")
    )
    draft = df.filter(pl.col("status") == "draft").group_by(["entity_id", "period"]).agg(
        pl.col("amount").sum().alias("_draft_amount")
    )

    out = (
        df.group_by(["entity_id", "period"])
        .agg(
            pl.len().cast(pl.Int64).alias("invoice_count_total"),
            pl.col("amount").sum().alias("invoice_amount_total"),
            pl.col("amount").max().alias("invoice_amount_max"),
            pl.col("amount").min().alias("invoice_amount_min"),
            pl.col("category").n_unique().cast(pl.Int64).alias("invoice_category_count"),
            pl.col("status").n_unique().cast(pl.Int64).alias("invoice_status_count"),
        )
        .join(paid, on=["entity_id", "period"], how="left")
        .join(draft, on=["entity_id", "period"], how="left")
        .with_columns(
            pl.col("invoice_paid_amount").fill_null(_ZERO),
            pl.col("_draft_amount").fill_null(_ZERO),
            (pl.col("invoice_amount_total") / pl.col("invoice_count_total"))
            .alias("invoice_amount_avg"),
            (pl.col("invoice_paid_amount") / pl.col("invoice_amount_total").replace(_ZERO, None))
            .fill_null(_ZERO)
            .alias("invoice_share_paid"),
            (pl.col("_draft_amount") / pl.col("invoice_amount_total").replace(_ZERO, None))
            .fill_null(_ZERO)
            .alias("invoice_share_draft"),
        )
        .drop("_draft_amount")
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
    "build_invoice_features",
]
