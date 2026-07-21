"""Tests for the assertion pipeline — building, validating, and scoring assertions."""

from decimal import Decimal

import pytest

from backend.models.assertions import Assertion, AssertionType, SupportLevel
from backend.models.degraded_mode import DegradedMode
from backend.engine.assertion_pipeline import (
    AssertionPipelineResult,
    build_numeric_assertion,
    build_comparative_assertion,
    build_causal_assertion,
    build_action_assertion,
    run_assertion_pipeline,
)
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
    degraded_mode: str | None = None,
    tenant_id: str = "test-tenant",
) -> ToolResult:
    return ToolResult(
        data=[{"account": "test"}],
        row_count=row_count,
        coverage_pct=coverage_pct,
        quality_score=quality_score,
        freshness_seconds=freshness_seconds,
        schema_version="1.0",
        source_diversity=source_diversity,
        source_type="financial_fact",
        retrieval_scope="factual",
        tenant_id=tenant_id,
        required_filters_present=True,
        insufficient_data=False,
        degraded_mode=degraded_mode,
        query_fingerprint="abc123",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Numeric assertion builder
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildNumericAssertion:
    def test_numeric_assertion_from_variance(self):
        """Build a numeric assertion from variance data with tool results."""
        tool_results = [
            _make_tool_result(row_count=50, coverage_pct=0.95, quality_score=0.9),
            _make_tool_result(row_count=30, coverage_pct=0.85, quality_score=0.8),
        ]
        assertion = build_numeric_assertion(
            account_name="Cloud Spend",
            actual=Decimal("120000"),
            budget=Decimal("100000"),
            variance=Decimal("20000"),
            variance_pct=Decimal("20.00"),
            tool_results=tool_results,
        )
        assert assertion is not None
        assert assertion.type == AssertionType.NUMERIC
        assert assertion.support_level == SupportLevel.VERIFIED
        assert "Cloud Spend" in assertion.text
        assert "$120,000" in assertion.text
        assert "$100,000" in assertion.text
        assert "20.00%" in assertion.text
        assert assertion.value == Decimal("20000")
        assert len(assertion.evidence_ids) == 2
        assert assertion.confidence > 0.0
        assert assertion.metadata["account_name"] == "Cloud Spend"
        assert assertion.metadata["tool_count"] == 2

    def test_numeric_assertion_no_tool_results_returns_none(self):
        """No tool results → returns None."""
        assertion = build_numeric_assertion(
            account_name="Cloud Spend",
            actual=Decimal("120000"),
            budget=Decimal("100000"),
            variance=Decimal("20000"),
            variance_pct=Decimal("20.00"),
            tool_results=[],
        )
        assert assertion is None

    def test_numeric_confidence_scales_with_evidence(self):
        """More evidence → higher confidence."""
        low = build_numeric_assertion(
            account_name="A",
            actual=Decimal("100"), budget=Decimal("90"),
            variance=Decimal("10"), variance_pct=Decimal("11.11"),
            tool_results=[_make_tool_result(row_count=1, coverage_pct=0.3, quality_score=0.3)],
        )
        high = build_numeric_assertion(
            account_name="A",
            actual=Decimal("100"), budget=Decimal("90"),
            variance=Decimal("10"), variance_pct=Decimal("11.11"),
            tool_results=[
                _make_tool_result(row_count=100, coverage_pct=0.95, quality_score=0.95),
                _make_tool_result(row_count=80, coverage_pct=0.90, quality_score=0.90),
            ],
        )
        assert low is not None
        assert high is not None
        assert high.confidence > low.confidence

    def test_numeric_with_degraded_tool(self):
        """Degraded tool results are tracked in metadata."""
        tool_results = [
            _make_tool_result(degraded_mode="low_coverage"),
            _make_tool_result(degraded_mode="stale_source"),
        ]
        assertion = build_numeric_assertion(
            account_name="Test",
            actual=Decimal("100"), budget=Decimal("90"),
            variance=Decimal("10"), variance_pct=Decimal("11.11"),
            tool_results=tool_results,
        )
        assert assertion is not None
        assert "low_coverage" in assertion.metadata["degraded_modes"]
        assert "stale_source" in assertion.metadata["degraded_modes"]


# ═══════════════════════════════════════════════════════════════════════════════
# Comparative assertion builder
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildComparativeAssertion:
    def test_comparative_assertion_with_candidates(self):
        """Build a comparative assertion from a candidate set."""
        candidates = [
            {"account_id": "a1", "account_name": "Cloud", "variance_amount": 50000},
            {"account_id": "a2", "account_name": "HR", "variance_amount": 20000},
            {"account_id": "a3", "account_name": "Marketing", "variance_amount": 10000},
        ]
        assertion = build_comparative_assertion(
            subject="variance",
            candidates=candidates,
            value_field="variance_amount",
        )
        assert assertion is not None
        assert assertion.type == AssertionType.COMPARATIVE
        assert "$50,000" in assertion.text  # largest is 50,000
        assert assertion.support_level == SupportLevel.VERIFIED
        assert assertion.confidence > 0.0

    def test_comparative_assertion_with_rank(self):
        """Rank parameter is included in the assertion text."""
        candidates = [
            {"account_id": "a1", "variance_amount": 50000},
            {"account_id": "a2", "variance_amount": 20000},
        ]
        assertion = build_comparative_assertion(
            subject="variance",
            candidates=candidates,
            value_field="variance_amount",
            rank=1,
        )
        assert assertion is not None
        assert "#1" in assertion.text

    def test_comparative_assertion_insufficient_candidates(self):
        """Fewer than 2 candidates → returns None."""
        candidates = [
            {"account_id": "a1", "variance_amount": 50000},
        ]
        assertion = build_comparative_assertion(
            subject="variance",
            candidates=candidates,
            value_field="variance_amount",
        )
        assert assertion is None

    def test_comparative_empty_candidates(self):
        """Empty candidates list → returns None."""
        assertion = build_comparative_assertion(
            subject="variance",
            candidates=[],
            value_field="variance_amount",
        )
        assert assertion is None


# ═══════════════════════════════════════════════════════════════════════════════
# Causal assertion builder
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildCausalAssertion:
    def test_causal_assertion_with_driver_tree(self):
        """Build a causal assertion with driver tree edges."""
        driver_tree_edges = [
            {"from": "headcount_increase", "to": "salary_expense"},
            {"from": "salary_expense", "to": "total_variance"},
        ]
        assertion = build_causal_assertion(
            cause="headcount_increase",
            effect="salary_expense",
            driver_tree_edges=driver_tree_edges,
            evidence_classes=2,
        )
        assert assertion is not None
        assert assertion.type == AssertionType.CAUSAL
        assert assertion.support_level == SupportLevel.PROBABLE
        assert "headcount_increase" in assertion.text
        assert assertion.confidence <= 0.85  # causal max cap

    def test_causal_assertion_no_driver_tree_with_evidence(self):
        """No driver tree but multiple evidence classes still produces an assertion."""
        assertion = build_causal_assertion(
            cause="headcount_increase",
            effect="salary_expense",
            driver_tree_edges=None,
            evidence_classes=2,
        )
        # With evidence_classes >= 2, validate_causal_claim returns valid
        assert assertion is not None
        assert assertion.support_level in (SupportLevel.PROBABLE, SupportLevel.WEAK)

    def test_causal_assertion_no_driver_tree_no_evidence_rejected(self):
        """No driver tree and insufficient evidence → returns None."""
        assertion = build_causal_assertion(
            cause="headcount_increase",
            effect="salary_expense",
            driver_tree_edges=None,
            evidence_classes=0,
        )
        assert assertion is None

    def test_causal_assertion_alternative_explanation_lowers_support(self):
        """Alternative explanations cause WEAK support level."""
        driver_tree_edges = [
            {"from": "headcount_increase", "to": "salary_expense"},
        ]
        assertion = build_causal_assertion(
            cause="headcount_increase",
            effect="salary_expense",
            driver_tree_edges=driver_tree_edges,
            evidence_classes=1,
            has_alternative=True,
        )
        assert assertion is not None
        assert assertion.support_level == SupportLevel.WEAK

    def test_causal_confidence_capped(self):
        """Causal confidence never exceeds 0.85."""
        driver_tree_edges = [
            {"from": "cause_a", "to": "effect_b"},
            {"from": "cause_b", "to": "effect_c"},
        ]
        assertion = build_causal_assertion(
            cause="cause_a",
            effect="effect_b",
            driver_tree_edges=driver_tree_edges,
            evidence_classes=5,
        )
        assert assertion is not None
        assert assertion.confidence <= 0.85


# ═══════════════════════════════════════════════════════════════════════════════
# Action assertion builder
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildActionAssertion:
    def test_action_assertion_valid(self):
        """Build a valid action assertion."""
        assertion = build_action_assertion(
            action="reduce",
            target="cloud spend",
            cited_causes=["over-provisioning", "underutilized instances"],
            policy_permitted=True,
            owner_identified=True,
            impact_quantified=True,
        )
        assert assertion is not None
        assert assertion.type == AssertionType.ACTION
        assert assertion.support_level == SupportLevel.PROBABLE
        assert "reduce" in assertion.text
        assert "cloud spend" in assertion.text
        assert assertion.confidence > 0.0

    def test_action_assertion_not_in_taxonomy_rejected(self):
        """Action not in approved taxonomy → returns None."""
        assertion = build_action_assertion(
            action="fire",
            target="everyone",
            cited_causes=["performance"],
            policy_permitted=False,
        )
        assert assertion is None

    def test_action_assertion_no_cited_causes_rejected(self):
        """No cited causes → returns None."""
        assertion = build_action_assertion(
            action="reduce",
            target="costs",
            cited_causes=None,
            policy_permitted=True,
        )
        assert assertion is None

    def test_action_assertion_impact_quantified_in_text(self):
        """impact_quantified=True adds 'with quantified impact' to text."""
        assertion = build_action_assertion(
            action="optimize",
            target="infrastructure",
            cited_causes=["waste"],
            policy_permitted=True,
            impact_quantified=True,
        )
        assert assertion is not None
        assert "quantified impact" in assertion.text

    def test_action_confidence_scales_with_metadata(self):
        """More action metadata → higher confidence."""
        low = build_action_assertion(
            action="reduce", target="costs",
            cited_causes=["cause1"], policy_permitted=False,
        )
        high = build_action_assertion(
            action="reduce", target="costs",
            cited_causes=["cause1", "cause2"],
            policy_permitted=True, owner_identified=True, impact_quantified=True,
        )
        assert low is not None
        assert high is not None
        assert high.confidence > low.confidence


# ═══════════════════════════════════════════════════════════════════════════════
# Full pipeline run
# ═══════════════════════════════════════════════════════════════════════════════


class TestFullPipeline:
    def test_full_pipeline_run(self):
        """Run the full assertion pipeline end-to-end."""
        variances = [
            {
                "account_name": "Cloud Spend",
                "actual_amount": Decimal("120000"),
                "budget_amount": Decimal("100000"),
                "variance_amount": Decimal("20000"),
                "variance_pct": Decimal("20.00"),
            },
            {
                "account_name": "Travel",
                "actual_amount": Decimal("50000"),
                "budget_amount": Decimal("60000"),
                "variance_amount": Decimal("-10000"),
                "variance_pct": Decimal("-16.67"),
            },
        ]

        tool_results = {
            "gl": [
                _make_tool_result(row_count=80, coverage_pct=0.95, quality_score=0.9),
                _make_tool_result(row_count=60, coverage_pct=0.85, quality_score=0.8),
            ],
            "headcount": [
                _make_tool_result(
                    row_count=30, coverage_pct=0.90, quality_score=0.85,
                    source_type="operational_metric",
                ),
            ],
        }

        candidates = [
            {"account_id": "a1", "account_name": "Cloud", "variance_amount": 20000},
            {"account_id": "a2", "account_name": "Travel", "variance_amount": -10000},
        ]

        driver_tree_edges = [
            {"from": "cloud_migration", "to": "infra_spend"},
            {"from": "infra_spend", "to": "cloud_variance"},
        ]

        result = run_assertion_pipeline(
            variances=variances,
            tool_results=tool_results,
            candidates=candidates,
            driver_tree_edges=driver_tree_edges,
        )

        assert isinstance(result, AssertionPipelineResult)
        assert result.has_valid_assertions
        assert len(result.assertions) >= 2  # at least 2 numeric + comparative + causal
        assert result.highest_confidence > 0.0
        assert result.summary

    def test_pipeline_result_properties(self):
        """AssertionPipelineResult properties behave correctly."""
        # Empty result
        empty = AssertionPipelineResult()
        assert empty.has_valid_assertions is False
        assert empty.highest_confidence == 0.0
        assert empty.all_verified is True  # vacuous truth

        # Result with assertions
        a1 = Assertion(
            id="test-1", type=AssertionType.NUMERIC,
            text="Test", support_level=SupportLevel.VERIFIED,
            confidence=0.9,
        )
        a2 = Assertion(
            id="test-2", type=AssertionType.NUMERIC,
            text="Test", support_level=SupportLevel.VERIFIED,
            confidence=0.7,
        )
        a3 = Assertion(
            id="test-3", type=AssertionType.CAUSAL,
            text="Test", support_level=SupportLevel.PROBABLE,
            confidence=0.5,
        )
        a4 = Assertion(
            id="test-4", type=AssertionType.HYPOTHESIS,
            text="Test", support_level=SupportLevel.PROBABLE,
            confidence=0.3,
        )

        result = AssertionPipelineResult(
            assertions=[a1, a2, a3, a4],
            rejected=[{"id": "bad", "reason": "no data"}],
            degraded_modes=["low_coverage"],
            summary="Pipeline summary",
        )
        assert result.has_valid_assertions is True
        assert result.highest_confidence == 0.9
        assert result.all_verified is False  # a3 is PROBABLE
        assert result.summary == "Pipeline summary"

    def test_pipeline_all_verified_true_when_all_verified_except_hypotheses(self):
        """all_verified ignores HYPOTHESIS assertions."""
        a1 = Assertion(
            id="t1", type=AssertionType.NUMERIC,
            text="T", support_level=SupportLevel.VERIFIED,
        )
        a2 = Assertion(
            id="t2", type=AssertionType.HYPOTHESIS,
            text="T", support_level=SupportLevel.PROBABLE,
        )
        result = AssertionPipelineResult(assertions=[a1, a2])
        assert result.all_verified is True

    def test_assertions_sorted_by_confidence(self):
        """run_assertion_pipeline sorts assertions by confidence descending."""
        variances = [
            {
                "account_name": "Low Conf",
                "actual_amount": Decimal("100"), "budget_amount": Decimal("90"),
                "variance_amount": Decimal("10"), "variance_pct": Decimal("11.11"),
            },
            {
                "account_name": "High Conf",
                "actual_amount": Decimal("200"), "budget_amount": Decimal("180"),
                "variance_amount": Decimal("20"), "variance_pct": Decimal("11.11"),
            },
        ]
        # Different tool result quality will produce different confidence scores
        tool_results = {
            "gl": [
                _make_tool_result(row_count=100, coverage_pct=0.95, quality_score=0.95),
            ],
        }
        result = run_assertion_pipeline(
            variances=variances,
            tool_results=tool_results,
        )
        confidences = [a.confidence for a in result.assertions]
        assert confidences == sorted(confidences, reverse=True), (
            f"Expected descending order, got {confidences}"
        )

    def test_pipeline_empty_variances(self):
        """Empty variances list produces no assertions."""
        result = run_assertion_pipeline(
            variances=[],
            tool_results={"gl": []},
        )
        assert result.has_valid_assertions is False
        assert len(result.assertions) == 0
        assert result.highest_confidence == 0.0

    def test_pipeline_rejected_no_tool_results(self):
        """Variances without tool results appear in rejected."""
        variances = [
            {
                "account_name": "No Data Account",
                "actual_amount": Decimal("100"), "budget_amount": Decimal("90"),
                "variance_amount": Decimal("10"), "variance_pct": Decimal("11.11"),
            },
        ]
        result = run_assertion_pipeline(
            variances=variances,
            tool_results={"gl": []},
        )
        assert len(result.rejected) == 1
        assert result.rejected[0]["account"] == "No Data Account"

    def test_pipeline_tracks_degraded_modes(self):
        """Degraded modes from tool results surface in pipeline result."""
        variances = [
            {
                "account_name": "Degraded Account",
                "actual_amount": Decimal("100"), "budget_amount": Decimal("90"),
                "variance_amount": Decimal("10"), "variance_pct": Decimal("11.11"),
            },
        ]
        tool_results = {
            "gl": [
                _make_tool_result(degraded_mode="low_coverage"),
                _make_tool_result(degraded_mode="stale_source"),
            ],
        }
        result = run_assertion_pipeline(
            variances=variances,
            tool_results=tool_results,
        )
        assert "low_coverage" in result.degraded_modes
        assert "stale_source" in result.degraded_modes


# ═══════════════════════════════════════════════════════════════════════════════
# PipelineResult edge cases
# ═══════════════════════════════════════════════════════════════════════════════


class TestPipelineResultEdgeCases:
    def test_empty_result_defaults(self):
        """AssertionPipelineResult defaults are safe."""
        r = AssertionPipelineResult()
        assert r.assertions == []
        assert r.rejected == []
        assert r.degraded_modes == []
        assert r.summary == ""

    def test_highest_confidence_empty(self):
        """highest_confidence returns 0.0 for empty result."""
        r = AssertionPipelineResult()
        assert r.highest_confidence == 0.0

    def test_all_verified_empty(self):
        """all_verified returns True for empty result (vacuous truth)."""
        r = AssertionPipelineResult()
        assert r.all_verified is True
