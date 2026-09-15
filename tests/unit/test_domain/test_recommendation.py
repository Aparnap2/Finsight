"""Tests for the Recommendation domain model.

Covers ``finance/domain/recommendation.py``: the ``RecommendationType`` and
``RecommendationStatus`` enums and the ``Recommendation`` aggregate. Key
invariants: monetary impact uses ``MoneyDecimal`` (float rejected), the
lifecycle status defaults to ``PROPOSED``, and evidence linkage is via
``evidence_ids``.
"""

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from finance.domain.evidence import EvidenceConfidence
from finance.domain.recommendation import (
    Recommendation,
    RecommendationStatus,
    RecommendationType,
)


def _now() -> datetime:
    """A fixed timestamp for created/updated fields."""
    return datetime(2026, 7, 15, 12, 0, 0, tzinfo=UTC)


def _recommendation(**overrides: object) -> Recommendation:
    """Build a default recommendation, overriding fields as needed."""
    defaults: dict[str, object] = {
        "id": "REC-001",
        "type": RecommendationType.COST_SAVING,
        "title": "Consolidate vendors",
        "description": "Merge two vendors to reduce procurement cost.",
        "expected_impact": "50000.00",
        "confidence": EvidenceConfidence.HIGH,
        "created_at": _now(),
        "updated_at": _now(),
    }
    defaults.update(overrides)
    return Recommendation(**defaults)


# =============================================================================
# Enums
# =============================================================================


class TestRecommendationType:
    """RecommendationType enum values."""

    def test_cost_saving_value(self) -> None:
        """COST_SAVING serializes to 'cost_saving'."""
        assert RecommendationType.COST_SAVING.value == "cost_saving"

    def test_revenue_optimization_value(self) -> None:
        """REVENUE_OPTIMIZATION serializes to 'revenue_optimization'."""
        assert RecommendationType.REVENUE_OPTIMIZATION.value == "revenue_optimization"

    def test_process_improvement_value(self) -> None:
        """PROCESS_IMPROVEMENT serializes to 'process_improvement'."""
        assert RecommendationType.PROCESS_IMPROVEMENT.value == "process_improvement"

    def test_risk_mitigation_value(self) -> None:
        """RISK_MITIGATION serializes to 'risk_mitigation'."""
        assert RecommendationType.RISK_MITIGATION.value == "risk_mitigation"

    def test_all_types_are_str_enum(self) -> None:
        """All recommendation types are StrEnum members."""
        for member in RecommendationType:
            assert isinstance(member.value, str)


class TestRecommendationStatus:
    """RecommendationStatus enum values."""

    def test_proposed_value(self) -> None:
        """PROPOSED serializes to 'proposed'."""
        assert RecommendationStatus.PROPOSED.value == "proposed"

    def test_reviewed_value(self) -> None:
        """REVIEWED serializes to 'reviewed'."""
        assert RecommendationStatus.REVIEWED.value == "reviewed"

    def test_approved_value(self) -> None:
        """APPROVED serializes to 'approved'."""
        assert RecommendationStatus.APPROVED.value == "approved"

    def test_implemented_value(self) -> None:
        """IMPLEMENTED serializes to 'implemented'."""
        assert RecommendationStatus.IMPLEMENTED.value == "implemented"

    def test_rejected_value(self) -> None:
        """REJECTED serializes to 'rejected'."""
        assert RecommendationStatus.REJECTED.value == "rejected"


# ===========================================================================
# Construction
# ===========================================================================


