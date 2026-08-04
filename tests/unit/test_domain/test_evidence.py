"""Tests for the Evidence domain model.

Covers ``finance/domain/evidence.py``: the ``EvidenceSource`` and
``EvidenceConfidence`` enums and the ``EvidenceItem`` aggregate. Key
invariants: source values use ``MoneyDecimal`` (float rejected), evidence
links to exactly one source object, and confidence levels are from the
closed enum.
"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from finance.domain.evidence import (
    EvidenceConfidence,
    EvidenceItem,
    EvidenceSource,
)


def _now() -> datetime:
    """A fixed timestamp for created_at."""
    return datetime(2026, 7, 15, 12, 0, 0, tzinfo=UTC)


def _evidence(**overrides: object) -> EvidenceItem:
    """Build a default evidence item, overriding fields as needed."""
    defaults: dict[str, object] = {
        "id": "EVID-001",
        "claim": "Travel spend increased 12% quarter over quarter.",
        "source_type": EvidenceSource.VARIANCE,
        "source_id": "VAR-2026-042",
        "source_value": "1200.00",
        "confidence": EvidenceConfidence.HIGH,
        "created_at": _now(),
    }
    defaults.update(overrides)
    return EvidenceItem(**defaults)


# =============================================================================
# Enums
# =============================================================================


class TestEvidenceSource:
    """EvidenceSource enum values."""

    def test_kpi_value(self) -> None:
        """KPI serializes to 'kpi'."""
        assert EvidenceSource.KPI.value == "kpi"

    def test_variance_value(self) -> None:
        """VARIANCE serializes to 'variance'."""
        assert EvidenceSource.VARIANCE.value == "variance"

    def test_driver_value(self) -> None:
        """DRIVER serializes to 'driver'."""
        assert EvidenceSource.DRIVER.value == "driver"

    def test_transaction_value(self) -> None:
        """TRANSACTION serializes to 'transaction'."""
        assert EvidenceSource.TRANSACTION.value == "transaction"

    def test_manual_value(self) -> None:
        """MANUAL serializes to 'manual'."""
        assert EvidenceSource.MANUAL.value == "manual"


class TestEvidenceConfidence:
    """EvidenceConfidence enum values."""

    def test_high_value(self) -> None:
        """HIGH serializes to 'high'."""
        assert EvidenceConfidence.HIGH.value == "high"

    def test_medium_value(self) -> None:
        """MEDIUM serializes to 'medium'."""
        assert EvidenceConfidence.MEDIUM.value == "medium"

    def test_low_value(self) -> None:
        """LOW serializes to 'low'."""
        assert EvidenceConfidence.LOW.value == "low"

    def test_tentative_value(self) -> None:
        """TENTATIVE serializes to 'tentative'."""
        assert EvidenceConfidence.TENTATIVE.value == "tentative"

    def test_all_confidences_are_representable(self) -> None:
        """Every confidence level constructs an evidence item."""
        for confidence in EvidenceConfidence:
            item = _evidence(confidence=confidence)
            assert item.confidence == confidence


# =============================================================================
# Construction
# =============================================================================


class TestEvidenceConstruction:
    """Evidence item construction and defaults."""

    def test_constructs_with_required_fields(self) -> None:
        """An evidence item builds with required fields."""
        item = _evidence()
        assert item.id == "EVID-001"
        assert item.claim == "Travel spend increased 12% quarter over quarter."
        assert item.source_type == EvidenceSource.VARIANCE
        assert item.source_id == "VAR-2026-042"
        assert item.confidence == EvidenceConfidence.HIGH

    def test_source_value_defaults_to_none(self) -> None:
        """source_value defaults to None."""
        assert _evidence(source_value=None).source_value is None

    def test_supporting_metrics_default_to_empty(self) -> None:
        """supporting_metrics defaults to an empty list."""
        assert _evidence().supporting_metrics == []

    def test_assumptions_default_to_empty(self) -> None:
        """assumptions defaults to an empty list."""
        assert _evidence().assumptions == []

    def test_limitations_default_to_empty(self) -> None:
        """limitations defaults to an empty list."""
        assert _evidence().limitations == []

    def test_id_required(self) -> None:
        """An evidence item requires an id."""
        with pytest.raises(ValidationError):
            _evidence(id=None)

    def test_claim_required(self) -> None:
        """An evidence item requires a claim."""
        with pytest.raises(ValidationError):
            _evidence(claim=None)

    def test_source_type_required(self) -> None:
        """An evidence item requires a source type."""
        with pytest.raises(ValidationError):
            _evidence(source_type=None)

    def test_source_id_required(self) -> None:
        """An evidence item requires a source id."""
        with pytest.raises(ValidationError):
            _evidence(source_id=None)

    def test_confidence_required(self) -> None:
        """An evidence item requires a confidence level."""
        with pytest.raises(ValidationError):
            _evidence(confidence=None)

    def test_created_at_required(self) -> None:
        """An evidence item requires a created_at timestamp."""
        with pytest.raises(ValidationError):
            _evidence(created_at=None)


# =============================================================================
# Source value validation
# =============================================================================


class TestEvidenceSourceValue:
    """Evidence source value monetary validation."""

    def test_float_source_value_rejected(self) -> None:
        """A float source value is rejected."""
        with pytest.raises(ValidationError):
            _evidence(source_value=1200.0)

    def test_string_source_value_coerced(self) -> None:
        """A string source value is coerced to Decimal."""
        item = _evidence(source_value="1200.00")
        assert str(item.source_value) == "1200.00"

    def test_negative_source_value_allowed(self) -> None:
        """A negative source value is representable (e.g., expense variance)."""
        item = _evidence(source_value="-1200.00")
        assert str(item.source_value) == "-1200.00"

    def test_zero_source_value_allowed(self) -> None:
        """A zero source value is representable."""
        item = _evidence(source_value="0.00")
        assert str(item.source_value) == "0.00"

    def test_int_source_value_accepted(self) -> None:
        """An int source value is accepted by MoneyDecimal."""
        item = _evidence(source_value=1200)
        assert str(item.source_value) == "1200"


# =============================================================================
# Evidence metadata
# =============================================================================


class TestEvidenceMetadata:
    """Evidence supporting metrics, assumptions, and limitations."""

    def test_supporting_metrics_stored(self) -> None:
        """Supporting metric ids are stored as provided."""
        item = _evidence(supporting_metrics=["KPI-REV-GROWTH", "DRV-HEADCOUNT"])
        assert item.supporting_metrics == ["KPI-REV-GROWTH", "DRV-HEADCOUNT"]

    def test_assumptions_stored(self) -> None:
        """Assumptions are stored as provided."""
        item = _evidence(assumptions=["FX rate held constant at 1.08"])
        assert item.assumptions == ["FX rate held constant at 1.08"]

    def test_limitations_stored(self) -> None:
        """Limitations are stored as provided."""
        item = _evidence(limitations=["Data covers 9 of 12 months"])
        assert item.limitations == ["Data covers 9 of 12 months"]

    def test_round_trip_serialization(self) -> None:
        """An evidence item round-trips through model_dump."""
        item = _evidence(
            supporting_metrics=["KPI-1"],
            assumptions=["assumption"],
            limitations=["limitation"],
        )
        dumped = item.model_dump()
        rebuilt = EvidenceItem(**dumped)
        assert rebuilt == item

    def test_all_sources_are_representable(self) -> None:
        """Every source type constructs an evidence item."""
        for source in EvidenceSource:
            item = _evidence(source_type=source)
            assert item.source_type == source