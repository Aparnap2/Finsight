from decimal import Decimal

import pytest

from backend.models.assertions import Assertion, AssertionType, SupportLevel
from backend.validators.assertion_validator import (
    validate_assertion,
    AssertionValidationResult,
)


# ---------------------------------------------------------------------------
# Core model tests
# ---------------------------------------------------------------------------


def test_assertion_defaults():
    a = Assertion(
        id="asst-001",
        type=AssertionType.NUMERIC,
        text="Revenue was $100k",
        value=Decimal("100000"),
    )
    assert a.id == "asst-001"
    assert a.type is AssertionType.NUMERIC
    assert a.value == Decimal("100000")
    assert a.support_level is SupportLevel.INSUFFICIENT
    assert a.evidence_ids == []
    assert a.max_allowed_action == "route_for_review"
    assert a.source == ""


def test_assertion_type_enum_values():
    assert AssertionType.NUMERIC.value == "numeric"
    assert AssertionType.COMPARATIVE.value == "comparative"
    assert AssertionType.CAUSAL.value == "causal"
    assert AssertionType.HYPOTHESIS.value == "hypothesis"
    assert AssertionType.ACTION.value == "action"


def test_support_level_enum_values():
    assert SupportLevel.VERIFIED.value == "verified"
    assert SupportLevel.PROBABLE.value == "probable"
    assert SupportLevel.INSUFFICIENT.value == "insufficient"


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


def test_numeric_assertion_with_valid_evidence_passes():
    """Numeric assertion with valid evidence → passes."""
    a = Assertion(
        id="asst-num-001",
        type=AssertionType.NUMERIC,
        text="Revenue was $100k",
        value=Decimal("100000"),
        evidence_ids=["evt-001", "evt-002"],
        support_level=SupportLevel.INSUFFICIENT,
    )
    result = validate_assertion(a)
    assert result.is_valid is True
    assert result.adjusted_support_level is SupportLevel.VERIFIED
    assert result.errors == []


def test_numeric_assertion_with_no_evidence_fails():
    """Numeric assertion with no evidence → fails."""
    a = Assertion(
        id="asst-num-002",
        type=AssertionType.NUMERIC,
        text="Revenue was $100k",
        value=Decimal("100000"),
        evidence_ids=[],
    )
    result = validate_assertion(a)
    assert result.is_valid is False
    assert "must cite evidence" in str(result.errors)
    assert result.adjusted_support_level is SupportLevel.INSUFFICIENT


def test_numeric_assertion_with_no_value_fails():
    """Numeric assertion with no value → fails."""
    a = Assertion(
        id="asst-num-003",
        type=AssertionType.NUMERIC,
        text="Something happened",
        value=None,
        evidence_ids=["evt-001"],
    )
    result = validate_assertion(a)
    assert result.is_valid is False
    assert "must have a value" in str(result.errors)


def test_causal_assertion_with_single_source_downgraded():
    """Causal assertion with single source → downgraded to PROBABLE."""
    a = Assertion(
        id="asst-cau-001",
        type=AssertionType.CAUSAL,
        text="Cost increase due to supplier price hike",
        evidence_ids=["evt-001"],
        support_level=SupportLevel.VERIFIED,
    )
    result = validate_assertion(a, evidence_count=1, source_count=1)
    assert result.is_valid is False
    assert result.adjusted_support_level is SupportLevel.INSUFFICIENT
    assert any("≥2 independent evidence" in e for e in result.errors)


def test_causal_assertion_with_two_sources_passes():
    """Causal assertion with 2+ sources → passes."""
    a = Assertion(
        id="asst-cau-002",
        type=AssertionType.CAUSAL,
        text="Cost increase due to supplier price hike",
        evidence_ids=["evt-001", "evt-002", "evt-003"],
    )
    result = validate_assertion(a, evidence_count=3, source_count=2)
    assert result.is_valid is True
    assert result.adjusted_support_level is SupportLevel.VERIFIED


def test_hypothesis_is_never_verified():
    """Hypothesis is never VERIFIED, max PROBABLE."""
    a = Assertion(
        id="asst-hyp-001",
        type=AssertionType.HYPOTHESIS,
        text="Might be a seasonal pattern",
        evidence_ids=["evt-001", "evt-002"],
        support_level=SupportLevel.VERIFIED,
    )
    result = validate_assertion(a)
    assert result.is_valid is True
    assert result.adjusted_support_level is SupportLevel.PROBABLE
    assert result.adjusted_support_level is not SupportLevel.VERIFIED


