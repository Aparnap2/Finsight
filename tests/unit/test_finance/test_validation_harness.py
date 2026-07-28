"""TDD tests for Phase 7 — Validation Harness.

Unified validation interface: common results, validator protocol, composite suites.
Wraps existing validators (PeriodValidator, DataQuality checks) into the harness.
"""
from __future__ import annotations

import pytest
from datetime import date
from pydantic import BaseModel


# ── ValidationResult ─────────────────────────────────────────────────────────


class TestValidationResult:
    """ValidationResult is the common result model for all validators."""

    def test_result_creation(self):
        """Create a ValidationResult with basic fields."""
        from finance.validation.harness import ValidationResult
        r = ValidationResult(
            validator_name="test_validator",
            is_valid=True,
            messages=["All checks passed"],
        )
        assert r.validator_name == "test_validator"
        assert r.is_valid is True
        assert len(r.messages) == 1

    def test_result_with_severity(self):
        """ValidationResult supports severity levels: error, warning, info."""
        from finance.validation.harness import ValidationResult
        r = ValidationResult(
            validator_name="coverage",
            is_valid=False,
            messages=["Coverage below 50%"],
            severity="warning",
        )
        assert r.severity == "warning"

    def test_result_defaults(self):
        """ValidationResult has sensible defaults."""
        from finance.validation.harness import ValidationResult
        r = ValidationResult(validator_name="check", is_valid=True)
        assert r.severity == "error"
        assert r.messages == []

    def test_result_with_metadata(self):
        """ValidationResult accepts optional metadata dict."""
        from finance.validation.harness import ValidationResult
        r = ValidationResult(
            validator_name="coverage",
            is_valid=True,
            metadata={"coverage_pct": 0.85, "threshold": 0.5},
        )
        assert r.metadata["coverage_pct"] == 0.85


# ── Validator Protocol / Base ────────────────────────────────────────────────


class TestValidatorProtocol:
    """All validators implement a common interface."""

    def test_validator_protocol_exists(self):
        """Validator is a Protocol class with a validate() method."""
        from finance.validation.harness import Validator
        assert hasattr(Validator, "validate")

    def test_concrete_validator_conforms(self):
        """A concrete validator can be created that satisfies the protocol."""
        from finance.validation.harness import ValidationResult, Validator

        class MyValidator:
            def validate(self, **kwargs) -> ValidationResult:
                return ValidationResult(
                    validator_name="my", is_valid=True, messages=["OK"]
                )

        v: Validator = MyValidator()
        result = v.validate()
        assert result.is_valid is True

    def test_validator_can_be_parametrized(self):
        """Validators accept configuration at construction time."""
        from finance.validation.harness import ValidationResult, Validator

        class ThresholdValidator:
            def __init__(self, name: str, threshold: float):
                self.name = name
                self.threshold = threshold

            def validate(self, **kwargs) -> ValidationResult:
                value = kwargs.get("value", 0)
                return ValidationResult(
                    validator_name=self.name,
                    is_valid=value >= self.threshold,
                    messages=[f"Value {value} >= threshold {self.threshold}"]
                    if value >= self.threshold
                    else [f"Value {value} < threshold {self.threshold}"],
                )

        v: Validator = ThresholdValidator("pct_check", 0.5)
        r1 = v.validate(value=0.8)
        assert r1.is_valid is True
        r2 = v.validate(value=0.2)
        assert r2.is_valid is False


# ── ValidationSuite ──────────────────────────────────────────────────────────


class TestValidationSuite:
    """ValidationSuite runs multiple validators and aggregates results."""

    def test_suite_runs_all_validators(self):
        """Suite runs all registered validators and returns all results."""
        from finance.validation.harness import ValidationResult, Validator, ValidationSuite

        class AlwaysPass:
            def validate(self, **kwargs) -> ValidationResult:
                return ValidationResult(validator_name="pass", is_valid=True)

        class AlwaysFail:
            def validate(self, **kwargs) -> ValidationResult:
                return ValidationResult(validator_name="fail", is_valid=False, messages=["Failed"])

        suite = ValidationSuite(validators=[AlwaysPass(), AlwaysFail()])
        report = suite.run()
        assert len(report.results) == 2
        assert report.passed is False

    def test_suite_passes_when_all_pass(self):
        """Suite.passed is True when all validators pass."""
        from finance.validation.harness import ValidationResult, Validator, ValidationSuite

        class AlwaysPass:
            def validate(self, **kwargs) -> ValidationResult:
                return ValidationResult(validator_name="p", is_valid=True)

        suite = ValidationSuite(validators=[AlwaysPass(), AlwaysPass()])
        assert suite.run().passed is True

    def test_suite_includes_report_metadata(self):
        """ValidationReport includes total, passed, failed counts."""
        from finance.validation.harness import ValidationResult, Validator, ValidationSuite

        class Flip:
            def __init__(self, name: str, valid: bool):
                self.name = name
                self.valid = valid
            def validate(self, **kwargs) -> ValidationResult:
                return ValidationResult(validator_name=self.name, is_valid=self.valid)

        suite = ValidationSuite(validators=[
            Flip("a", True), Flip("b", False), Flip("c", True),
        ])
        report = suite.run()
        assert report.total == 3
        assert report.passed_count == 2
        assert report.failed_count == 1
        assert report.passed is False

    def test_suite_empty(self):
        """Empty suite is trivially passing."""
        from finance.validation.harness import ValidationSuite
        suite = ValidationSuite()
        report = suite.run()
        assert report.passed is True
        assert report.total == 0