class TestRecommendationConstruction:
    """Recommendation construction and defaults."""

    def test_constructs_with_required_fields(self) -> None:
        """A recommendation builds with required fields."""
        rec = _recommendation()
        assert rec.id == "REC-001"
        assert rec.type == RecommendationType.COST_SAVING
        assert rec.title == "Consolidate vendors"
        assert rec.description == "Merge two vendors to reduce procurement cost."

    def test_status_defaults_to_proposed(self) -> None:
        """The lifecycle status defaults to PROPOSED."""
        assert _recommendation().status == RecommendationStatus.PROPOSED

    def test_impact_currency_defaults_to_usd(self) -> None:
        """The impact currency defaults to USD."""
        assert _recommendation().impact_currency == "USD"

    def test_evidence_ids_default_to_empty(self) -> None:
        """evidence_ids defaults to an empty list."""
        assert _recommendation().evidence_ids == []

    def test_owner_defaults_to_none(self) -> None:
        """owner defaults to None."""
        assert _recommendation().owner is None

    def test_target_date_defaults_to_none(self) -> None:
        """target_date defaults to None."""
        assert _recommendation().target_date is None

    def test_expected_impact_defaults_to_none(self) -> None:
        """expected_impact defaults to None."""
        assert _recommendation(expected_impact=None).expected_impact is None

    def test_id_required(self) -> None:
        """A recommendation requires an id."""
        with pytest.raises(ValidationError):
            _recommendation(id=None)

    def test_type_required(self) -> None:
        """A recommendation requires a type."""
        with pytest.raises(ValidationError):
            _recommendation(type=None)

    def test_title_required(self) -> None:
        """A recommendation requires a title."""
        with pytest.raises(ValidationError):
            _recommendation(title=None)

    def test_description_required(self) -> None:
        """A recommendation requires a description."""
        with pytest.raises(ValidationError):
            _recommendation(description=None)

    def test_confidence_required(self) -> None:
        """A recommendation requires a confidence level."""
        with pytest.raises(ValidationError):
            _recommendation(confidence=None)

    def test_created_at_required(self) -> None:
        """A recommendation requires a created_at timestamp."""
        with pytest.raises(ValidationError):
            _recommendation(created_at=None)

    def test_updated_at_required(self) -> None:
        """A recommendation requires an updated_at timestamp."""
        with pytest.raises(ValidationError):
            _recommendation(updated_at=None)


# ===========================================================================
# Monetary impact
# ===========================================================================


class TestRecommendationImpact:
    """Expected impact monetary validation."""

    def test_float_impact_rejected(self) -> None:
        """A float expected impact is rejected."""
        with pytest.raises(ValidationError):
            _recommendation(expected_impact=50000.0)

    def test_string_impact_coerced(self) -> None:
        """A string expected impact is coerced to Decimal."""
        rec = _recommendation(expected_impact="50000.00")
        assert str(rec.expected_impact) == "50000.00"

    def test_negative_impact_allowed(self) -> None:
        """A negative expected impact (cost) is representable."""
        rec = _recommendation(expected_impact="-2500.00")
        assert str(rec.expected_impact) == "-2500.00"

    def test_zero_impact_allowed(self) -> None:
        """A zero expected impact is representable."""
        rec = _recommendation(expected_impact="0.00")
        assert str(rec.expected_impact) == "0.00"

    def test_high_precision_impact_preserved(self) -> None:
        """MoneyDecimal does not enforce 4-dp precision at the model boundary.

        Unlike ``business.canonical_types.Money`` (which quantizes to 4
        decimal places), the finance-domain ``MoneyDecimal`` alias only
        rejects ``float``. A 5-dp impact is therefore preserved as-is.
        This is a documented residual risk: precision is not normalized
        until a downstream engine quantizes.
        """
        rec = _recommendation(expected_impact="1.00001")
        assert str(rec.expected_impact) == "1.00001"


# ===========================================================================
# Lifecycle & linkage
# ===========================================================================


class TestRecommendationLifecycle:
    """Recommendation status and evidence linkage."""

    def test_status_accepts_all_lifecycle_states(self) -> None:
        """All lifecycle states are representable."""
        for status in RecommendationStatus:
            rec = _recommendation(status=status)
            assert rec.status == status

    def test_evidence_ids_are_linked(self) -> None:
        """Evidence ids are stored as provided."""
        rec = _recommendation(evidence_ids=["EVID-1", "EVID-2"])
        assert rec.evidence_ids == ["EVID-1", "EVID-2"]

    def test_owner_and_target_date_are_settable(self) -> None:
        """Owner and target date are settable."""
        rec = _recommendation(
            owner="finance.lead", target_date=date(2026, 9, 30)
        )
        assert rec.owner == "finance.lead"
        assert rec.target_date == date(2026, 9, 30)

    def test_impact_currency_is_settable(self) -> None:
        """The impact currency is settable."""
        rec = _recommendation(impact_currency="EUR")
        assert rec.impact_currency == "EUR"

    def test_round_trip_serialization(self) -> None:
        """A recommendation round-trips through model_dump."""
        rec = _recommendation()
        dumped = rec.model_dump()
        rebuilt = Recommendation(**dumped)
        assert rebuilt == rec