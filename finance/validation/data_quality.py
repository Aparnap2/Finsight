"""Data quality validation engine.

Runs 6 deterministic checks on ToolResults and computes:
1. Overall quality score
2. Active degraded modes
3. Per-check breakdown for auditability

Checks:
- COVERAGE_CHECK: coverage_pct < 0.5 → LOW_COVERAGE
- FRESHNESS_CHECK: freshness_seconds > 90 days → STALE_SOURCE
- ROW_COUNT_CHECK: row_count == 0 and not expected → INSUFFICIENT_DATA
- SOURCE_DIVERSITY_CHECK: source_diversity < 2 → single-source warning
- REQUIRED_FILTERS_CHECK: required_filters_present == False → missing scoping
- QUALITY_SCORE_CHECK: quality_score < 0.5 → low quality data
"""

from datetime import UTC, datetime
from typing import Any

from shared.models.degraded_mode import DegradedMode
from shared.models.state import PipelineState
from shared.utils.tools.tool_result import ToolResult

MAX_STALE_SECONDS = 86400 * 90  # 90 days

DATETIME_UTC_NOW = datetime.now(UTC)


class DataQualityCheck:
    """Result of a single data quality check."""

    def __init__(
        self,
        name: str,
        passed: bool,
        severity: str = "info",
        detail: str = "",
    ):
        self.name = name
        self.passed = passed
        self.severity = severity  # "critical", "warning", "info"
        self.detail = detail

    def to_dict(self) -> dict[str, Any]:
        return {
            "check": self.name,
            "passed": self.passed,
            "severity": self.severity,
            "detail": self.detail,
        }


class DataQualityReport:
    """Report from running all 6 quality checks on a batch of ToolResults."""

    def __init__(
        self,
        checks: list[DataQualityCheck] | None = None,
        overall_score: float = 1.0,
        degraded_modes: list[str] | None = None,
        source_summary: dict[str, Any] | None = None,
    ):
        self.checks = checks or []
        self.overall_score = overall_score
        self.degraded_modes = degraded_modes or []
        self.source_summary = source_summary or {}

    @property
    def passed(self) -> bool:
        return self.overall_score >= 0.7

    @property
    def critical_issues(self) -> list[DataQualityCheck]:
        return [c for c in self.checks if c.severity == "critical" and not c.passed]

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_score": self.overall_score,
            "passed": self.passed,
            "degraded_modes": self.degraded_modes,
            "critical_issues": len(self.critical_issues),
            "checks": [c.to_dict() for c in self.checks],
            "source_summary": self.source_summary,
        }


def check_coverage(result: ToolResult) -> DataQualityCheck:
    """COVERAGE_CHECK: coverage_pct < 0.5 → LOW_COVERAGE."""
    if result.coverage_pct < 0.5:
        return DataQualityCheck(
            name="coverage",
            passed=False,
            severity="warning",
            detail=f"Coverage {result.coverage_pct:.0%} below 50% threshold",
        )
    return DataQualityCheck(
        name="coverage",
        passed=True,
        detail=f"Coverage {result.coverage_pct:.0%}",
    )


def check_freshness(result: ToolResult) -> DataQualityCheck:
    """FRESHNESS_CHECK: freshness_seconds > 90 days → STALE_SOURCE."""
    if result.freshness_seconds is not None and result.freshness_seconds > MAX_STALE_SECONDS:
        stale_days = result.freshness_seconds // 86400
        return DataQualityCheck(
            name="freshness",
            passed=False,
            severity="warning",
            detail=f"Data is {stale_days} days old, exceeds 90 day threshold",
        )
    return DataQualityCheck(name="freshness", passed=True)


def check_row_count(result: ToolResult) -> DataQualityCheck:
    """ROW_COUNT_CHECK: row_count == 0 and not expected → insufficient data."""
    if result.row_count == 0 and result.insufficient_data:
        return DataQualityCheck(
            name="row_count",
            passed=False,
            severity="critical",
            detail="Query returned 0 rows with insufficient_data flag",
        )
    if result.row_count == 0:
        return DataQualityCheck(
            name="row_count",
            passed=False,
            severity="warning",
            detail="Query returned 0 rows",
        )
    return DataQualityCheck(
        name="row_count",
        passed=True,
        detail=f"{result.row_count} rows returned",
    )


def check_source_diversity(result: ToolResult) -> DataQualityCheck:
    """SOURCE_DIVERSITY_CHECK: source_diversity < 2 → single-source."""
    if result.source_diversity < 2:
        return DataQualityCheck(
            name="source_diversity",
            passed=False,
            severity="info",
            detail=f"Single source (diversity={result.source_diversity})",
        )
    return DataQualityCheck(
        name="source_diversity",
        passed=True,
        detail=f"Diversity={result.source_diversity}",
    )


