"""Agentic capability tests: Hallucination Resistance dimension.

Tests claim validation, monetary extraction, tolerance enforcement,
assertion validation per type, and hallucination detection patterns
that prevent the system from making unsupported claims.
"""

import pytest
from decimal import Decimal

from backend.validators.claim_validator import (
    validate_commentary_claims,
    extract_monetary_claims,
    ValidationResult,
    Claim,
)
from backend.validators.assertion_validator import (
    validate_assertion,
    AssertionValidationResult,
)
from backend.models.assertions import Assertion, AssertionType, SupportLevel


# ── Claim validator: valid claims ─────────────────────────────────────────────


class TestClaimValidatorValid:
    def test_valid_claims_pass(self):
        """Claims matching facts within tolerance must pass validation."""
        commentary = "Revenue was $484,464."
        facts = [{"amount": Decimal("484464")}]
        result = validate_commentary_claims(commentary, facts)
        assert result.is_valid
        assert len(result.verified_claims) > 0

    def test_empty_commentary_is_valid(self):
        """Empty commentary must be trivially valid."""
        result = validate_commentary_claims("", [])
        assert result.is_valid

    def test_whitespace_commentary_is_valid(self):
        """Whitespace-only commentary must be trivially valid."""
        result = validate_commentary_claims("   ", [])
        assert result.is_valid

    def test_claim_within_3pct_tolerance_passes(self):
        """Claims within 3% of fact must pass (tolerance is 5%)."""
        commentary = "Costs were $103,000."
        facts = [{"amount": Decimal("100000")}]
        result = validate_commentary_claims(commentary, facts)
        assert result.is_valid

    def test_claim_at_exact_5pct_tolerance_passes(self):
        """Claims at exactly 5% above fact must pass (<= tolerance)."""
        commentary = "Costs were $105,000."
        facts = [{"amount": Decimal("100000")}]
        result = validate_commentary_claims(commentary, facts)
        assert result.is_valid

    def test_multiple_facts_multiple_claims(self):
        """Multiple verified claims against multiple facts must all pass."""
        commentary = "Revenue was $1,000,000 and costs were $500,000."
        facts = [{"amount": Decimal("1000000")}, {"amount": Decimal("500000")}]
        result = validate_commentary_claims(commentary, facts)
        assert result.is_valid
        assert len(result.verified_claims) >= 2


# ── Claim validator: hallucinated / unverified ────────────────────────────────


class TestClaimValidatorUnverified:
    def test_hallucinated_claim_fails(self):
        """Claims not matching any fact must be flagged as unverified."""
        commentary = "Revenue was $999,999,999 which is a huge number."
        facts = [{"amount": Decimal("100000")}]
        result = validate_commentary_claims(commentary, facts)
        assert not result.is_valid
        assert len(result.unverified_claims) > 0
        assert len(result.errors) > 0

    def claim_barely_outside_tolerance_fails(self):
        """Claims just outside 5% tolerance must fail."""
        commentary = "Costs were $110,000."
        facts = [{"amount": Decimal("100000")}]
        result = validate_commentary_claims(commentary, facts)
        assert not result.is_valid

    def test_no_facts_causes_all_claims_unverified(self):
        """With no facts, every monetary claim must be unverified."""
        commentary = "Revenue was $1,000,000 and costs were $500,000."
        result = validate_commentary_claims(commentary, [])
        assert not result.is_valid
        assert len(result.unverified_claims) >= 2
        assert len(result.verified_claims) == 0

    def test_mixed_verified_and_unverified(self):
        """Some claims passing and some failing must result in invalid overall."""
        commentary = "Revenue was $1,000,000 and costs were $999,999,999."
        facts = [{"amount": Decimal("1000000")}]
        result = validate_commentary_claims(commentary, facts)
        assert not result.is_valid
        assert len(result.verified_claims) >= 1
        assert len(result.unverified_claims) >= 1

    def test_invalid_claims_have_errors(self):
        """Unverified claims must produce descriptive error messages."""
        commentary = "Revenue was $999,999,999."
        facts = [{"amount": Decimal("100000")}]
        result = validate_commentary_claims(commentary, facts)
        assert len(result.errors) > 0
        assert "999,999,999" in result.errors[0]


# ── Monetary claim extraction ─────────────────────────────────────────────────


