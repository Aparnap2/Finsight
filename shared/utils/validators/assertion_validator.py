from pydantic import BaseModel

from shared.models.assertions import Assertion, AssertionType, SupportLevel


class AssertionValidationResult(BaseModel):
    is_valid: bool
    assertion_id: str
    errors: list[str]
    warnings: list[str]
    adjusted_support_level: SupportLevel | None = None  # if downgraded


ALLOWED_ACTION_TEMPLATES: set[str] = {
    "route_for_review",
    "flag_for_approval",
    "auto_accept",
    "escalate_to_manager",
    "require_second_source",
}


def _validate_numeric(assertion: Assertion) -> AssertionValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    if assertion.value is None:
        errors.append("Numeric assertion must have a value")

    if not assertion.evidence_ids:
        errors.append("Numeric assertion must cite evidence")

    if len(assertion.evidence_ids) < 2:
        warnings.append("Numeric assertion with fewer than 2 evidence sources is weaker")

    adjusted = SupportLevel.VERIFIED if not errors else SupportLevel.INSUFFICIENT
    return AssertionValidationResult(
        is_valid=len(errors) == 0,
        assertion_id=assertion.id,
        errors=errors,
        warnings=warnings,
        adjusted_support_level=adjusted,
    )


def _validate_comparative(assertion: Assertion, evidence_count: int) -> AssertionValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    if assertion.value is None:
        errors.append("Comparative assertion requires a ranked value or delta")

    if evidence_count < 2:
        errors.append(
            "Comparative assertion must be provable from at least 2 ranked facts"
        )

    if not assertion.evidence_ids:
        errors.append("Comparative assertion must cite evidence")

    adjusted = SupportLevel.VERIFIED
    if errors:
        adjusted = SupportLevel.INSUFFICIENT
    elif evidence_count < 3:
        warnings.append("Comparative assertion with fewer than 3 data points is weaker")
        adjusted = SupportLevel.PROBABLE

    return AssertionValidationResult(
        is_valid=len(errors) == 0,
        assertion_id=assertion.id,
        errors=errors,
        warnings=warnings,
        adjusted_support_level=adjusted,
    )


def _validate_causal(
    assertion: Assertion, evidence_count: int, source_count: int
) -> AssertionValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    if evidence_count < 2:
        errors.append("Causal assertion needs ≥2 independent evidence sources")

    if source_count < 2:
        errors.append("Causal assertion needs ≥2 distinct source types")

    if not assertion.evidence_ids:
        errors.append("Causal assertion must cite evidence")

    adjusted = SupportLevel.PROBABLE if evidence_count >= 2 else SupportLevel.INSUFFICIENT
    if evidence_count >= 2 and source_count >= 2:
        adjusted = SupportLevel.VERIFIED

    return AssertionValidationResult(
        is_valid=len(errors) == 0,
        assertion_id=assertion.id,
        errors=errors,
        warnings=warnings,
        adjusted_support_level=adjusted,
    )


def _validate_hypothesis(assertion: Assertion) -> AssertionValidationResult:
    # Hypotheses are never VERIFIED, max PROBABLE
    warnings: list[str] = []

    if not assertion.evidence_ids:
        warnings.append("Hypothesis without evidence is purely speculative")

    if assertion.contradictions:
        warnings.append(f"Hypothesis has {len(assertion.contradictions)} contradiction(s)")

    return AssertionValidationResult(
        is_valid=True,
        assertion_id=assertion.id,
        errors=[],
        warnings=warnings,
        adjusted_support_level=SupportLevel.PROBABLE,
    )


def _validate_action(assertion: Assertion) -> AssertionValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    if assertion.max_allowed_action not in ALLOWED_ACTION_TEMPLATES:
        errors.append(
            f"Action assertion must map to an allowed template. "
            f"Got '{assertion.max_allowed_action}', expected one of {sorted(ALLOWED_ACTION_TEMPLATES)}"
        )

    if not assertion.text:
        errors.append("Action assertion must have descriptive text")

    if assertion.support_level == SupportLevel.INSUFFICIENT:
        warnings.append(
            "Action based on insufficient support level — consider increasing scrutiny"
        )

    adjusted = SupportLevel.VERIFIED if not errors else SupportLevel.INSUFFICIENT
    return AssertionValidationResult(
        is_valid=len(errors) == 0,
        assertion_id=assertion.id,
        errors=errors,
        warnings=warnings,
        adjusted_support_level=adjusted,
    )


def validate_assertion(
    assertion: Assertion,
    evidence_count: int = 0,
    source_count: int = 0,
) -> AssertionValidationResult:
    match assertion.type:
        case AssertionType.NUMERIC:
            return _validate_numeric(assertion)
        case AssertionType.COMPARATIVE:
            return _validate_comparative(assertion, evidence_count)
        case AssertionType.CAUSAL:
            return _validate_causal(assertion, evidence_count, source_count)
        case AssertionType.HYPOTHESIS:
            return _validate_hypothesis(assertion)
        case AssertionType.ACTION:
            return _validate_action(assertion)
        case _:
            return AssertionValidationResult(
                is_valid=False,
                assertion_id=assertion.id,
                errors=[f"Unknown assertion type: {assertion.type}"],
                warnings=[],
                adjusted_support_level=SupportLevel.INSUFFICIENT,
            )
