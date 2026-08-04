"""Tests for the shared Assertion model.

Covers ``shared/models/assertions.py``: the ``AssertionType`` and
``SupportLevel`` enums and the ``Assertion`` model that backs evidence for
commentary, root-cause analysis, and recommendation gating.
"""

import pytest
from pydantic import ValidationError

from shared.models.assertions import Assertion, AssertionType, SupportLevel


def _assertion(**overrides: object) -> Assertion:
    """Build a default assertion, overriding fields as needed."""
    defaults: dict[str, object] = {
        "id": "ASRT-001",
        "type": AssertionType.NUMERIC,
        "text": "Revenue grew 8% year over year.",
        "value": "1.08",
    }
    defaults.update(overrides)
    return Assertion(**defaults)


# =============================================================================
# Enums
# =============================================================================


class TestAssertionType:
    """AssertionType enum values."""

    def test_numeric_value(self) -> None:
        """NUMERIC serializes to 'numeric'."""
        assert AssertionType.NUMERIC.value == "numeric"

    def test_comparative_value(self) -> None:
        """COMPARATIVE serializes to 'comparative'."""
        assert AssertionType.COMPARATIVE.value == "comparative"

    def test_causal_value(self) -> None:
        """CAUSAL serializes to 'causal'."""
        assert AssertionType.CAUSAL.value == "causal"

    def test_hypothesis_value(self) -> None:
        """HYPOTHESIS serializes to 'hypothesis'."""
        assert AssertionType.HYPOTHESIS.value == "hypothesis"

    def test_action_value(self) -> None:
        """ACTION serializes to 'action'."""
        assert AssertionType.ACTION.value == "action"


class TestSupportLevel:
    """SupportLevel enum values."""

    def test_verified_value(self) -> None:
        """VERIFIED serializes to 'verified'."""
        assert SupportLevel.VERIFIED.value == "verified"

    def test_probable_value(self) -> None:
        """PROBABLE serializes to 'probable'."""
        assert SupportLevel.PROBABLE.value == "probable"

    def test_weak_value(self) -> None:
        """WEAK serializes to 'weak'."""
        assert SupportLevel.WEAK.value == "weak"

    def test_insufficient_value(self) -> None:
        """INSUFFICIENT serializes to 'insufficient'."""
        assert SupportLevel.INSUFFICIENT.value == "insufficient"


# =============================================================================
# Construction & defaults
# =============================================================================


class TestAssertionConstruction:
    """Assertion construction and defaults."""

    def test_constructs_with_required_fields(self) -> None:
        """An assertion builds with required fields."""
        assertion = _assertion()
        assert assertion.id == "ASRT-001"
        assert assertion.type == AssertionType.NUMERIC
        assert assertion.text == "Revenue grew 8% year over year."
        assert str(assertion.value) == "1.08"

    def test_support_level_defaults_to_insufficient(self) -> None:
        """The support level defaults to INSUFFICIENT."""
        assert _assertion().support_level == SupportLevel.INSUFFICIENT

    def test_confidence_defaults_to_zero(self) -> None:
        """confidence defaults to 0.0."""
        assert _assertion().confidence == 0.0

    def test_evidence_ids_default_to_empty(self) -> None:
        """evidence_ids defaults to an empty list."""
        assert _assertion().evidence_ids == []

    def test_contradictions_default_to_empty(self) -> None:
        """contradictions defaults to an empty list."""
        assert _assertion().contradictions == []

    def test_missing_evidence_default_to_empty(self) -> None:
        """missing_evidence defaults to an empty list."""
        assert _assertion().missing_evidence == []

    def test_max_allowed_action_default(self) -> None:
        """max_allowed_action defaults to route_for_review."""
        assert _assertion().max_allowed_action == "route_for_review"

    def test_source_defaults_to_empty(self) -> None:
        """source defaults to an empty string."""
        assert _assertion().source == ""

    def test_value_defaults_to_none(self) -> None:
        """value defaults to None."""
        assert _assertion(value=None).value is None

    def test_id_required(self) -> None:
        """An assertion requires an id."""
        with pytest.raises(ValidationError):
            _assertion(id=None)

    def test_type_required(self) -> None:
        """An assertion requires a type."""
        with pytest.raises(ValidationError):
            _assertion(type=None)

    def test_text_required(self) -> None:
        """An assertion requires text."""
        with pytest.raises(ValidationError):
            _assertion(text=None)


# =============================================================================
# Value & confidence
# =============================================================================


class TestAssertionValue:
    """Assertion value and confidence validation."""

    def test_string_value_coerced(self) -> None:
        """A string value is coerced to Decimal."""
        assertion = _assertion(value="1.08")
        assert str(assertion.value) == "1.08"

    def test_int_value_coerced(self) -> None:
        """An int value is coerced to Decimal."""
        assertion = _assertion(value=8)
        assert str(assertion.value) == "8"

    def test_negative_value_representable(self) -> None:
        """A negative value is representable."""
        assertion = _assertion(value="-0.12")
        assert str(assertion.value) == "-0.12"

    def test_zero_value_representable(self) -> None:
        """A zero value is representable."""
        assertion = _assertion(value="0.00")
        assert str(assertion.value) == "0.00"

    def test_confidence_is_float(self) -> None:
        """confidence is stored as a float."""
        assertion = _assertion(confidence=0.87)
        assert assertion.confidence == 0.87

    def test_confidence_out_of_range_representable(self) -> None:
        """confidence has no range constraint at the model boundary.

        Documented residual risk: values outside [0, 1] are accepted.
        Callers must validate; the model is a plain container.
        """
        assertion = _assertion(confidence=1.5)
        assert assertion.confidence == 1.5


# =============================================================================
# Evidence & policy linkage
# =============================================================================


class TestAssertionLinkage:
    """Assertion evidence, contradictions, and policy gating."""

    def test_evidence_ids_stored(self) -> None:
        """Evidence ids are stored as provided."""
        assertion = _assertion(evidence_ids=["EVID-1", "EVID-2"])
        assert assertion.evidence_ids == ["EVID-1", "EVID-2"]

    def test_contradictions_stored(self) -> None:
        """Contradicting evidence ids are stored."""
        assertion = _assertion(contradictions=["EVID-9"])
        assert assertion.contradictions == ["EVID-9"]

    def test_missing_evidence_stored(self) -> None:
        """Missing evidence ids are stored."""
        assertion = _assertion(missing_evidence=["KPI-HEADCOUNT"])
        assert assertion.missing_evidence == ["KPI-HEADCOUNT"]

    def test_max_allowed_action_settable(self) -> None:
        """The gating policy action is settable."""
        assertion = _assertion(max_allowed_action="no_action")
        assert assertion.max_allowed_action == "no_action"

    def test_source_values(self) -> None:
        """The source is settable to the documented values."""
        for source in ("deterministic", "llm_analysis", "human"):
            assertion = _assertion(source=source)
            assert assertion.source == source

    def test_metadata_stored(self) -> None:
        """Structured metadata is preserved."""
        assertion = _assertion(metadata={"account": "4010", "period": "2026-06"})
        assert assertion.metadata["account"] == "4010"
        assert assertion.metadata["period"] == "2026-06"

    def test_round_trip_serialization(self) -> None:
        """An assertion round-trips through model_dump."""
        assertion = _assertion(
            evidence_ids=["EVID-1"],
            contradictions=["EVID-9"],
            missing_evidence=["KPI-1"],
            metadata={"account": "4010"},
        )
        dumped = assertion.model_dump()
        rebuilt = Assertion(**dumped)
        assert rebuilt == assertion