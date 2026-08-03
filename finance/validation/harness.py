"""Phase 7 — Validation Harness.

Unified validation interface: common result model, validator protocol,
adapter for wrapping existing validators, and composite validation suites.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from pydantic import BaseModel

# ── ValidationResult ───────────────────────────────────────────────────────────


class ValidationResult(BaseModel):
    """Common result model for all validators.

    Attributes:
        validator_name: Name of the validator that produced this result.
        is_valid: Whether the check(s) passed.
        messages: Human-readable messages describing the result.
        severity: Severity level — "error", "warning", or "info".
        metadata: Arbitrary key-value pairs for additional context.
    """

    validator_name: str
    is_valid: bool
    messages: list[str] = []
    severity: str = "error"
    metadata: dict[str, Any] = {}


# ── Validator Protocol ─────────────────────────────────────────────────────────


class Validator(Protocol):
    """Protocol that all validators must satisfy.

    Duck-typed: any object with a ``validate(**kwargs) -> ValidationResult``
    method is a Validator.
    """

    def validate(self, **kwargs: Any) -> ValidationResult:  # pragma: no cover
        ...


# ── ValidationReport ───────────────────────────────────────────────────────────


class ValidationReport(BaseModel):
    """Aggregated results from running a ValidationSuite.

    Attributes:
        results: The list of individual ValidationResult objects.
        total: Total number of results (computed).
        passed_count: Number of results with is_valid=True (computed).
        failed_count: Number of results with is_valid=False (computed).
        passed: True when *all* results have is_valid=True (computed).
    """

    results: list[ValidationResult]

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.results if r.is_valid)

    @property
    def failed_count(self) -> int:
        return self.total - self.passed_count

    @property
    def passed(self) -> bool:
        return all(r.is_valid for r in self.results)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict representation."""
        return {
            "passed": self.passed,
            "total": self.total,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "results": [r.model_dump() for r in self.results],
            "failures": [
                r.model_dump() for r in self.results if not r.is_valid
            ],
        }


# ── ValidationSuite ────────────────────────────────────────────────────────────


class ValidationSuite:
    """Composite validator that runs a collection of Validators and aggregates
    their results into a single ValidationReport.
    """

    def __init__(self, validators: list[Validator] | None = None) -> None:
        self._validators: list[Validator] = list(validators) if validators else []

    def add(self, validator: Validator) -> None:
        """Register an additional validator."""
        self._validators.append(validator)

    def run(self, **kwargs: Any) -> ValidationReport:
        """Run all registered validators and return an aggregated report."""
        results = [v.validate(**kwargs) for v in self._validators]
        return ValidationReport(results=results)

    @property
    def passed(self) -> bool:
        """Shortcut — run an empty kwargs check and return whether all passed."""
        return self.run().passed


# ── ValidatorAdapter ────────────────────────────────────────────────────────────


class ValidatorAdapter:
    """Adapts an existing callable into the Validator protocol.

    Wraps any function or callable so it can be used inside a ValidationSuite.
    The adapter handles three cases when ``validate()`` is called:

    1. The wrapped function returns a ``ValidationResult`` — returned as-is.
    2. The wrapped function returns something with an ``is_valid`` attribute
       (e.g. a ``DataQualityReport`` or ``DataQualityCheck``) — adapted.
    3. The wrapped function raises an exception — caught and returned as a
       non-valid ``ValidationResult``.
    """

    def __init__(self, name: str, validator_fn: Callable[..., Any]) -> None:
        self._name = name
        self._fn = validator_fn

    def validate(self, **kwargs: Any) -> ValidationResult:
        """Call the wrapped function and adapt its return value."""
        try:
            raw = self._fn(**kwargs)
        except Exception as exc:
            return ValidationResult(
                validator_name=self._name,
                is_valid=False,
                messages=[f"Validator raised exception: {exc}"],
            )

        # Case 1: already a ValidationResult
        if isinstance(raw, ValidationResult):
            return raw

        # Case 2: duck-typed object with is_valid (DataQualityReport etc.)
        if hasattr(raw, "is_valid"):
            messages: list[str] = []
            # If it has a 'checks' list, collect details from failing checks
            if hasattr(raw, "checks"):
                for check in raw.checks:
                    if not check.passed:
                        detail = getattr(check, "detail", "") or getattr(check, "name", "")
                        messages.append(detail)
            # If it's a single DataQualityCheck
            if (
                hasattr(raw, "detail")
                and not raw.passed
                and raw.detail
                and raw.detail not in messages
            ):
                messages.append(raw.detail)

            return ValidationResult(
                validator_name=self._name,
                is_valid=bool(raw.is_valid),
                messages=messages,
                severity=getattr(raw, "severity", "error"),
            )

        # Fallback: truthy → valid
        return ValidationResult(
            validator_name=self._name,
            is_valid=bool(raw),
        )


# ── DataQualityValidator ────────────────────────────────────────────────────────


class DataQualityValidator:
    """Runs all 6 standard data-quality checks and returns a single aggregated
    ValidationResult.

    Imports the free check functions from ``finance.validation.data_quality``
    and runs each against the provided ``tool_result``.
    """

    def __init__(self) -> None:
        from finance.validation.data_quality import (
            check_coverage,
            check_freshness,
            check_quality_score,
            check_required_filters,
            check_row_count,
            check_source_diversity,
        )

        self._checks = [
            check_coverage,
            check_freshness,
            check_quality_score,
            check_required_filters,
            check_row_count,
            check_source_diversity,
        ]

    def validate(
        self,
        tool_result: Any = None,
        **kwargs: Any,
    ) -> ValidationResult:
        """Run all 6 checks and return an aggregated result.

        The ``tool_result`` keyword argument is passed to each check function.
        """
        messages: list[str] = []
        overall_valid = True

        for check_fn in self._checks:
            check_result = check_fn(tool_result)
            if not check_result.passed:
                overall_valid = False
                messages.append(check_result.detail)

        return ValidationResult(
            validator_name="data_quality",
            is_valid=overall_valid,
            messages=messages,
        )
