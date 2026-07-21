"""Tests for the data quality validation engine — 6 deterministic checks,
quality scoring, degraded mode propagation, and batch aggregation."""

import pytest

from backend.engine.data_quality import (
    DataQualityCheck,
    DataQualityReport,
    check_coverage,
    check_freshness,
    check_row_count,
    check_source_diversity,
    check_required_filters,
    check_quality_score,
    assess_tool_result,
    assess_batch,
    propagate_to_state,
    MAX_STALE_SECONDS,
)
from backend.models.degraded_mode import DegradedMode
from backend.tools.tool_result import ToolResult


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _make_tool_result(
    row_count: int = 100,
    coverage_pct: float = 1.0,
    quality_score: float = 1.0,
    freshness_seconds: int | None = 3600,
    source_diversity: int = 2,
    source_type: str = "financial_fact",
    retrieval_scope: str = "factual",
    tenant_id: str = "test-tenant",
    required_filters_present: bool = True,
    insufficient_data: bool = False,
    degraded_mode: str | None = None,
) -> ToolResult:
    return ToolResult(
        data=[{"account": "test"}],
        row_count=row_count,
        coverage_pct=coverage_pct,
        quality_score=quality_score,
        freshness_seconds=freshness_seconds,
        schema_version="1.0",
        source_diversity=source_diversity,
        source_type=source_type,
        retrieval_scope=retrieval_scope,
        tenant_id=tenant_id,
        required_filters_present=required_filters_present,
        insufficient_data=insufficient_data,
        degraded_mode=degraded_mode,
        query_fingerprint="abc123",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# COVERAGE_CHECK: coverage_pct < 0.5 → LOW_COVERAGE
# ═══════════════════════════════════════════════════════════════════════════════


class TestCheckCoverage:
    def test_check_coverage_passes_above_threshold(self):
        """coverage_pct >= 0.5 should pass."""
        result = _make_tool_result(coverage_pct=0.75)
        check = check_coverage(result)
        assert check.passed is True
        assert check.name == "coverage"

    def test_check_coverage_fails_below_threshold(self):
        """coverage_pct < 0.5 should fail with warning severity."""
        result = _make_tool_result(coverage_pct=0.3)
        check = check_coverage(result)
        assert check.passed is False
        assert check.severity == "warning"
        assert "below 50%" in check.detail

    def test_check_coverage_at_exact_threshold_passes(self):
        """coverage_pct exactly 0.5 should pass."""
        result = _make_tool_result(coverage_pct=0.5)
        check = check_coverage(result)
        assert check.passed is True

    def test_check_coverage_zero_pct(self):
        """coverage_pct of 0.0 should fail."""
        result = _make_tool_result(coverage_pct=0.0)
        check = check_coverage(result)
        assert check.passed is False


# ═══════════════════════════════════════════════════════════════════════════════
# FRESHNESS_CHECK: freshness_seconds > 90 days → STALE_SOURCE
# ═══════════════════════════════════════════════════════════════════════════════


class TestCheckFreshness:
    def test_check_freshness_passes_within_window(self):
        """freshness_seconds within 90 days should pass."""
        result = _make_tool_result(freshness_seconds=86400 * 30)  # 30 days
        check = check_freshness(result)
        assert check.passed is True

    def test_check_freshness_fails_when_stale(self):
        """freshness_seconds > 90 days should fail."""
        result = _make_tool_result(freshness_seconds=86400 * 91)  # 91 days
        check = check_freshness(result)
        assert check.passed is False
        assert check.severity == "warning"
        assert "91 days" in check.detail

    def test_check_freshness_returns_pass_when_none(self):
        """freshness_seconds is None should pass (no data to judge)."""
        result = _make_tool_result(freshness_seconds=None)
        check = check_freshness(result)
        assert check.passed is True

    def test_check_freshness_at_exact_threshold_passes(self):
        """freshness_seconds exactly 90 days should pass."""
        result = _make_tool_result(freshness_seconds=MAX_STALE_SECONDS)
        check = check_freshness(result)
        assert check.passed is True

    def test_check_freshness_very_stale(self):
        """Very stale data (>1 year) should fail with appropriate detail."""
        result = _make_tool_result(freshness_seconds=86400 * 400)  # 400 days
        check = check_freshness(result)
        assert check.passed is False
        assert "400 days" in check.detail


# ═══════════════════════════════════════════════════════════════════════════════
# ROW_COUNT_CHECK: row_count == 0 → warning/critical
# ═══════════════════════════════════════════════════════════════════════════════


class TestCheckRowCount:
    def test_check_row_count_passes_with_data(self):
        """row_count > 0 should pass."""
        result = _make_tool_result(row_count=50)
        check = check_row_count(result)
        assert check.passed is True
        assert "50 rows" in check.detail

    def test_check_row_count_fails_with_insufficient(self):
        """row_count == 0 and insufficient_data should be critical."""
        result = _make_tool_result(row_count=0, insufficient_data=True)
        check = check_row_count(result)
        assert check.passed is False
        assert check.severity == "critical"
        assert "insufficient_data" in check.detail

    def test_check_row_count_zero_without_insufficient_flag(self):
        """row_count == 0 without insufficient_data should be warning."""
        result = _make_tool_result(row_count=0, insufficient_data=False)
        check = check_row_count(result)
        assert check.passed is False
        assert check.severity == "warning"
        assert "0 rows" in check.detail


# ═══════════════════════════════════════════════════════════════════════════════
# SOURCE_DIVERSITY_CHECK: source_diversity < 2 → single-source
# ═══════════════════════════════════════════════════════════════════════════════


class TestCheckSourceDiversity:
    def test_check_source_diversity_passes_with_multiple(self):
        """source_diversity >= 2 should pass."""
        result = _make_tool_result(source_diversity=3)
        check = check_source_diversity(result)
        assert check.passed is True
        assert "Diversity=3" in check.detail

    def test_check_source_diversity_fails_with_one(self):
        """source_diversity < 2 should fail with info severity."""
        result = _make_tool_result(source_diversity=1)
        check = check_source_diversity(result)
        assert check.passed is False
        assert check.severity == "info"
        assert "Single source" in check.detail

    def test_check_source_diversity_zero(self):
        """source_diversity of 0 should fail."""
        result = _make_tool_result(source_diversity=0)
        check = check_source_diversity(result)
        assert check.passed is False


# ═══════════════════════════════════════════════════════════════════════════════
# REQUIRED_FILTERS_CHECK: required_filters_present == False
# ═══════════════════════════════════════════════════════════════════════════════


class TestCheckRequiredFilters:
    def test_check_required_filters_passes_when_present(self):
        """required_filters_present == True should pass."""
        result = _make_tool_result(required_filters_present=True)
        check = check_required_filters(result)
        assert check.passed is True

    def test_check_required_filters_fails_when_absent(self):
        """required_filters_present == False should be critical."""
        result = _make_tool_result(required_filters_present=False)
        check = check_required_filters(result)
        assert check.passed is False
        assert check.severity == "critical"
        assert "tenant_id, period" in check.detail


# ═══════════════════════════════════════════════════════════════════════════════
# QUALITY_SCORE_CHECK: quality_score < 0.5
# ═══════════════════════════════════════════════════════════════════════════════


class TestCheckQualityScore:
    def test_check_quality_score_passes_above(self):
        """quality_score >= 0.5 should pass."""
        result = _make_tool_result(quality_score=0.75)
        check = check_quality_score(result)
        assert check.passed is True
        assert "Score" in check.detail

    def test_check_quality_score_fails_below(self):
        """quality_score < 0.5 should fail with warning."""
        result = _make_tool_result(quality_score=0.3)
        check = check_quality_score(result)
        assert check.passed is False
        assert check.severity == "warning"
        assert "below 50%" in check.detail

    def test_check_quality_score_at_exact_threshold(self):
        """quality_score exactly 0.5 should pass."""
        result = _make_tool_result(quality_score=0.5)
        check = check_quality_score(result)
        assert check.passed is True

    def test_check_quality_score_zero(self):
        """quality_score of 0.0 should fail."""
        result = _make_tool_result(quality_score=0.0)
        check = check_quality_score(result)
        assert check.passed is False


# ═══════════════════════════════════════════════════════════════════════════════
# DataQualityCheck helper
# ═══════════════════════════════════════════════════════════════════════════════


class TestDataQualityCheck:
    def test_to_dict_returns_expected_keys(self):
        check = DataQualityCheck(
            name="coverage",
            passed=False,
            severity="warning",
            detail="Coverage 30% below 50% threshold",
        )
        d = check.to_dict()
        assert d["check"] == "coverage"
        assert d["passed"] is False
        assert d["severity"] == "warning"
        assert d["detail"] == "Coverage 30% below 50% threshold"


# ═══════════════════════════════════════════════════════════════════════════════
# DataQualityReport helper
# ═══════════════════════════════════════════════════════════════════════════════


class TestDataQualityReport:
    def test_passed_property_high_score(self):
        """overall_score >= 0.7 → passed is True."""
        report = DataQualityReport(overall_score=0.85)
        assert report.passed is True

    def test_passed_property_low_score(self):
        """overall_score < 0.7 → passed is False."""
        report = DataQualityReport(overall_score=0.5)
        assert report.passed is False

    def test_critical_issues_returns_only_critical_failures(self):
        checks = [
            DataQualityCheck(name="a", passed=True, severity="info"),
            DataQualityCheck(name="b", passed=False, severity="critical", detail="Bad"),
            DataQualityCheck(name="c", passed=False, severity="warning"),
            DataQualityCheck(name="d", passed=False, severity="critical", detail="Critical"),
        ]
        report = DataQualityReport(checks=checks)
        assert len(report.critical_issues) == 2
        assert all(c.name in ("b", "d") for c in report.critical_issues)

    def test_to_dict_returns_full_structure(self):
        checks = [
            DataQualityCheck(name="coverage", passed=True),
        ]
        report = DataQualityReport(
            checks=checks,
            overall_score=0.9,
            degraded_modes=["stale_source"],
            source_summary={"source_type": "financial_fact"},
        )
        d = report.to_dict()
        assert d["overall_score"] == 0.9
        assert d["passed"] is True
        assert d["degraded_modes"] == ["stale_source"]
        assert d["critical_issues"] == 0
        assert len(d["checks"]) == 1
        assert d["source_summary"]["source_type"] == "financial_fact"

    def test_default_construction(self):
        """Defaults should be safe for empty construction."""
        report = DataQualityReport()
        assert report.checks == []
        assert report.overall_score == 1.0
        assert report.degraded_modes == []
        assert report.source_summary == {}
        assert report.passed is True
        assert report.critical_issues == []


# ═══════════════════════════════════════════════════════════════════════════════
# assess_tool_result — full orchestration
# ═══════════════════════════════════════════════════════════════════════════════


class TestAssessToolResult:
    def test_assess_tool_result_generates_report(self):
        """Running all 6 checks on a high-quality result produces a passing report."""
        result = _make_tool_result(
            row_count=100,
            coverage_pct=0.95,
            quality_score=0.9,
            freshness_seconds=3600,
            source_diversity=3,
            required_filters_present=True,
            insufficient_data=False,
        )
        report = assess_tool_result(result)
        assert isinstance(report, DataQualityReport)
        assert len(report.checks) == 6
        assert report.passed is True
        assert report.overall_score > 0.7

    def test_assess_tool_result_degraded_on_low_coverage(self):
        """Low coverage (< 0.5) should produce LOW_COVERAGE degraded mode
        and the overall score should reflect the issue."""
        result = _make_tool_result(
            coverage_pct=0.3,
            quality_score=0.8,
        )
        report = assess_tool_result(result)
        assert DegradedMode.LOW_COVERAGE.value in report.degraded_modes
        # Blended score with good quality_score keeps it above 0.7; degraded
        # mode surfaces in the report regardless.
        assert report.overall_score < 0.8  # penalised below raw quality_score

    def test_assess_tool_result_degraded_on_stale_freshness(self):
        """Stale data (> 90 days) should produce STALE_SOURCE degraded mode."""
        result = _make_tool_result(freshness_seconds=86400 * 95)
        report = assess_tool_result(result)
        assert DegradedMode.STALE_SOURCE.value in report.degraded_modes

    def test_assess_tool_result_degraded_on_multiple_failures(self):
        """3+ failures should produce LOW_COVERAGE as catch-all degraded mode."""
        result = _make_tool_result(
            coverage_pct=0.3,
            quality_score=0.3,
            source_diversity=1,
            freshness_seconds=86400 * 95,
        )
        report = assess_tool_result(result)
        assert DegradedMode.LOW_COVERAGE.value in report.degraded_modes

    def test_assess_tool_result_critical_failure_triggers_degraded(self):
        """A critical failure (e.g., missing required_filters) triggers LOW_COVERAGE."""
        result = _make_tool_result(
            required_filters_present=False,
            coverage_pct=0.9,
            quality_score=0.9,
        )
        report = assess_tool_result(result)
        assert DegradedMode.LOW_COVERAGE.value in report.degraded_modes

    def test_assess_tool_result_source_summary_included(self):
        """The report includes a source_summary dictionary."""
        result = _make_tool_result(
            source_type="operational_metric",
            retrieval_scope="factual",
            tenant_id="tenant-42",
            row_count=75,
        )
        report = assess_tool_result(result)
        assert report.source_summary["source_type"] == "operational_metric"
        assert report.source_summary["retrieval_scope"] == "factual"
        assert report.source_summary["tenant_id"] == "tenant-42"
        assert report.source_summary["row_count"] == 75

    def test_assess_tool_result_all_checks_represented(self):
        """The report contains exactly 6 checks with expected names."""
        result = _make_tool_result()
        report = assess_tool_result(result)
        check_names = {c.name for c in report.checks}
        expected = {
            "coverage",
            "freshness",
            "row_count",
            "source_diversity",
            "required_filters",
            "quality_score",
        }
        assert check_names == expected


# ═══════════════════════════════════════════════════════════════════════════════
# assess_batch — batch aggregation
# ═══════════════════════════════════════════════════════════════════════════════


class TestAssessBatch:
    def test_assess_batch_empty_returns_degraded(self):
        """An empty batch should produce a LOW_COVERAGE degraded mode."""
        report = assess_batch([])
        assert DegradedMode.LOW_COVERAGE.value in report.degraded_modes
        assert report.overall_score == 0.0

    def test_assess_batch_empty_has_batch_empty_check(self):
        """An empty batch has a 'batch_empty' check."""
        report = assess_batch([])
        assert len(report.checks) == 1
        assert report.checks[0].name == "batch_empty"
        assert report.checks[0].passed is True

    def test_assess_batch_aggregates_multiple_results(self):
        """Multiple results should be aggregated with combined checks."""
        r1 = _make_tool_result(
            quality_score=0.9, coverage_pct=0.95,
        )
        r2 = _make_tool_result(
            quality_score=0.8, coverage_pct=0.85,
        )
        report = assess_batch([r1, r2])
        # 2 results × 6 checks each = 12 total
        assert len(report.checks) == 12
        assert report.overall_score > 0.0
        assert report.source_summary["batch_size"] == 2

    def test_assess_batch_deducts_for_degraded_modes(self):
        """Each unique degraded mode deducts 0.1 from overall_score."""
        r1 = _make_tool_result(
            quality_score=1.0, coverage_pct=0.3,
        )
        r2 = _make_tool_result(
            quality_score=1.0, freshness_seconds=86400 * 95,
        )
        report = assess_batch([r1, r2])
        # Two unique degraded modes: LOW_COVERAGE and STALE_SOURCE
        # Base avg quality = 1.0, deduct 2 × 0.1 = 0.2 → overall = 0.8
        assert report.overall_score == pytest.approx(0.8)
        assert DegradedMode.LOW_COVERAGE.value in report.degraded_modes
        assert DegradedMode.STALE_SOURCE.value in report.degraded_modes

    def test_assess_batch_overall_score_never_below_zero(self):
        """Overall score should be clamped at 0.0 minimum."""
        r1 = _make_tool_result(quality_score=0.05, coverage_pct=0.0)
        report = assess_batch([r1])
        # Base avg = 0.05, deduct 0.1 for LOW_COVERAGE → -0.05 → clamped to 0.0
        assert report.overall_score >= 0.0

    def test_assess_batch_collects_source_types(self):
        """Source summary includes distinct source types from all results."""
        r1 = _make_tool_result(source_type="financial_fact")
        r2 = _make_tool_result(source_type="operational_metric")
        report = assess_batch([r1, r2])
        assert "financial_fact" in report.source_summary["source_types"]
        assert "operational_metric" in report.source_summary["source_types"]

    def test_assess_batch_deduplicates_degraded_modes(self):
        """Duplicate degraded modes across results should be deduped."""
        r1 = _make_tool_result(coverage_pct=0.3, freshness_seconds=86400 * 95)
        r2 = _make_tool_result(coverage_pct=0.2, freshness_seconds=86400 * 100)
        report = assess_batch([r1, r2])
        # Both have LOW_COVERAGE and STALE_SOURCE → should dedupe to 2 unique
        assert len(report.degraded_modes) == 2
        assert DegradedMode.LOW_COVERAGE.value in report.degraded_modes
        assert DegradedMode.STALE_SOURCE.value in report.degraded_modes

    def test_assess_batch_degraded_modes_sorted(self):
        """Degraded modes in batch report are sorted alphabetically."""
        r1 = _make_tool_result(freshness_seconds=86400 * 95)
        r2 = _make_tool_result(coverage_pct=0.3)
        report = assess_batch([r1, r2])
        assert report.degraded_modes == sorted(report.degraded_modes)


# ═══════════════════════════════════════════════════════════════════════════════
# propagate_to_state — PipelineState integration
# ═══════════════════════════════════════════════════════════════════════════════


class TestPropagateToState:
    def test_propagate_to_state_adds_quality_key(self):
        """Propagating a report adds 'data_quality' key to state."""
        state: dict = {
            "period": "2024-Q1",
            "entity_id": "ent-1",
            "current_step": "ingestion",
        }
        report = DataQualityReport(
            overall_score=0.9,
            checks=[DataQualityCheck(name="coverage", passed=True)],
        )
        result = propagate_to_state(state, report)  # type: ignore[arg-type]
        assert "data_quality" in result
        assert result["data_quality"]["overall_score"] == 0.9
        assert result["data_quality"]["passed"] is True

    def test_propagate_to_state_merges_degraded_modes(self):
        """Degraded modes are merged into state's 'degraded_modes' key."""
        state: dict = {
            "period": "2024-Q1",
            "entity_id": "ent-1",
            "degraded_modes": ["stale_source"],
        }
        report = DataQualityReport(
            overall_score=0.5,
            degraded_modes=["low_coverage", "stale_source"],
        )
        result = propagate_to_state(state, report)  # type: ignore[arg-type]
        assert "low_coverage" in result["degraded_modes"]
        assert "stale_source" in result["degraded_modes"]
        assert len(result["degraded_modes"]) == 2  # deduped

    def test_propagate_to_state_no_degraded_modes_key_when_none(self):
        """If report has no degraded modes, state keeps existing key unchanged."""
        state: dict = {
            "period": "2024-Q1",
            "entity_id": "ent-1",
            "degraded_modes": ["some_existing"],
        }
        report = DataQualityReport(overall_score=0.9)
        result = propagate_to_state(state, report)  # type: ignore[arg-type]
        assert "some_existing" in result["degraded_modes"]
        assert len(result["degraded_modes"]) == 1

    def test_propagate_to_state_creates_degraded_modes_key(self):
        """If state has no degraded_modes key, it is created."""
        state: dict = {
            "period": "2024-Q1",
            "entity_id": "ent-1",
        }
        report = DataQualityReport(
            overall_score=0.4,
            degraded_modes=["low_coverage"],
        )
        result = propagate_to_state(state, report)  # type: ignore[arg-type]
        assert "degraded_modes" in result
        assert result["degraded_modes"] == ["low_coverage"]

    def test_propagate_to_state_preserves_other_state_keys(self):
        """Existing state keys should be preserved unchanged."""
        state: dict = {
            "period": "2024-Q1",
            "entity_id": "ent-1",
            "current_step": "ingestion",
            "variances": [],
        }
        report = DataQualityReport(overall_score=1.0)
        result = propagate_to_state(state, report)  # type: ignore[arg-type]
        assert result["period"] == "2024-Q1"
        assert result["entity_id"] == "ent-1"
        assert result["current_step"] == "ingestion"
        assert result["variances"] == []

    def test_propagate_to_state_returns_same_state_object(self):
        """propagate_to_state should mutate and return the original state dict."""
        state: dict = {"period": "2024-Q1", "entity_id": "ent-1"}
        report = DataQualityReport(overall_score=0.8)
        result = propagate_to_state(state, report)  # type: ignore[arg-type]
        assert result is state  # same object
