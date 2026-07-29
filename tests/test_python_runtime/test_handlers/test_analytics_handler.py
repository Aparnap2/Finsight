"""Tests for python_runtime.handlers.analytics_handler — AnalyticsHandler."""

import polars as pl
import pytest

from python_runtime.handlers.analytics_handler import AnalyticsHandler
from python_runtime.importers.protocol import Dataset
from python_runtime.models import ComputeError, Job


class TestAnalyticsHandler:
    """AnalyticsHandler — import -> validate -> DuckDB query -> result Dataset."""

    def setup_method(self) -> None:
        self.handler = AnalyticsHandler()

    def test_csv_import_and_query(self, sample_csv_path: str) -> None:
        """Import CSV, run SQL aggregation, get result."""
        job = Job(
            tenant_id="CF001",
            pipeline="analytics",
            params={
                "source_type": "csv",
                "source_uri": sample_csv_path,
                "query": "SELECT department, SUM(amount) as total FROM data GROUP BY department",
                "validation_schema": "financial_dataset",
            },
        )
        result = self.handler.handle(job)
        assert isinstance(result, Dataset)
        assert result.source == "duckdb"
        assert result.row_count == 3  # Sales, Engineering, Marketing
        assert "department" in result.column_names

        # Verify aggregation values
        sales_row = result.data.filter(pl.col("department") == "Sales")
        assert sales_row["total"].to_list() == [1000.0]

    def test_simple_select(self, sample_csv_path: str) -> None:
        job = Job(
            tenant_id="T1",
            pipeline="analytics",
            params={
                "source_type": "csv",
                "source_uri": sample_csv_path,
                "query": "SELECT account_id, amount FROM data WHERE amount > 1000",
            },
        )
        result = self.handler.handle(job)
        assert result.row_count == 2  # A101 (2500), A104 (7500)
        assert result.column_names == ["account_id", "amount"]

    def test_missing_source_uri_raises_error(self) -> None:
        job = Job(
            tenant_id="T1",
            pipeline="analytics",
            params={
                "source_type": "csv",
                "source_uri": "",
                "query": "SELECT 1",
            },
        )
        with pytest.raises(ComputeError) as excinfo:
            self.handler.handle(job)
        assert excinfo.value.code == "IMPORT_ERROR"
        assert "source_uri" in excinfo.value.message

    def test_missing_query_raises_error(self, sample_csv_path: str) -> None:
        job = Job(
            tenant_id="T1",
            pipeline="analytics",
            params={
                "source_type": "csv",
                "source_uri": sample_csv_path,
                "query": "",
            },
        )
        with pytest.raises(ComputeError) as excinfo:
            self.handler.handle(job)
        assert excinfo.value.code == "ANALYTICS_ERROR"
        assert "query" in excinfo.value.message

    def test_invalid_sql_raises_error(self, sample_csv_path: str) -> None:
        job = Job(
            tenant_id="T1",
            pipeline="analytics",
            params={
                "source_type": "csv",
                "source_uri": sample_csv_path,
                "query": "SELECT INVALID SQL",
            },
        )
        with pytest.raises(ComputeError) as excinfo:
            self.handler.handle(job)
        assert excinfo.value.code == "ANALYTICS_ERROR"
        assert "DuckDB query failed" in excinfo.value.message

    def test_missing_csv_file_raises_import_error(self) -> None:
        job = Job(
            tenant_id="T1",
            pipeline="analytics",
            params={
                "source_type": "csv",
                "source_uri": "/nonexistent/file.csv",
                "query": "SELECT 1",
            },
        )
        with pytest.raises(ComputeError) as excinfo:
            self.handler.handle(job)
        # FileNotFoundError gets caught by the handler -> HANDLER_ERROR
        assert excinfo.value.code in ("IMPORT_ERROR", "HANDLER_ERROR")

    def test_validation_schema_not_in_registry_skips_validation(
        self, sample_csv_path: str
    ) -> None:
        """If schema name is not in SCHEMA_REGISTRY, validation is skipped (graceful)."""
        job = Job(
            tenant_id="T1",
            pipeline="analytics",
            params={
                "source_type": "csv",
                "source_uri": sample_csv_path,
                "query": "SELECT COUNT(*) as cnt FROM data",
                "validation_schema": "nonexistent_schema",
            },
        )
        result = self.handler.handle(job)
        assert result.row_count == 1

    def test_result_metadata(self, sample_csv_path: str) -> None:
        job = Job(
            tenant_id="T1",
            pipeline="analytics",
            params={
                "source_type": "csv",
                "source_uri": sample_csv_path,
                "query": "SELECT 1 as val",
            },
        )
        result = self.handler.handle(job)
        assert result.metadata["source_query"] == "SELECT 1 as val"
        assert result.metadata["source_pipeline"] == "analytics"

    def test_result_is_dataset(self, sample_csv_path: str) -> None:
        job = Job(
            tenant_id="T1",
            pipeline="analytics",
            params={
                "source_type": "csv",
                "source_uri": sample_csv_path,
                "query": "SELECT * FROM data",
            },
        )
        result = self.handler.handle(job)
        assert isinstance(result, Dataset)
        assert result.source == "duckdb"