def test_comparative_assertion_requires_ranked_facts():
    """Comparative assertion requires ranked facts (≥2 evidence)."""
    a = Assertion(
        id="asst-cmp-001",
        type=AssertionType.COMPARATIVE,
        text="Q2 revenue outperformed Q1 by 15%",
        value=Decimal("15.00"),
        evidence_ids=["evt-001"],
    )
    result = validate_assertion(a, evidence_count=1)
    assert result.is_valid is False
    assert any("ranked facts" in e for e in result.errors)


def test_comparative_assertion_with_enough_evidence():
    """Comparative assertion with enough evidence passes."""
    a = Assertion(
        id="asst-cmp-002",
        type=AssertionType.COMPARATIVE,
        text="Q2 outperformed Q1 by 15%",
        value=Decimal("15.00"),
        evidence_ids=["evt-001", "evt-002", "evt-003"],
    )
    result = validate_assertion(a, evidence_count=3)
    assert result.is_valid is True
    assert result.adjusted_support_level is SupportLevel.VERIFIED


def test_action_assertion_requires_template():
    """Action assertion requires an allowed template."""
    a = Assertion(
        id="asst-act-001",
        type=AssertionType.ACTION,
        text="Approve budget adjustment",
        max_allowed_action="invalid_action",
    )
    result = validate_assertion(a)
    assert result.is_valid is False
    assert "allowed template" in str(result.errors)


def test_action_assertion_with_valid_template_passes():
    """Action assertion with a valid template passes."""
    a = Assertion(
        id="asst-act-002",
        type=AssertionType.ACTION,
        text="Route discrepancy for manager review",
        max_allowed_action="flag_for_approval",
        evidence_ids=["evt-001"],
    )
    result = validate_assertion(a)
    assert result.is_valid is True
    assert result.adjusted_support_level is SupportLevel.VERIFIED


def test_empty_evidence_ids_causes_validation_failure():
    """Empty evidence_ids → validation failure for types that require evidence."""
    test_cases = [
        (AssertionType.NUMERIC, {"value": Decimal("100")}),
        (AssertionType.COMPARATIVE, {"value": Decimal("10")}),
        (AssertionType.CAUSAL, {}),
    ]
    for asst_type, extra in test_cases:
        a = Assertion(
            id=f"asst-evidence-{asst_type.value}",
            type=asst_type,
            text=f"Test {asst_type.value}",
            evidence_ids=[],
            **extra,
        )
        result = validate_assertion(a, evidence_count=0, source_count=1)
        assert result.is_valid is False, f"{asst_type.value} should fail with no evidence"
        assert any("must cite evidence" in e for e in result.errors), (
            f"{asst_type.value} missing 'must cite evidence' error"
        )


def test_hypothesis_with_contradictions_warns():
    """Hypothesis with contradictions generates warnings."""
    a = Assertion(
        id="asst-hyp-002",
        type=AssertionType.HYPOTHESIS,
        text="Might be related to FX changes",
        evidence_ids=["evt-001"],
        contradictions=["Data shows strengthening, not weakening"],
    )
    result = validate_assertion(a)
    assert result.is_valid is True
    assert any("contradiction" in w for w in result.warnings)


def test_action_insufficient_support_warns():
    """Action with INSUFFICIENT support level generates a warning."""
    a = Assertion(
        id="asst-act-003",
        type=AssertionType.ACTION,
        text="Auto-approve the adjustment",
        max_allowed_action="auto_accept",
        support_level=SupportLevel.INSUFFICIENT,
    )
    result = validate_assertion(a)
    assert result.is_valid is True
    assert any("insufficient support" in w.lower() for w in result.warnings)


def test_validation_result_structure():
    """AssertionValidationResult has expected fields."""
    a = Assertion(
        id="asst-str-001",
        type=AssertionType.NUMERIC,
        text="Test",
        value=Decimal("42"),
        evidence_ids=["evt-001"],
    )
    result = validate_assertion(a)
    assert isinstance(result, AssertionValidationResult)
    assert hasattr(result, "is_valid")
    assert hasattr(result, "assertion_id")
    assert hasattr(result, "errors")
    assert hasattr(result, "warnings")
    assert hasattr(result, "adjusted_support_level")
