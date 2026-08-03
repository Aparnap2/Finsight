"""Tests for python_runtime.exporters — JSONExporter, CSVExporter."""

import json
from uuid import uuid4

import polars as pl

from python_runtime.exporters.csv_exporter import CSVExporter
from python_runtime.exporters.json_exporter import JSONExporter
from python_runtime.exporters.protocol import Artifact, Exporter


class TestJSONExporter:
    """JSONExporter — serializes DataFrames as JSON arrays."""

    def setup_method(self) -> None:
        self.exporter = JSONExporter()
        self.job_id = uuid4()

    def test_format_and_content_type(self) -> None:
        assert self.exporter.format == "json"
        assert self.exporter.content_type == "application/json"

    def test_is_exporter_protocol(self) -> None:
        assert isinstance(self.exporter, Exporter)

    def test_export_returns_artifact(self, sample_dataframe: pl.DataFrame) -> None:
        artifact = self.exporter.export(sample_dataframe, self.job_id)
        assert isinstance(artifact, Artifact)
        assert artifact.job_id == self.job_id
        assert artifact.format == "json"
        assert artifact.content_type == "application/json"

    def test_payload_is_valid_json(self, sample_dataframe: pl.DataFrame) -> None:
        artifact = self.exporter.export(sample_dataframe, self.job_id)
        assert artifact.payload is not None
        parsed = json.loads(artifact.payload)
        assert isinstance(parsed, list)
        assert len(parsed) == sample_dataframe.height

    def test_payload_contains_all_rows(self, sample_dataframe: pl.DataFrame) -> None:
        artifact = self.exporter.export(sample_dataframe, self.job_id)
        parsed = json.loads(artifact.payload)
        assert len(parsed) == 5

    def test_size_bytes(self, sample_dataframe: pl.DataFrame) -> None:
        artifact = self.exporter.export(sample_dataframe, self.job_id)
        assert artifact.size_bytes > 0
        expected = len(artifact.payload.encode("utf-8")) if artifact.payload else 0
        assert artifact.size_bytes == expected

    def test_round_trip(self, sample_dataframe: pl.DataFrame) -> None:
        """Export JSON, then re-import and verify columns match."""
        artifact = self.exporter.export(sample_dataframe, self.job_id)
        parsed = json.loads(artifact.payload)
        reimported = pl.DataFrame(parsed)
        assert reimported.columns == sample_dataframe.columns
        assert reimported.height == sample_dataframe.height

    def test_empty_dataframe(self) -> None:
        df = pl.DataFrame({"a": [], "b": []})
        artifact = self.exporter.export(df, self.job_id)
        parsed = json.loads(artifact.payload)
        assert len(parsed) == 0

    def test_artifact_has_id(self, sample_dataframe: pl.DataFrame) -> None:
        artifact = self.exporter.export(sample_dataframe, self.job_id)
        assert artifact.id is not None


class TestCSVExporter:
    """CSVExporter — serializes DataFrames as CSV."""

    def setup_method(self) -> None:
        self.exporter = CSVExporter()
        self.job_id = uuid4()

    def test_format_and_content_type(self) -> None:
        assert self.exporter.format == "csv"
        assert self.exporter.content_type == "text/csv"

    def test_is_exporter_protocol(self) -> None:
        assert isinstance(self.exporter, Exporter)

    def test_export_returns_artifact(self, sample_dataframe: pl.DataFrame) -> None:
        artifact = self.exporter.export(sample_dataframe, self.job_id)
        assert isinstance(artifact, Artifact)
        assert artifact.job_id == self.job_id
        assert artifact.format == "csv"

    def test_payload_is_csv(self, sample_dataframe: pl.DataFrame) -> None:
        artifact = self.exporter.export(sample_dataframe, self.job_id)
        assert artifact.payload is not None
        assert artifact.payload.startswith("account_id,period,amount,department,currency")

    def test_csv_has_header(self, sample_dataframe: pl.DataFrame) -> None:
        artifact = self.exporter.export(sample_dataframe, self.job_id)
        lines = artifact.payload.strip().split("\n")
        assert lines[0] == "account_id,period,amount,department,currency"
        assert len(lines) == 6  # header + 5 data rows

    def test_size_bytes(self, sample_dataframe: pl.DataFrame) -> None:
        artifact = self.exporter.export(sample_dataframe, self.job_id)
        assert artifact.size_bytes > 0

    def test_round_trip(self, sample_dataframe: pl.DataFrame) -> None:
        """Export CSV, then re-import and verify columns."""
        artifact = self.exporter.export(sample_dataframe, self.job_id)
        reimported = pl.read_csv(artifact.payload.encode())
        assert reimported.columns == sample_dataframe.columns
        assert reimported.height == sample_dataframe.height

    def test_empty_dataframe(self) -> None:
        df = pl.DataFrame({"a": [], "b": []})
        artifact = self.exporter.export(df, self.job_id)
        assert artifact.payload == "a,b\n"

    def test_artifact_has_id(self, sample_dataframe: pl.DataFrame) -> None:
        artifact = self.exporter.export(sample_dataframe, self.job_id)
        assert artifact.id is not None