def check_required_filters(result: ToolResult) -> DataQualityCheck:
    """REQUIRED_FILTERS_CHECK: required_filters_present == False."""
    if not result.required_filters_present:
        return DataQualityCheck(
            name="required_filters",
            passed=False,
            severity="critical",
            detail="Required filters (tenant_id, period) not applied",
        )
    return DataQualityCheck(name="required_filters", passed=True)


def check_quality_score(result: ToolResult) -> DataQualityCheck:
    """QUALITY_SCORE_CHECK: quality_score < 0.5."""
    if result.quality_score < 0.5:
        return DataQualityCheck(
            name="quality_score",
            passed=False,
            severity="warning",
            detail=f"Quality score {result.quality_score:.0%} below 50%",
        )
    return DataQualityCheck(
        name="quality_score",
        passed=True,
        detail=f"Score {result.quality_score:.0%}",
    )


ALL_CHECKS = [
    check_coverage,
    check_freshness,
    check_row_count,
    check_source_diversity,
    check_required_filters,
    check_quality_score,
]


def assess_tool_result(result: ToolResult) -> DataQualityReport:
    """Run all 6 checks on a single ToolResult."""
    checks = [check(result) for check in ALL_CHECKS]

    # Determine degraded mode from worst check
    degraded_modes = []
    failure_count = sum(1 for c in checks if not c.passed)
    critical_failures = sum(1 for c in checks if not c.passed and c.severity == "critical")

    if critical_failures > 0 or failure_count >= 3:
        degraded_modes.append(DegradedMode.LOW_COVERAGE.value)
    if any(c.name == "freshness" and not c.passed for c in checks):
        degraded_modes.append(DegradedMode.STALE_SOURCE.value)
    if any(c.name == "coverage" and not c.passed for c in checks):
        degraded_modes.append(DegradedMode.LOW_COVERAGE.value)

    # Compute overall score as weighted average of passed checks
    weights = {"critical": 0.3, "warning": 0.2, "info": 0.1}
    total_weight = sum(weights.get(c.severity, 0.1) for c in checks)
    passed_weight = sum(weights.get(c.severity, 0.1) for c in checks if c.passed)
    overall_score = (passed_weight / total_weight) if total_weight > 0 else 0.0

    # Blend with tool's own quality_score
    overall_score = (overall_score + result.quality_score) / 2.0

    return DataQualityReport(
        checks=checks,
        overall_score=round(overall_score, 4),
        degraded_modes=list(set(degraded_modes)),
        source_summary={
            "source_type": result.source_type,
            "retrieval_scope": result.retrieval_scope,
            "tenant_id": result.tenant_id,
            "row_count": result.row_count,
        },
    )


def assess_batch(tool_results: list[ToolResult]) -> DataQualityReport:
    """Run all 6 checks on a batch of ToolResults and aggregate."""
    if not tool_results:
        return DataQualityReport(
            checks=[
                DataQualityCheck(
                    name="batch_empty",
                    passed=True,
                    detail="No tool results to assess",
                )
            ],
            overall_score=0.0,
            degraded_modes=[DegradedMode.LOW_COVERAGE.value],
        )

    all_degraded = []
    all_checks = []
    quality_scores = []

    for result in tool_results:
        report = assess_tool_result(result)
        all_checks.extend(report.checks)
        all_degraded.extend(report.degraded_modes)
        quality_scores.append(result.quality_score)

    overall_score = sum(quality_scores) / len(quality_scores) if quality_scores else 0.0
    # Deduct for each degraded mode
    unique_degraded = set(all_degraded)
    overall_score -= 0.1 * len(unique_degraded)
    overall_score = max(0.0, overall_score)

    return DataQualityReport(
        checks=all_checks,
        overall_score=round(overall_score, 4),
        degraded_modes=sorted(unique_degraded),
        source_summary={
            "batch_size": len(tool_results),
            "source_types": list(set(tr.source_type for tr in tool_results)),
        },
    )


def propagate_to_state(
    state: PipelineState,
    quality_report: DataQualityReport,
) -> PipelineState:
    """Propagate degraded modes and quality info into PipelineState.

    Adds a 'data_quality' key to state with the quality report.
    If degraded modes exist, adds them to a 'degraded_modes' key.
    """
    state["data_quality"] = quality_report.to_dict()
    if quality_report.degraded_modes:
        existing = state.get("degraded_modes", [])
        state["degraded_modes"] = list(set(existing + quality_report.degraded_modes))
    return state
