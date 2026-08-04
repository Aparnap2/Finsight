"""Tests for python_runtime.importers.csv_importer — CSVImporter."""

from pathlib import Path

import polars as pl
import pytest

from python_runtime.importers.csv_importer import CSVImporter
from python_runtime.importers.protocol import Dataset, Importer


class TestCSVImporter:
    """CSVImporter — imports CSV files as Datasets."""

    def setup_method(self) -> None:
        self.importer = CSVImporter()

    def test_source_type(self) -> None:
        assert self.importer.source_type == "csv"

    def test_is_importer_protocol(self) -> None:
        assert isinstance(self.importer, Importer)

    def test_import_valid_csv(self, sample_csv_path: str) -> None:
        dataset = self.importer.import_data(sample_csv_path)
        assert isinstance(dataset, Dataset)
        assert dataset.source == "csv"
        assert dataset.row_count == 5
        assert "account_id" in dataset.column_names
        assert "amount" in dataset.column_names

    def test_import_data_types(self, sample_csv_path: str) -> None:
        dataset = self.importer.import_data(sample_csv_path)
        # amount column should be float64 by default (Polars inference)
        assert dataset.data.schema["amount"] == pl.Float64
        assert dataset.data.schema["account_id"] == pl.Utf8

    def test_import_preserves_values(self, sample_csv_path: str) -> None:
        dataset = self.importer.import_data(sample_csv_path)
        amounts = dataset.data["amount"].to_list()
        assert amounts == [1000.0, 2500.0, 0.0, 500.0, 7500.0]

    def test_import_with_has_header_false(
        self, tmp_path: Path, sample_dataframe: pl.DataFrame
    ) -> None:
        """CSV without header row — column names become default."""
        path = tmp_path / "no_header.csv"
        sample_dataframe.write_csv(path, include_header=False)
        dataset = self.importer.import_data(str(path), has_header=False)
        assert dataset.row_count == 5
        # Without header, columns get auto names like column_1, column_2, ...
        assert "column_1" in dataset.column_names or len(dataset.column_names) == 5

    def test_hash_stability(self, sample_csv_path: str) -> None:
        """Same file produces the same hash."""
        ds1 = self.importer.import_data(sample_csv_path)
        ds2 = self.importer.import_data(sample_csv_path)
        assert ds1.hash == ds2.hash

    def test_metadata_includes_path_and_size(self, sample_csv_path: str) -> None:
        dataset = self.importer.import_data(sample_csv_path)
        assert "path" in dataset.metadata
        assert "file_size_bytes" in dataset.metadata
        assert dataset.metadata["file_size_bytes"] > 0

    def test_missing_file_raises_error(self) -> None:
        with pytest.raises(FileNotFoundError, match="not found"):
            self.importer.import_data("/nonexistent/path.csv")

    def test_empty_csv(self, tmp_path: Path) -> None:
        """Empty CSV (header only) produces 0-row dataset."""
        path = tmp_path / "empty.csv"
        with open(path, "w") as f:
            f.write("col1,col2,col3\n")
        dataset = self.importer.import_data(str(path))
        assert dataset.row_count == 0
        assert dataset.column_names == ["col1", "col2", "col3"]

    def test_infer_schema_length_parameter(self, sample_csv_path: str) -> None:
        """infer_schema_length can be customized."""
        dataset = self.importer.import_data(sample_csv_path, infer_schema_length=10)
        assert dataset.row_count == 5

    def test_kwargs_passed_to_polars(self, sample_csv_path: str) -> None:
        """Additional kwargs are passed through to pl.read_csv."""
        dataset = self.importer.import_data(sample_csv_path, null_values="N/A")
        assert dataset.row_count == 5