class TestExtractMonetaryClaims:
    def test_extracts_standard_format(self):
        """Must extract $X,XXX.XX formatted amounts."""
        text = "Revenue increased by $50,000 and costs decreased by $12,500."
        claims = extract_monetary_claims(text)
        amounts = {c.amount for c in claims}
        assert Decimal("50000") in amounts
        assert Decimal("12500") in amounts

    def test_ignores_zero_amounts(self):
        """$0 must be excluded — zero amounts are not meaningful claims."""
        text = "The variance was $0."
        claims = extract_monetary_claims(text)
        assert len(claims) == 0

    def test_extracts_large_numbers(self):
        """Must extract large amounts with commas."""
        text = "Total revenue was $12,345,678."
        claims = extract_monetary_claims(text)
        assert len(claims) >= 1
        # The claim amount will be the integer 12345678 (commas removed)
        assert any(c.amount == Decimal("12345678") for c in claims)

    def test_extracts_decimal_amounts(self):
        """Must extract amounts with cents."""
        text = "The cost was $1,234.56."
        claims = extract_monetary_claims(text)
        assert any(c.amount == Decimal("1234.56") for c in claims)

    def test_multiple_amounts_in_sentence(self):
        """Multiple monetary references in one sentence must all be captured."""
        text = "Revenue went from $100,000 to $120,000, an increase of $20,000."
        claims = extract_monetary_claims(text)
        assert len(claims) >= 3

    def test_position_tracking(self):
        """Each claim must record its position in the text."""
        text = "First $100 then $200."
        claims = extract_monetary_claims(text)
        positions = [c.position for c in claims]
        assert len(positions) == 2
        # $100 appears before $200
        assert positions[0] < positions[1]

    def test_no_dollar_amounts_returns_empty(self):
        """Text without dollar amounts must return empty list."""
        text = "Revenue increased significantly."
        claims = extract_monetary_claims(text)
        assert claims == []

    def test_amount_without_commas(self):
        """Amounts without commas must also be extracted."""
        text = "Amount was $50000."
        claims = extract_monetary_claims(text)
        assert any(c.amount == Decimal("50000") for c in claims)


# ── ValidationResult structure ────────────────────────────────────────────────


class TestValidationResultStructure:
    def test_result_has_expected_fields(self):
        """ValidationResult must have all required fields."""
        result = validate_commentary_claims("", [])
        assert isinstance(result, ValidationResult)
        assert hasattr(result, "is_valid")
        assert hasattr(result, "claims")
        assert hasattr(result, "verified_claims")
        assert hasattr(result, "unverified_claims")
        assert hasattr(result, "errors")

    def test_valid_result_no_errors(self):
        """Valid result must have empty errors list."""
        result = validate_commentary_claims("Revenue was $100,000.", [{"amount": Decimal("100000")}])
        assert result.is_valid
        assert result.errors == []

    def test_invalid_result_populated(self):
        """Invalid result must have populated errors."""
        result = validate_commentary_claims("Revenue was $999,999,999.", [])
        assert not result.is_valid
        assert len(result.errors) > 0


# ── Assertion validation ──────────────────────────────────────────────────────


