"""Canonical shared module for the deterministic feature store.

This module is the single source of truth for cross-cutting concerns of the
feature store (``finance/feature_store/``):

* the package-level exception (:class:`FeatureStoreError`);
* shared monetary-dtype policy: every monetary column in a feature frame must
  be a ``polars`` ``Decimal`` column (``decimal.Decimal`` is the only money
  representation — never ``float``);
* deterministic frame-shape guards (:func:`assert_columns`);
* pandera schemas that validate the *structural* columns of each feature
  group's output frame.

Why structural-only pandera schemas?
    pandera's polars backend cannot reliably validate ``Decimal`` columns: it
    expects ``Decimal(precision=28, scale=0)`` while the feature store
    produces ``Decimal(precision=38, scale=2)`` (the same limitation is
    documented in ``python_runtime/validation/schemas.py``). Monetary columns
    are therefore checked with :func:`assert_money_columns`, and the complete
    column contract of every group is declared in that group's module as
    ``FEATURE_NAMES`` (validated in ``tests/unit/test_finance/``).

This module must stay free of I/O and free of LLM calls — it is pure,
deterministic compute support.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pandera.polars as pa
import polars as pl
from pandera.typing.polars import Series

#: Precision used by every monetary column produced by the feature store.
MONEY_PRECISION = 38

#: Scale used by every monetary column produced by the feature store (2dp).
MONEY_SCALE = 2

#: Canonical dtype for feature-store money columns.
MONEY_DTYPE: Any = pl.Decimal(MONEY_PRECISION, MONEY_SCALE)

#: Feature versions are semantic ``MAJOR.MINOR.PATCH`` strings.
FEATURE_VERSION_FORMAT = "MAJOR.MINOR.PATCH"


class FeatureStoreError(Exception):
    """Raised when a feature group cannot be built or validated.

    This is the single exception type the feature store raises for
    malformed inputs, missing columns, non-Decimal money columns, and
    registry lookups that fail (see :class:`finance.feature_store.registry
    .FeatureLookupError` for the lookup-specific subclass).
    """


def assert_columns(df: pl.DataFrame, required: Sequence[str]) -> None:
    """Raise :class:`FeatureStoreError` if any of ``required`` is missing.

    Args:
        df: The frame to check.
        required: Column names that must be present.

    Raises:
        FeatureStoreError: When at least one required column is absent.
    """
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise FeatureStoreError(
            f"missing required column(s): {', '.join(missing)}; "
            f"present: {', '.join(sorted(df.columns)) or '<none>'}"
        )


def assert_money_columns(df: pl.DataFrame, columns: Sequence[str]) -> None:
    """Raise :class:`FeatureStoreError` if any monetary column is not Decimal.

    Money is represented exclusively as ``decimal.Decimal`` — never
    ``float``. Each named column must resolve to a ``polars`` ``Decimal``
    dtype.

    Args:
        df: The frame to check.
        columns: Monetary column names that must be ``Decimal`` typed.

    Raises:
        FeatureStoreError: When a column is absent or is not a Decimal dtype.
    """
    for col in columns:
        if col not in df.columns:
            raise FeatureStoreError(f"money column missing: {col!r}")
        dtype = df.schema[col]
        if not isinstance(dtype, pl.Decimal):
            raise FeatureStoreError(
                f"money column {col!r} has dtype {dtype}, expected Decimal "
                f"(precision={MONEY_PRECISION}, scale={MONEY_SCALE})"
            )


# =============================================================================
# Pandera structural schemas for feature-group output frames
# =============================================================================


class FeatureFrameSchema(pa.DataFrameModel):
    """Structural columns shared by every feature-group output frame.

    Every group produces one row per ``(entity_id, period)`` (plus, for
    departmental groups, ``department``). Monetary feature columns are not
    declared here — pandera's polars backend cannot validate ``Decimal`` —
    they are enforced by :func:`assert_money_columns` and documented per
    group in ``FEATURE_NAMES``.
    """

    entity_id: Series[str] = pa.Field(nullable=False)
    period: Series[str] = pa.Field(nullable=False)


class VendorFeaturesSchema(FeatureFrameSchema):
    """Structural schema for the ``vendor`` feature group (vendor_invoices).

    Adds the integer vendor-count features; monetary features
    (``vendor_total_amount``, ``vendor_avg_invoice_amount``,
    ``vendor_paid_amount``, ``vendor_open_amount``,
    ``vendor_concentration_ratio``) are enforced via
    :func:`assert_money_columns`.
    """

    vendor_count: Series[int] = pa.Field(nullable=False, ge=0)
    vendor_invoice_count: Series[int] = pa.Field(nullable=False, ge=0)


class InvoiceFeaturesSchema(FeatureFrameSchema):
    """Structural schema for the ``invoice`` feature group (vendor_invoices).

    Adds integer invoice-book features; monetary features are enforced via
    :func:`assert_money_columns`.
    """

    invoice_count_total: Series[int] = pa.Field(nullable=False, ge=0)
    invoice_category_count: Series[int] = pa.Field(nullable=False, ge=0)
    invoice_status_count: Series[int] = pa.Field(nullable=False, ge=0)


class CashflowFeaturesSchema(FeatureFrameSchema):
    """Structural schema for the ``cashflow`` feature group (actuals).

    The cashflow group is entirely monetary; all columns are enforced via
    :func:`assert_money_columns`.
    """


class DepartmentFeaturesSchema(FeatureFrameSchema):
    """Structural schema for the ``department`` feature group (headcount_data).

    Adds the ``department`` key column and integer headcount features;
    monetary features (``dept_total_compensation``,
    ``dept_comp_per_head``) and the ``headcount_turnover_rate`` ratio are
    enforced via :func:`assert_money_columns`.
    """

    department: Series[str] = pa.Field(nullable=False)
    headcount_total: Series[int] = pa.Field(nullable=False, ge=0)
    headcount_new_hires: Series[int] = pa.Field(nullable=False, ge=0)
    headcount_departures: Series[int] = pa.Field(nullable=False, ge=0)
    headcount_net_change: Series[int] = pa.Field(nullable=False)


class ForecastFeaturesSchema(FeatureFrameSchema):
    """Structural schema for the ``forecast`` feature group (forecast_lines).

    Adds the ``department`` key column and integer forecast features;
    monetary features are enforced via :func:`assert_money_columns`.
    """

    department: Series[str] = pa.Field(nullable=False)
    forecast_line_count: Series[int] = pa.Field(nullable=False, ge=0)
    forecast_version_max: Series[int] = pa.Field(nullable=False, ge=1)


class AnomalyFeaturesSchema(FeatureFrameSchema):
    """Structural schema for the ``anomaly`` feature group (actuals x budget).

    Adds the ``account_id`` key column, the nullable ``department`` column,
    and the boolean anomaly flags; monetary features are enforced via
    :func:`assert_money_columns`.
    """

    account_id: Series[str] = pa.Field(nullable=False)
    department: Series[str] = pa.Field(nullable=True)
    anomaly_flag_spike: Series[bool] = pa.Field(nullable=False)
    anomaly_flag_deficit: Series[bool] = pa.Field(nullable=False)
    anomaly_flag_material: Series[bool] = pa.Field(nullable=False)


#: Registry of structural output schemas keyed by feature group name.
FEATURE_GROUP_SCHEMAS: dict[str, type[pa.DataFrameModel]] = {
    "vendor": VendorFeaturesSchema,
    "invoice": InvoiceFeaturesSchema,
    "cashflow": CashflowFeaturesSchema,
    "department": DepartmentFeaturesSchema,
    "forecast": ForecastFeaturesSchema,
    "anomaly": AnomalyFeaturesSchema,
}


def validate_feature_frame(group: str, df: pl.DataFrame) -> pl.DataFrame:
    """Validate a built feature frame for ``group`` and return it unchanged.

    Applies the group's pandera structural schema plus the money-column
    contract. Unknown groups raise :class:`FeatureStoreError`; invalid
    frames raise pandera's ``SchemaError``.

    Args:
        group: Feature group key (must exist in ``FEATURE_GROUP_SCHEMAS``).
        df: The frame produced by the group's builder.

    Returns:
        The validated frame (identity).

    Raises:
        FeatureStoreError: When the group is unknown.
    """
    if group not in FEATURE_GROUP_SCHEMAS:
        raise FeatureStoreError(f"no output schema registered for feature group {group!r}")
    schema = FEATURE_GROUP_SCHEMAS[group]
    schema.validate(df, lazy=True)  # raises SchemaError on violation
    return df


__all__ = [
    "FEATURE_GROUP_SCHEMAS",
    "FEATURE_VERSION_FORMAT",
    "MONEY_DTYPE",
    "MONEY_PRECISION",
    "MONEY_SCALE",
    "AnomalyFeaturesSchema",
    "CashflowFeaturesSchema",
    "DepartmentFeaturesSchema",
    "FeatureFrameSchema",
    "FeatureStoreError",
    "ForecastFeaturesSchema",
    "InvoiceFeaturesSchema",
    "VendorFeaturesSchema",
    "assert_columns",
    "assert_money_columns",
    "validate_feature_frame",
]
