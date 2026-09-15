"""Tests for the versioned data contracts.

Covers the formula registry contract (validating the real
``registry.yaml``), the dataset contract, and the event contract.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from contracts.datasets import DatasetContractV1
from contracts.events import EventContractV1
from contracts.formulas import (
    SCHEMA,
    FormulaRecordV1,
    FormulaRegistryFileV1,
)


class TestFormulaContract:
    """Tests for the formula registry contract."""

    def test_valid_record(self) -> None:
        """A valid record parses."""
        record = FormulaRecordV1(
            id="gross_margin",
            name="Gross Margin",
            description="Gross profit over revenue.",
            expression="(NetRevenue - COGS) / NetRevenue * 100",
            category="Profitability",
        )
        assert record.id == "gross_margin"
        assert record.output == "Decimal"

    def test_invalid_category_rejected(self) -> None:
        """A category outside the literal set is rejected."""
        with pytest.raises(ValidationError):
            FormulaRecordV1(
                id="x",
                name="X",
                description="X",
                expression="1",
                category="Fiction",
            )

    def test_bad_semver_rejected(self) -> None:
        """A non-MAJOR.MINOR.PATCH version is rejected."""
        with pytest.raises(ValidationError):
            FormulaRecordV1(
                id="x",
                name="X",
                description="X",
                expression="1",
                category="Profitability",
                version="1.0",
            )

    def test_whitespace_in_id_rejected(self) -> None:
        """Ids must be snake_case alphanumeric."""
        with pytest.raises(ValidationError):
            FormulaRecordV1(
                id="bad id",
                name="X",
                description="X",
                expression="1",
                category="Profitability",
            )

    def test_registry_file_validates_shipped_yaml(self) -> None:
        """The shipped registry.yaml satisfies the contract."""
        import yaml

        with open("business/formula_registry/registry.yaml", encoding="utf-8") as f:
            payload = yaml.safe_load(f)
        registry_file = FormulaRegistryFileV1(**payload)
        assert registry_file.schema_name == SCHEMA
        assert len(registry_file.formulas) == 74

    def test_wrong_schema_rejected(self) -> None:
        """A file declaring the wrong schema is rejected."""
        with pytest.raises(ValidationError):
            FormulaRegistryFileV1(
                schema="finsight/other",
                version="1.0.0",
                count=0,
                formulas=[],
            )

    def test_count_mismatch_rejected(self) -> None:
        """A declared count that disagrees with the list is rejected."""
        record = FormulaRecordV1(
            id="a",
            name="A",
            description="A",
            expression="1",
            category="Profitability",
        )
        with pytest.raises(ValidationError):
            FormulaRegistryFileV1(
                schema=SCHEMA,
                version="1.0.0",
                count=2,
                formulas=[record],
            )


class TestDatasetContract:
    """Tests for the dataset contract."""

    def test_valid_dataset(self) -> None:
        """A valid dataset contract parses."""
        dataset = DatasetContractV1(
            dataset_id="finance.actuals",
            name="Actuals",
            description="Actuals ledger data.",
            table="actuals",
            schema_ref="schemas/actuals.json",
            owner="FP&A Team",
            updated_at="2026-01-01T00:00:00Z",
        )
        assert dataset.sensitivity == "internal"
        assert dataset.version == "1.0.0"

    def test_bad_sensitivity_rejected(self) -> None:
        """An unknown sensitivity value is rejected."""
        with pytest.raises(ValidationError):
            DatasetContractV1(
                dataset_id="finance.actuals",
                name="Actuals",
                description="Actuals.",
                table="actuals",
                schema_ref="schemas/actuals.json",
                updated_at="2026-01-01T00:00:00Z",
                sensitivity="top-secret",
            )

    def test_whitespace_in_id_rejected(self) -> None:
        """Ids must not contain whitespace."""
        with pytest.raises(ValidationError):
            DatasetContractV1(
                dataset_id="bad id",
                name="Actuals",
                description="Actuals.",
                table="actuals",
                schema_ref="schemas/actuals.json",
                updated_at="2026-01-01T00:00:00Z",
            )


class TestEventContract:
    """Tests for the event contract."""

    def test_valid_event(self) -> None:
        """A valid event contract parses."""
        event = EventContractV1(
            event_id="evt-123",
            event_type="invoice.imported",
            producer="CSV Connector",
            payload={"amount": Decimal("100.00")},
        )
        assert event.version == "1.0"
        assert event.sensitivity == "internal"
        assert isinstance(event.timestamp, datetime)

    def test_frozen(self) -> None:
        """The contract is immutable."""
        event = EventContractV1(
            event_id="evt-123",
            event_type="invoice.imported",
            producer="CSV Connector",
        )
        with pytest.raises(ValidationError):
            setattr(event, "payload", {"x": 1})  # noqa: B010 — runtime frozen validation