class TestAssertionValidation:
    def test_numeric_with_evidence_passes(self):
        """Numeric assertion with evidence must pass."""
        a = Assertion(
            id="a1",
            type=AssertionType.NUMERIC,
            text="Revenue was $1.2M",
            value=Decimal("1200000"),
            evidence_ids=["ev-1"],
        )
        result = validate_assertion(a, evidence_count=1, source_count=1)
        assert result.is_valid
        assert result.adjusted_support_level == SupportLevel.VERIFIED

    def test_numeric_no_evidence_fails(self):
        """Numeric assertion without evidence must fail."""
        a = Assertion(
            id="a2",
            type=AssertionType.NUMERIC,
            text="Revenue was $1.2M",
            value=Decimal("1200000"),
            evidence_ids=[],
        )
        result = validate_assertion(a, evidence_count=0, source_count=0)
        assert not result.is_valid
        assert "must cite evidence" in str(result.errors)

    def test_numeric_no_value_fails(self):
        """Numeric assertion without value must fail."""
        a = Assertion(
            id="a3",
            type=AssertionType.NUMERIC,
            text="Something happened",
            value=None,
            evidence_ids=["ev-1"],
        )
        result = validate_assertion(a)
        assert not result.is_valid
        assert "must have a value" in str(result.errors)

    def test_causal_with_single_source_downgraded(self):
        """Causal assertion with only 1 evidence source must be PROBABLE at best."""
        a = Assertion(
            id="a4",
            type=AssertionType.CAUSAL,
            text="Driven by increased compute spend",
            evidence_ids=["ev-1"],
            support_level=SupportLevel.VERIFIED,
        )
        result = validate_assertion(a, evidence_count=1, source_count=1)
        assert result.is_valid is False
        assert result.adjusted_support_level == SupportLevel.INSUFFICIENT
        assert any("≥2 independent" in e for e in result.errors)

    def test_causal_with_two_sources_and_two_types_passes(self):
        """Causal assertion with 2+ evidence from 2+ sources must pass."""
        a = Assertion(
            id="a5",
            type=AssertionType.CAUSAL,
            text="Driven by increased compute spend",
            evidence_ids=["ev-1", "ev-2"],
            support_level=SupportLevel.VERIFIED,
        )
        result = validate_assertion(a, evidence_count=2, source_count=2)
        assert result.is_valid
        assert result.adjusted_support_level == SupportLevel.VERIFIED

    def test_hypothesis_never_verified(self):
        """Hypothesis assertions must max out at PROBABLE."""
        a = Assertion(
            id="a6",
            type=AssertionType.HYPOTHESIS,
            text="Possibly due to seasonal effects",
            evidence_ids=["ev-1"],
        )
        result = validate_assertion(a, evidence_count=1, source_count=1)
        assert result.is_valid
        assert result.adjusted_support_level == SupportLevel.PROBABLE
        assert result.adjusted_support_level != SupportLevel.VERIFIED

    def test_hypothesis_without_evidence_warns(self):
        """Hypothesis without evidence must generate a warning."""
        a = Assertion(
            id="a7",
            type=AssertionType.HYPOTHESIS,
            text="Maybe seasonal",
            evidence_ids=[],
        )
        result = validate_assertion(a)
        assert result.is_valid
        assert any("without evidence" in w for w in result.warnings)

    def test_comparative_with_fewer_than_2_evidence_fails(self):
        """Comparative assertion with fewer than 2 evidence must fail."""
        a = Assertion(
            id="a8",
            type=AssertionType.COMPARATIVE,
            text="Costs are 15% higher",
            value=Decimal("15.00"),
            evidence_ids=["ev-1"],
        )
        result = validate_assertion(a, evidence_count=1)
        assert result.is_valid is False
        assert any("ranked facts" in e for e in result.errors)

    def test_comparative_with_enough_evidence_passes(self):
        """Comparative with sufficient evidence must pass."""
        a = Assertion(
            id="a9",
            type=AssertionType.COMPARATIVE,
            text="Costs are 15% higher",
            value=Decimal("15.00"),
            evidence_ids=["ev-1", "ev-2", "ev-3"],
        )
        result = validate_assertion(a, evidence_count=3)
        assert result.is_valid

    def test_action_with_valid_template_passes(self):
        """Action assertion with allowed template must pass."""
        a = Assertion(
            id="a10",
            type=AssertionType.ACTION,
            text="Route for manager review",
            max_allowed_action="flag_for_approval",
        )
        result = validate_assertion(a)
        assert result.is_valid

    def test_action_with_invalid_template_fails(self):
        """Action assertion with invalid template must fail."""
        a = Assertion(
            id="a11",
            type=AssertionType.ACTION,
            text="Invalid action",
            max_allowed_action="not_an_allowed_template",
        )
        result = validate_assertion(a)
        assert not result.is_valid
        assert any("allowed template" in e for e in result.errors)

    def test_action_without_text_fails(self):
        """Action assertion without descriptive text must fail."""
        a = Assertion(
            id="a12",
            type=AssertionType.ACTION,
            text="",
            max_allowed_action="route_for_review",
        )
        result = validate_assertion(a)
        assert not result.is_valid
        assert "descriptive text" in str(result.errors)

    def test_unknown_assertion_type_fails(self):
        """Unknown assertion type must produce an error.

        Uses model_construct to bypass Pydantic's strict enum validation
        so we can test the assertion validator's fallback branch.
        """
        a = Assertion.model_construct(
            id="a13",
            type="unknown_type",  # bypasses Pydantic enum validation
            text="Some text",
        )
        result = validate_assertion(a)
        assert not result.is_valid
        assert "Unknown assertion type" in str(result.errors)

    def test_assertion_validation_result_structure(self):
        """AssertionValidationResult must have expected fields."""
        a = Assertion(
            id="a14",
            type=AssertionType.NUMERIC,
            text="Test",
            value=Decimal("42"),
            evidence_ids=["ev-1"],
        )
        result = validate_assertion(a)
        assert isinstance(result, AssertionValidationResult)
        assert hasattr(result, "is_valid")
        assert hasattr(result, "assertion_id")
        assert hasattr(result, "errors")
        assert hasattr(result, "warnings")
        assert hasattr(result, "adjusted_support_level")
