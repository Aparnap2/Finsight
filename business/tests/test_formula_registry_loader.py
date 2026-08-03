"""Tests for the formula registry loader.

Covers loading ``registry.yaml``, schema validation, and record
lookup helpers.
"""

from __future__ import annotations

import pytest

from business.formula_registry.loader import (
    RegistryFileError,
    load_records,
    record_by_id,
)


class TestLoadRecords:
    """Tests for :func:`load_records`."""

    def test_loads_74_records(self) -> None:
        """The shipped registry contains all 74 formulas."""
        records = load_records()
        assert len(records) == 74

    def test_records_have_elevated_fields(self) -> None:
        """Records carry the elevated registry-v1 fields."""
        records = load_records()
        sample = next(r for r in records if r["id"] == "gross_margin")
        assert sample["category"] == "Profitability"
        assert "inputs" in sample
        assert "output" in sample
        assert "references" in sample
        assert "status" in sample

    def test_missing_file_raises(self, tmp_path: pytest.TempPathFactory) -> None:
        """A missing file raises RegistryFileError."""
        with pytest.raises(RegistryFileError):
            load_records(tmp_path / "nope.yaml")

    def test_wrong_schema_raises(self, tmp_path: pytest.TempPathFactory) -> None:
        """A file with the wrong schema raises RegistryFileError."""
        target = tmp_path / "registry.yaml"
        target.write_text(
            "schema: finsight/other-schema\nversion: 1.0.0\nformulas: []\n",
            encoding="utf-8",
        )
        with pytest.raises(RegistryFileError):
            load_records(target)


class TestRecordById:
    """Tests for :func:`record_by_id`."""

    def test_found(self) -> None:
        """Lookup by id returns the matching record."""
        records = load_records()
        record = record_by_id(records, "gross_margin")
        assert record["id"] == "gross_margin"

    def test_missing_raises(self) -> None:
        """Lookup of an unknown id raises KeyError."""
        records = load_records()
        with pytest.raises(KeyError):
            record_by_id(records, "not_a_real_formula")
