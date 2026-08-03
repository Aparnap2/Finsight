from __future__ import annotations

from pydantic import BaseModel


class ValidationResult(BaseModel):
    is_valid: bool
    errors: list[str]


class ResponseValidator:
    def validate(
        self,
        output: BaseModel,
        expected_schema: type[BaseModel],
    ) -> ValidationResult:
        if isinstance(output, expected_schema):
            return ValidationResult(is_valid=True, errors=[])
        return ValidationResult(is_valid=False, errors=["Output does not match expected schema"])

    def validate_evidence(
        self,
        claim: str,
        evidence_ids: list[str],
        min_evidence: int = 1,
    ) -> ValidationResult:
        errors: list[str] = []
        if len(evidence_ids) < min_evidence:
            errors.append(f"Claim requires at least {min_evidence} evidence source(s), got {len(evidence_ids)}")
        return ValidationResult(is_valid=len(errors) == 0, errors=errors)