# ── Adapter for Existing Validators ──────────────────────────────────────────


class TestValidatorAdapter:
    """Adapter wraps existing validators into the common Validator protocol."""

    def test_wraps_period_validator(self):
        """ValidatorAdapter wraps PeriodValidator.validate_period."""
        from finance.validation.harness import Validator, ValidatorAdapter, ValidationSuite
        from finance.validation.calendar import FiscalCalendar
        from finance.validation.models import FiscalPeriod, PeriodType, PeriodStatus
        from finance.validation.validator import PeriodValidator

        cal = FiscalCalendar()
        cal.generate_periods(2026, PeriodType.MONTHLY)

        adapter = ValidatorAdapter(
            name="period_validator",
            validator_fn=lambda: PeriodValidator().validate_year(
                year=2026, calendar=cal
            ),
        )
        result = adapter.validate()
        assert result.validator_name == "period_validator"
        # Should be a ValidationResult

    def test_wraps_data_quality_checks(self):
        """ValidatorAdapter wraps data quality check functions."""
        from finance.validation.harness import Validator, ValidatorAdapter, ValidationSuite
        from finance.validation.data_quality import check_freshness
        from shared.utils.tools.tool_result import ToolResult

        result = ToolResult(
            source_type="financial_fact",
            retrieval_scope="factual",
            tenant_id="test",
            row_count=100,
            quality_score=0.9,
            coverage_pct=1.0,
            source_diversity=3,
            required_filters_present=True,
            data=[],
            freshness_seconds=3600,
            schema_version="1.0",
            insufficient_data=False,
            degraded_mode=None,
            query_fingerprint=None,
        )

        adapter = ValidatorAdapter(
            name="freshness",
            validator_fn=lambda: check_freshness(result),
        )
        vr = adapter.validate()
        assert vr.validator_name == "freshness"

    def test_suite_with_mixed_validators(self):
        """Suite can run both native and adapted validators together."""
        from finance.validation.harness import (
            ValidationResult, Validator, ValidatorAdapter, ValidationSuite,
        )

        class NativePass:
            def validate(self, **kwargs) -> ValidationResult:
                return ValidationResult(validator_name="native", is_valid=True)

        adapter = ValidatorAdapter(
            name="adapted",
            validator_fn=lambda: ValidationResult(validator_name="adapted", is_valid=True),
        )

        suite = ValidationSuite(validators=[NativePass(), adapter])
        report = suite.run()
        assert report.passed is True
        assert report.total == 2


# ── DataQuality Validator (reusable check) ───────────────────────────────────


class TestDataQualityValidator:
    """DataQualityValidator runs the 6 standard checks in harness form."""

    def test_dq_validator_runs_all_checks(self):
        """DataQualityValidator runs all 6 checks and returns aggregated result."""
        from finance.validation.harness import DataQualityValidator
        from shared.utils.tools.tool_result import ToolResult

        result = ToolResult(
            source_type="financial_fact",
            retrieval_scope="factual",
            tenant_id="test",
            row_count=100,
            quality_score=0.9,
            coverage_pct=1.0,
            source_diversity=3,
            required_filters_present=True,
            data=[],
            freshness_seconds=3600,
            schema_version="1.0",
            insufficient_data=False,
            degraded_mode=None,
            query_fingerprint=None,
        )

        dqv = DataQualityValidator()
        vr = dqv.validate(tool_result=result)
        assert vr.validator_name == "data_quality"
        assert vr.is_valid is True

    def test_dq_validator_detects_issues(self):
        """DataQualityValidator flags failing checks."""
        from finance.validation.harness import DataQualityValidator
        from shared.utils.tools.tool_result import ToolResult

        result = ToolResult(
            source_type="financial_fact",
            retrieval_scope="factual",
            tenant_id="test",
            row_count=0,
            quality_score=0.3,
            coverage_pct=0.2,
            source_diversity=1,
            required_filters_present=False,
            insufficient_data=True,
            data=[],
            freshness_seconds=3600,
            schema_version="1.0",
            degraded_mode=None,
            query_fingerprint=None,
        )

        dqv = DataQualityValidator()
        vr = dqv.validate(tool_result=result)
        assert vr.validator_name == "data_quality"
        assert vr.is_valid is False
        assert len(vr.messages) > 0


# ── ValidationReport Serialization ───────────────────────────────────────────


class TestValidationReport:
    """ValidationReport can be serialized and deserialized."""

    def test_report_to_dict(self):
        """ValidationReport.to_dict() returns a JSON-serializable dict."""
        from finance.validation.harness import ValidationResult, ValidationSuite

        class Pass:
            def validate(self, **kwargs) -> ValidationResult:
                return ValidationResult(validator_name="p", is_valid=True, messages=["OK"])

        suite = ValidationSuite(validators=[Pass()])
        report = suite.run()
        d = report.to_dict()
        assert d["passed"] is True
        assert d["total"] == 1
        assert len(d["results"]) == 1
        assert d["results"][0]["validator_name"] == "p"

    def test_report_to_dict_with_failures(self):
        """to_dict captures failure details."""
        from finance.validation.harness import ValidationResult, ValidationSuite

        class Fail:
            def validate(self, **kwargs) -> ValidationResult:
                return ValidationResult(
                    validator_name="f", is_valid=False, messages=["Failed"],
                    severity="critical", metadata={"key": "val"},
                )

        suite = ValidationSuite(validators=[Fail()])
        d = suite.run().to_dict()
        assert d["passed"] is False
        assert len(d["failures"]) == 1
        assert d["failures"][0]["severity"] == "critical"
