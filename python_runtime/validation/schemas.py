"""Pandera DataFrameModel definitions for financial datasets.

These schemas are used by the DualValidator to enforce DataFrame-level
constraints before analytics processing.

Note: amount columns use ``float`` (not ``Decimal``) because Pandera's
Polars integration does not support ``Decimal`` dtypes reliably. The
``MoneyDecimal`` enforcement happens at the Pydantic API boundary.
"""

from __future__ import annotations

import pandera.polars as pa
from pandera.typing.polars import Series


class FinancialDatasetSchema(pa.DataFrameModel):
    """Standard financial dataset: account-level actuals/budget lines.

    Columns:
        account_id: Non-nullable string account identifier.
        period: Non-nullable string period (e.g. "2026-Q1").
        amount: Non-nullable float amount >= 0.
        department: Nullable string department name.
        currency: Nullable string currency code (USD, EUR, GBP, INR, JPY).
    """

    account_id: Series[str] = pa.Field(nullable=False)
    period: Series[str] = pa.Field(nullable=False)
    amount: Series[float] = pa.Field(nullable=False, ge=0)
    department: Series[str] = pa.Field(nullable=True)
    currency: Series[str] = pa.Field(
        nullable=True, isin=["USD", "EUR", "GBP", "INR", "JPY"]
    )


class VarianceInputSchema(pa.DataFrameModel):
    """Schema for variance analysis input rows.

    Columns:
        account_id: Non-nullable string account identifier.
        actual_amount: Non-nullable float actual amount >= 0.
        budget_amount: Non-nullable float budget amount >= 0.
        variance_pct: Nullable float variance percentage.
        department: Nullable string department name.
    """

    account_id: Series[str] = pa.Field(nullable=False)
    actual_amount: Series[float] = pa.Field(nullable=False, ge=0)
    budget_amount: Series[float] = pa.Field(nullable=False, ge=0)
    variance_pct: Series[float] = pa.Field(nullable=True)
    department: Series[str] = pa.Field(nullable=True)


# Schema registry: maps pipeline names to their expected Pandera schema
SCHEMA_REGISTRY: dict[str, type[pa.DataFrameModel]] = {
    "financial_dataset": FinancialDatasetSchema,
    "variance_input": VarianceInputSchema,
}
