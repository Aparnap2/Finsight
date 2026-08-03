"""Tests for python_runtime.transforms.pipeline — TransformStep, TransformPipeline."""

import polars as pl
import pytest

from python_runtime.models import ComputeError
from python_runtime.transforms.builtins import (
    aggregate,
    derive_column,
    filter_rows,
    rename_column,
    select_columns,
)
from python_runtime.transforms.pipeline import TransformPipeline, TransformStep


class TestTransformStep:
    """A single step in the transform pipeline."""

    def test_apply_success(self, sample_dataframe: pl.DataFrame) -> None:
        step = TransformStep("filter", lambda df: df.filter(pl.col("amount") > 0))
        result = step.apply(sample_dataframe)
        assert result.height == 4  # one row with amount=0 removed

    def test_apply_preserves_other_rows(self, sample_dataframe: pl.DataFrame) -> None:
        step = TransformStep(
            "sales_only",
            lambda df: df.filter(pl.col("department") == "Sales"),
        )
        result = step.apply(sample_dataframe)
        assert result.height == 2
        assert result["department"].to_list() == ["Sales", "Sales"]

    def test_name_and_description(self) -> None:
        step = TransformStep(
            "filter_pos",
            lambda df: df,
            description="Filter positive amounts",
        )
        assert step.name == "filter_pos"
        assert step.description == "Filter positive amounts"

    def test_error_wrapping(self) -> None:
        def failing_fn(df: pl.DataFrame) -> pl.DataFrame:
            msg = "Something went wrong"
            raise ValueError(msg)

        step = TransformStep("bad_step", failing_fn)
        with pytest.raises(ComputeError) as excinfo:
            step.apply(pl.DataFrame({"a": [1]}))
        assert excinfo.value.code == "TRANSFORM_ERROR"
        assert "bad_step" in excinfo.value.message
        assert "Something went wrong" in excinfo.value.message


class TestTransformPipeline:
    """A sequence of transform steps applied in order."""

    def test_empty_pipeline(self, sample_dataframe: pl.DataFrame) -> None:
        pipeline = TransformPipeline()
        result = pipeline.apply(sample_dataframe)
        assert result.height == sample_dataframe.height
        assert result.columns == sample_dataframe.columns

    def test_single_step(self, sample_dataframe: pl.DataFrame) -> None:
        pipeline = TransformPipeline()
        pipeline.add_step(
            TransformStep("filter_sales", lambda df: df.filter(pl.col("department") == "Sales"))
        )
        result = pipeline.apply(sample_dataframe)
        assert result.height == 2
        assert result["department"].to_list() == ["Sales", "Sales"]

    def test_multiple_steps(self, sample_dataframe: pl.DataFrame) -> None:
        """Chain: select columns, then filter rows."""
        pipeline = TransformPipeline()
        pipeline.add_step(
            TransformStep(
                "select_cols",
                lambda df: df.select(["account_id", "amount", "department"]),
            )
        )
        pipeline.add_step(
            TransformStep(
                "filter_eng",
                lambda df: df.filter(pl.col("department") == "Engineering"),
            )
        )
        result = pipeline.apply(sample_dataframe)
        assert result.columns == ["account_id", "amount", "department"]
        assert result.height == 2
        assert result["department"].to_list() == ["Engineering", "Engineering"]

    def test_fluent_api(self, sample_dataframe: pl.DataFrame) -> None:
        pipeline = (
            TransformPipeline()
            .add_step(TransformStep("s1", lambda df: df.filter(pl.col("amount") > 0)))
            .add_step(TransformStep("s2", lambda df: df.select(["account_id"])))
        )
        result = pipeline.apply(sample_dataframe)
        assert result.height == 4
        assert result.columns == ["account_id"]

    def test_steps_property(self) -> None:
        s1 = TransformStep("s1", lambda df: df)
        s2 = TransformStep("s2", lambda df: df)
        pipeline = TransformPipeline([s1, s2])
        assert len(pipeline.steps) == 2
        assert pipeline.steps[0].name == "s1"

    def test_steps_property_returns_copy(self) -> None:
        s1 = TransformStep("s1", lambda df: df)
        pipeline = TransformPipeline([s1])
        steps = pipeline.steps
        steps.clear()
        assert len(pipeline.steps) == 1  # original unchanged

    def test_error_propagation(self, sample_dataframe: pl.DataFrame) -> None:
        def failing_fn(df: pl.DataFrame) -> pl.DataFrame:
            msg = "bad"
            raise RuntimeError(msg)

        pipeline = TransformPipeline()
        pipeline.add_step(TransformStep("ok", lambda df: df))
        pipeline.add_step(TransformStep("fail", failing_fn))
        with pytest.raises(ComputeError) as excinfo:
            pipeline.apply(sample_dataframe)
        assert excinfo.value.code == "TRANSFORM_ERROR"
        assert "fail" in excinfo.value.message


class TestIntegrationWithBuiltins:
    """Integration tests combining pipeline with built-in transforms."""

    def test_filter_then_select(self, sample_dataframe: pl.DataFrame) -> None:
        pipeline = (
            TransformPipeline()
            .add_step(
                TransformStep(
                    "filter_sales",
                    lambda df: filter_rows(df, "pl.col('department') == 'Sales'"),
                )
            )
            .add_step(
                TransformStep(
                    "select_id_amount",
                    lambda df: select_columns(df, ["account_id", "amount"]),
                )
            )
        )
        result = pipeline.apply(sample_dataframe)
        assert result.columns == ["account_id", "amount"]
        assert result.height == 2

    def test_rename_then_derive(self, sample_dataframe: pl.DataFrame) -> None:
        pipeline = (
            TransformPipeline()
            .add_step(
                TransformStep(
                    "rename_dept",
                    lambda df: rename_column(df, {"department": "dept"}),
                )
            )
            .add_step(
                TransformStep(
                    "derive_double",
                    lambda df: derive_column(df, "double_amount", "pl.col('amount') * 2"),
                )
            )
        )
        result = pipeline.apply(sample_dataframe)
        assert "dept" in result.columns
        assert "department" not in result.columns
        assert "double_amount" in result.columns
        assert result["double_amount"].to_list() == [2000.0, 5000.0, 0.0, 1000.0, 15000.0]

    def test_aggregate(self, sample_dataframe: pl.DataFrame) -> None:
        pipeline = TransformPipeline()
        pipeline.add_step(
            TransformStep(
                "aggregate_dept",
                lambda df: aggregate(df, ["department"], {"amount": "sum"}),
            )
        )
        result = pipeline.apply(sample_dataframe)
        assert "amount_sum" in result.columns
        assert result.height == 3  # Sales, Engineering, Marketing
        # Sales total = 1000 + 0 = 1000
        sales_row = result.filter(pl.col("department") == "Sales")
        assert sales_row["amount_sum"].to_list() == [1000.0]
