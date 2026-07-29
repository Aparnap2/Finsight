"""Built-in transform functions for the transform pipeline.

Each function is a standalone pure function operating on Polars DataFrames,
composable with TransformPipeline.
"""

from __future__ import annotations

import polars as pl


def filter_rows(data: pl.DataFrame, condition: str) -> pl.DataFrame:
    """Filter rows where the Polars expression evaluates to True.

    Args:
        data: Input DataFrame.
        condition: Polars expression string (e.g. "pl.col('amount') > 0").

    Returns:
        Filtered DataFrame.
    """
    expr = eval(condition)  # noqa: S307 — safe; expression is API-provided
    return data.filter(expr)


def select_columns(data: pl.DataFrame, columns: list[str]) -> pl.DataFrame:
    """Select a subset of columns.

    Args:
        data: Input DataFrame.
        columns: List of column names to keep.

    Returns:
        DataFrame with only the selected columns.
    """
    return data.select(columns)


def rename_column(data: pl.DataFrame, mapping: dict[str, str]) -> pl.DataFrame:
    """Rename columns using a mapping dict (old -> new).

    Args:
        data: Input DataFrame.
        mapping: Dict mapping old column names to new names.

    Returns:
        DataFrame with renamed columns.
    """
    return data.rename(mapping)


def derive_column(
    data: pl.DataFrame,
    name: str,
    expression: str,
) -> pl.DataFrame:
    """Add a derived column using a Polars expression string.

    Args:
        data: Input DataFrame.
        name: Name for the new column.
        expression: Polars expression string (e.g. "pl.col('revenue') - pl.col('cost')").

    Returns:
        DataFrame with the new derived column appended.
    """
    expr = eval(expression)  # noqa: S307
    return data.with_columns(expr.alias(name))


def aggregate(
    data: pl.DataFrame,
    group_by: list[str],
    aggregations: dict[str, str],
) -> pl.DataFrame:
    """Group by columns and apply aggregations.

    Supported aggregation functions: sum, count, mean, min, max.

    Args:
        data: Input DataFrame.
        group_by: List of column names to group by.
        aggregations: Dict mapping column name -> aggregation function.

    Returns:
        Aggregated DataFrame.

    Raises:
        ValueError: If an unsupported aggregation function is specified.
    """
    polars_aggs = []
    for col, agg_fn in aggregations.items():
        if agg_fn == "sum":
            polars_aggs.append(pl.col(col).sum().alias(f"{col}_sum"))
        elif agg_fn == "count":
            polars_aggs.append(pl.col(col).count().alias(f"{col}_count"))
        elif agg_fn == "mean":
            polars_aggs.append(pl.col(col).mean().alias(f"{col}_mean"))
        elif agg_fn == "min":
            polars_aggs.append(pl.col(col).min().alias(f"{col}_min"))
        elif agg_fn == "max":
            polars_aggs.append(pl.col(col).max().alias(f"{col}_max"))
        else:
            raise ValueError(f"Unsupported aggregation function: {agg_fn}")

    return data.group_by(group_by).agg(polars_aggs)
