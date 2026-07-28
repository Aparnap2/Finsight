"""Tests for Phase 4 — Evaluation (golden datasets, metrics, runner, regression)."""
from __future__ import annotations

from decimal import Decimal

import pytest

from finance.cognition.harness import HarnessResult
from finance.cognition.state.action import Action, ActionPlan, ActionStatus
from finance.cognition.state.models import ReasoningState
from finance.evaluation.dataset import (
    DatasetInput,
    DatasetMetadata,
    ExecutionExpectation,
    ExpectedBehaviour,
    GoldenDataset,
    OutputExpectation,
    PlanningExpectation,
    ReflectionExpectation,
    VerificationExpectation,
)
from finance.evaluation.loader import GoldenDatasetLoader
from finance.evaluation.metrics import (
    ActionSuccessRate,
    AverageLatency,
    EvidenceCoverage,
    KPIAccuracy,
    OverallScore,
    PlanningAccuracy,
    PolicyCompliance,
    ReplanningFrequency,
    ReportCoverage,
    RetryRate,
    ToolFailureRate,
    UnsupportedClaimRate,
    VarianceAccuracy,
)
from finance.evaluation.regression import (
    Comparator,
    RegressionReport,
    RegressionRunner,
    Threshold,
)
from finance.evaluation.runner import EvaluationReport, EvaluationRunner
from shared.models.assertions import Assertion, AssertionType, SupportLevel

# ── GoldenDataset ────────────────────────────────────────────────────────────


class TestGoldenDataset:
    def test_create_complete(self):
        ds = GoldenDataset(
            metadata=DatasetMetadata(id="test", name="Test", category="financial_logic"),
            input=DatasetInput(query="Analyse revenue"),
            expected=ExpectedBehaviour(
                planning=PlanningExpectation(required_intents=["compute_variance"]),
                output=OutputExpectation(variances=[{"account_id": "4010", "variance_amount": 5000}]),
            ),
        )
        assert ds.metadata.id == "test"
        assert ds.expected.planning.required_intents == ["compute_variance"]
        assert ds.expected.output.variances[0]["account_id"] == "4010"

    def test_minimal_defaults(self):
        ds = GoldenDataset(
            metadata=DatasetMetadata(id="min", name="Minimal", category="basic"),
            input=DatasetInput(),
        )
        assert ds.expected.planning.min_actions == 1
        assert ds.expected.execution.min_success_rate == 1.0
        assert ds.expected.verification.max_unsupported == 0
        assert ds.expected.reflection.expected_decision == "finalize"
        assert ds.expected.output.variances == []

    def test_nested_model_defaults(self):
        p = PlanningExpectation()
        e = ExecutionExpectation()
        v = VerificationExpectation()
        r = ReflectionExpectation()
        o = OutputExpectation()
        assert p.min_actions == 1
        assert p.max_replans == 0
        assert e.min_success_rate == 1.0
        assert e.max_retries_total == 0
        assert v.max_unsupported == 0
        assert v.min_evidence == 0
        assert r.expected_decision == "finalize"
        assert o.required_claims == []

    def test_serialization_roundtrip(self):
        ds = GoldenDataset(
            metadata=DatasetMetadata(id="rt", name="Round Trip", category="test", tags=["a", "b"]),
            input=DatasetInput(query="test query", context={"key": "val"}),
            expected=ExpectedBehaviour(
                planning=PlanningExpectation(required_intents=["x", "y"]),
            ),
        )
        raw = ds.model_dump()
        ds2 = GoldenDataset.model_validate(raw)
        assert ds2.metadata.id == "rt"
        assert ds2.input.query == "test query"
        assert ds2.expected.planning.required_intents == ["x", "y"]

    def test_metadata_category_tags(self):
        meta = DatasetMetadata(id="a", name="A", category="data_quality", subcategory="missing", difficulty="advanced")
        assert meta.category == "data_quality"
        assert meta.subcategory == "missing"
        assert meta.difficulty == "advanced"


# ── Dataset Loader ───────────────────────────────────────────────────────────


class TestGoldenDatasetLoader:
    def test_loader_returns_builtin_datasets(self):
        loader = GoldenDatasetLoader()
        ds = loader.load("simple_001")
        assert ds is not None
        assert ds.metadata.id == "simple_001"
        ds2 = loader.load("seasonal_001")
        assert ds2 is not None

    def test_loader_returns_all_datasets(self):
        loader = GoldenDatasetLoader()
        datasets = loader.load_all()
        assert len(datasets) >= 20

    def test_loader_load_by_id(self):
        loader = GoldenDatasetLoader()
        ds = loader.load("revenue_growth")
        assert ds is not None
        assert ds.metadata.id == "revenue_growth"

    def test_loader_returns_none_for_missing(self):
        loader = GoldenDatasetLoader()
        ds = loader.load("nonexistent")
        assert ds is None

    def test_loader_datasets_have_metadata(self):
        loader = GoldenDatasetLoader()
        for ds in loader.load_all():
            assert ds.metadata.id
            assert ds.metadata.name
            assert ds.metadata.category


# ── Business Metrics: VarianceAccuracy ───────────────────────────────────────


class TestVarianceAccuracy:
    def test_perfect(self):
        score = VarianceAccuracy.compute(
            expected=[{"account_id": "4010", "variance_amount": 5000, "variance_pct": 5.0}],
            actual=[{"account_id": "4010", "variance_amount": 5000, "variance_pct": 5.0}],
        )
        assert score == 1.0

    def test_no_match(self):
        score = VarianceAccuracy.compute(
            expected=[{"account_id": "4010", "variance_amount": 5000, "variance_pct": 5.0}],
            actual=[],
        )
        assert score == 0.0

    def test_partial(self):
        score = VarianceAccuracy.compute(
            expected=[
                {"account_id": "4010", "variance_amount": 5000, "variance_pct": 5.0},
                {"account_id": "6010", "variance_amount": 2000, "variance_pct": 3.0},
            ],
            actual=[{"account_id": "4010", "variance_amount": 5000, "variance_pct": 5.0}],
        )
        assert 0.0 < score < 1.0


# ── Business Metrics: KPIAccuracy ────────────────────────────────────────────


class TestKPIAccuracy:
    def test_perfect(self):
        score = KPIAccuracy().compute(
            expected=[{"name": "Gross Margin", "value": Decimal("62.0")}],
            actual=[{"name": "Gross Margin", "value": Decimal("62.0")}],
        )
        assert score == 1.0

    def test_with_tolerance(self):
        score = KPIAccuracy(tolerance=Decimal("0.5")).compute(
            expected=[{"name": "Gross Margin", "value": Decimal("62.0")}],
            actual=[{"name": "Gross Margin", "value": Decimal("62.3")}],
        )
        assert score == 1.0


# ── Business Metrics: ReportCoverage ─────────────────────────────────────────


class TestReportCoverage:
    def test_full_coverage(self):
        score = ReportCoverage.compute(
            expected_sections={"executive_summary": "revenue grew"},
            actual_content={"executive_summary": "Revenue grew 12% this quarter"},
        )
        assert score == 1.0

    def test_partial_coverage(self):
        score = ReportCoverage.compute(
            expected_sections={"executive_summary": "revenue grew", "risks": "market volatility"},
            actual_content={"executive_summary": "Revenue grew 12%"},
        )
        assert 0.0 < score < 1.0


# ── Business Metrics: UnsupportedClaimRate ───────────────────────────────────


class TestUnsupportedClaimRate:
    def test_all_supported(self):
        assertions = [
            Assertion(id="a1", type=AssertionType.NUMERIC, text="r1", support_level=SupportLevel.VERIFIED, confidence=0.9, evidence_ids=["e1"]),
            Assertion(id="a2", type=AssertionType.NUMERIC, text="r2", support_level=SupportLevel.PROBABLE, confidence=0.8, evidence_ids=["e2"]),
        ]
        score = UnsupportedClaimRate.compute(assertions)
        assert score == 1.0

    def test_none_supported(self):
        assertions = [
            Assertion(id="a1", type=AssertionType.NUMERIC, text="r1", support_level=SupportLevel.INSUFFICIENT, confidence=0.1),
            Assertion(id="a2", type=AssertionType.NUMERIC, text="r2", support_level=SupportLevel.WEAK, confidence=0.3),
        ]
        score = UnsupportedClaimRate.compute(assertions)
        assert score == 0.0

    def test_mixed(self):
        assertions = [
            Assertion(id="a1", type=AssertionType.NUMERIC, text="r1", support_level=SupportLevel.VERIFIED, confidence=0.9, evidence_ids=["e1"]),
            Assertion(id="a2", type=AssertionType.NUMERIC, text="r2", support_level=SupportLevel.INSUFFICIENT, confidence=0.1),
        ]
        score = UnsupportedClaimRate.compute(assertions)
        assert score == 0.5

    def test_empty(self):
        score = UnsupportedClaimRate.compute([])
        assert score == 1.0


# ── Business Metrics: EvidenceCoverage ───────────────────────────────────────


class TestEvidenceCoverage:
    def test_perfect(self):
        assertions = [
            Assertion(id="a1", type=AssertionType.NUMERIC, text="r1", support_level=SupportLevel.VERIFIED, confidence=0.9, evidence_ids=["e1"]),
        ]
        score = EvidenceCoverage().compute(assertions)
        assert score == 1.0

    def test_exceeds_target(self):
        assertions = [
            Assertion(id="a1", type=AssertionType.NUMERIC, text="r1", support_level=SupportLevel.VERIFIED, confidence=0.9, evidence_ids=["e1", "e2", "e3"]),
        ]
        score = EvidenceCoverage().compute(assertions)
        assert score == 1.0

    def test_below_target(self):
        assertions = [
            Assertion(id="a1", type=AssertionType.NUMERIC, text="r1", support_level=SupportLevel.VERIFIED, confidence=0.9, evidence_ids=[]),
        ]
        score = EvidenceCoverage().compute(assertions)
        assert score == 0.0

    def test_custom_target(self):
        assertions = [
            Assertion(id="a1", type=AssertionType.NUMERIC, text="r1", support_level=SupportLevel.VERIFIED, confidence=0.9, evidence_ids=["e1", "e2"]),
            Assertion(id="a2", type=AssertionType.NUMERIC, text="r2", support_level=SupportLevel.VERIFIED, confidence=0.9, evidence_ids=["e1", "e2"]),
        ]
        score = EvidenceCoverage(min_evidence_target=4).compute(assertions)
        assert score == 0.5

    def test_empty(self):
        score = EvidenceCoverage().compute([])
        assert score == 0.0


# ── Business Metrics: PolicyCompliance ───────────────────────────────────────


class TestPolicyCompliance:
    def test_all_compliant(self):
        assertions = [
            Assertion(id="a1", type=AssertionType.NUMERIC, text="r1", support_level=SupportLevel.VERIFIED, confidence=0.9, max_allowed_action="route_for_review"),
            Assertion(id="a2", type=AssertionType.NUMERIC, text="r2", support_level=SupportLevel.VERIFIED, confidence=0.9, max_allowed_action="notify"),
        ]
        score = PolicyCompliance.compute(assertions)
        assert score == 1.0

    def test_mixed(self):
        assertions = [
            Assertion(id="a1", type=AssertionType.NUMERIC, text="r1", support_level=SupportLevel.VERIFIED, confidence=0.9, max_allowed_action="route_for_review"),
            Assertion(id="a2", type=AssertionType.NUMERIC, text="r2", support_level=SupportLevel.VERIFIED, confidence=0.9, max_allowed_action="block"),
        ]
        score = PolicyCompliance.compute(assertions)
        assert score == 0.5

    def test_empty(self):
        score = PolicyCompliance.compute([])
        assert score == 1.0


# ── Runtime Metrics: PlanningAccuracy ────────────────────────────────────────


class TestPlanningAccuracy:
    def test_all_intents_met(self):
        plan = ActionPlan(actions=[Action(objective="compute_variance"), Action(objective="analyse_kpi")])
        score = PlanningAccuracy.compute(
            required_intents=["compute_variance", "analyse_kpi"],
            forbidden_intents=[],
            action_plan=plan,
        )
        assert score == 1.0

    def test_missing_required(self):
        plan = ActionPlan(actions=[Action(objective="compute_variance")])
        score = PlanningAccuracy.compute(
            required_intents=["compute_variance", "analyse_kpi"],
            forbidden_intents=[],
            action_plan=plan,
        )
        assert score == 0.75  # (1/2 + 1/1) / 2 = 0.75

    def test_forbidden_present(self):
        plan = ActionPlan(actions=[Action(objective="compute_variance"), Action(objective="reduce_headcount")])
        score = PlanningAccuracy.compute(
            required_intents=["compute_variance"],
            forbidden_intents=["reduce_headcount"],
            action_plan=plan,
        )
        assert score == 0.5  # (1/1 + 0/1) / 2 = 0.5

    def test_no_plan(self):
        score = PlanningAccuracy.compute(required_intents=["x"], forbidden_intents=[], action_plan=None)
        assert score == 0.0

    def test_no_expectations(self):
        score = PlanningAccuracy.compute(required_intents=[], forbidden_intents=[], action_plan=ActionPlan())
        assert score == 1.0


# ── Runtime Metrics: ReplanningFrequency ─────────────────────────────────────


class TestReplanningFrequency:
    def test_no_replanning(self):
        score = ReplanningFrequency.compute(max_replans=0, plan_history=["p1"])
        assert score == 1.0

    def test_one_replan(self):
        score = ReplanningFrequency.compute(max_replans=2, plan_history=["p1", "p2"])
        assert score == pytest.approx(2.0 / 3.0)

    def test_exceeded_max(self):
        score = ReplanningFrequency.compute(max_replans=0, plan_history=["p1", "p2"])
        assert score == 0.0


# ── Runtime Metrics: ActionSuccessRate ───────────────────────────────────────


class TestActionSuccessRate:
    def test_all_success(self):
        actions = [Action(objective="a", status=ActionStatus.SUCCESS), Action(objective="b", status=ActionStatus.SUCCESS)]
        assert ActionSuccessRate.compute(actions) == 1.0

    def test_all_failed(self):
        actions = [Action(objective="a", status=ActionStatus.FAILED)]
        assert ActionSuccessRate.compute(actions) == 0.0

    def test_mixed(self):
        actions = [
            Action(objective="a", status=ActionStatus.SUCCESS),
            Action(objective="b", status=ActionStatus.SUCCESS),
            Action(objective="c", status=ActionStatus.SUCCESS),
            Action(objective="d", status=ActionStatus.FAILED),
        ]
        assert ActionSuccessRate.compute(actions) == 0.75

    def test_empty(self):
        assert ActionSuccessRate.compute([]) == 0.0


# ── Runtime Metrics: RetryRate ────────────────────────────────────────────────


class TestRetryRate:
    def test_no_retries(self):
        actions = [Action(objective="a", retry_count=0), Action(objective="b", retry_count=0)]
        assert RetryRate.compute(actions) == 1.0

    def test_retry_on_every_action(self):
        actions = [Action(objective="a", retry_count=1)]
        assert RetryRate.compute(actions) == 0.0

    def test_some_retries(self):
        actions = [Action(objective="a", retry_count=0), Action(objective="b", retry_count=1)]
        assert RetryRate.compute(actions) == 0.5

    def test_empty(self):
        assert RetryRate.compute([]) == 0.0


# ── Runtime Metrics: AverageLatency ──────────────────────────────────────────


class TestAverageLatency:
    def test_under_budget(self):
        actions = [Action(objective="a", latency_ms=500)]
        score = AverageLatency(budget_ms=1000).compute(actions)
        assert score == 1.0

    def test_at_threshold(self):
        actions = [Action(objective="a", latency_ms=1000)]
        score = AverageLatency(budget_ms=1000).compute(actions)
        assert score == 1.0

    def test_double_budget(self):
        actions = [Action(objective="a", latency_ms=2000)]
        score = AverageLatency(budget_ms=1000).compute(actions)
        assert score == 0.0

    def test_in_between(self):
        actions = [Action(objective="a", latency_ms=1500)]
        score = AverageLatency(budget_ms=1000).compute(actions)
        assert score == 0.5

    def test_empty(self):
        assert AverageLatency().compute([]) == 0.0


# ── Runtime Metrics: ToolFailureRate ─────────────────────────────────────────


class TestToolFailureRate:
    def test_no_failures(self):
        actions = [Action(objective="a", status=ActionStatus.SUCCESS)]
        assert ToolFailureRate.compute(actions) == 1.0

    def test_half_failed(self):
        actions = [
            Action(objective="a", status=ActionStatus.SUCCESS),
            Action(objective="b", status=ActionStatus.FAILED),
        ]
        assert ToolFailureRate.compute(actions) == 0.5

    def test_empty(self):
        assert ToolFailureRate.compute([]) == 0.0


# ── OverallScore ─────────────────────────────────────────────────────────────


class TestOverallScore:
    def test_mean_of_all(self):
        result = OverallScore.compute(scores={"variance": 1.0, "kpi": 0.8, "coverage": 0.6})
        assert result["overall"] == 0.8

    def test_pass_threshold(self):
        result = OverallScore.compute(scores={"a": 0.7})
        assert result["passed"] is True

    def test_fail_threshold(self):
        result = OverallScore.compute(scores={"a": 0.6})
        assert result["passed"] is False

    def test_empty_scores(self):
        result = OverallScore.compute(scores={})
        assert result["overall"] == 0.0
        assert result["passed"] is False


# ── Evaluation Runner ────────────────────────────────────────────────────────


class TestEvaluationRunner:
    def test_run_returns_report(self):
        ds = GoldenDataset(
            metadata=DatasetMetadata(id="test001", name="Test", category="test"),
            input=DatasetInput(query="test"),
        )
        state = ReasoningState(query="test", context={})
        result = HarnessResult(state=state, run_id="r1", success=True)
        runner = EvaluationRunner()
        report = runner.run(dataset=ds, result=result)
        assert report.dataset_id == "test001"
        assert report.overall_score >= 0
        assert "variance_accuracy" in report.business_metrics
        assert "planning_accuracy" in report.runtime_metrics

    def test_report_has_separate_metric_groups(self):
        ds = GoldenDataset(
            metadata=DatasetMetadata(id="test002", name="Test2", category="test"),
            input=DatasetInput(query="test"),
        )
        state = ReasoningState(query="test", context={})
        result = HarnessResult(state=state, run_id="r2", success=True)
        runner = EvaluationRunner()
        report = runner.run(dataset=ds, result=result)
        assert isinstance(report.runtime_metrics, dict)
        assert isinstance(report.business_metrics, dict)
        assert len(report.runtime_metrics) == 6
        assert len(report.business_metrics) == 6

    def test_run_all_multiple_datasets(self):
        ds1 = GoldenDataset(metadata=DatasetMetadata(id="d1", name="D1", category="test"), input=DatasetInput())
        ds2 = GoldenDataset(metadata=DatasetMetadata(id="d2", name="D2", category="test"), input=DatasetInput())
        state1 = ReasoningState(query="t", context={})
        state2 = ReasoningState(query="t", context={})
        results = {
            "d1": HarnessResult(state=state1, run_id="r1", success=True),
            "d2": HarnessResult(state=state2, run_id="r2", success=True),
        }
        runner = EvaluationRunner()
        reports = runner.run_all(datasets=[ds1, ds2], results=results)
        assert len(reports) == 2

    def test_run_all_dict_legacy(self):
        ds = GoldenDataset(metadata=DatasetMetadata(id="d", name="D", category="test"), input=DatasetInput())
        runner = EvaluationRunner()
        reports = runner.run_all_dict(
            datasets=[ds],
            pipeline_outputs={"d": {"variances": [], "kpis": [], "report_sections": {}}},
        )
        assert len(reports) == 1
        assert reports[0].dataset_id == "d"

    def test_run_with_actions(self):
        plan = ActionPlan(actions=[
            Action(objective="compute_variance", status=ActionStatus.SUCCESS, latency_ms=500, retry_count=0, tool="ve"),
        ])
        ds = GoldenDataset(
            metadata=DatasetMetadata(id="act_test", name="Action Test", category="test"),
            input=DatasetInput(query="test"),
            expected=ExpectedBehaviour(
                planning=PlanningExpectation(required_intents=["compute_variance"]),
            ),
        )
        state = ReasoningState(query="test", context={"action_traces": plan.actions}, action_plan=plan)
        result = HarnessResult(state=state, run_id="r_act", success=True)
        runner = EvaluationRunner()
        report = runner.run(dataset=ds, result=result)
        assert report.runtime_metrics["action_success_rate"] == 1.0
        assert report.runtime_metrics["retry_rate"] == 1.0
        assert report.runtime_metrics["average_latency"] == 1.0


# ── Comparator (Regression) ──────────────────────────────────────────────────


class TestComparator:
    def test_identical_reports(self):
        r = EvaluationReport(dataset_id="d1", overall_score=0.9, runtime_metrics={"planning_accuracy": 1.0}, business_metrics={"variance_accuracy": 1.0}, passed=True)
        c = Comparator(runtime_thresholds={"planning_accuracy": Threshold(warn=0.0, break_=0.0)},
                       business_thresholds={"variance_accuracy": Threshold(warn=0.0, break_=0.0)})
        report = c.compare(baseline=[r], current=[r])
        assert report.summary == "PASS"
        assert report.breaking_changes == []

    def test_regression_detected(self):
        base = EvaluationReport(dataset_id="d1", overall_score=0.9, runtime_metrics={"planning_accuracy": 1.0}, business_metrics={"variance_accuracy": 1.0}, passed=True)
        curr = EvaluationReport(dataset_id="d1", overall_score=0.5, runtime_metrics={"planning_accuracy": 0.5}, business_metrics={"variance_accuracy": 1.0}, passed=True)
        c = Comparator(runtime_thresholds={"planning_accuracy": Threshold(warn=0.0, break_=0.3)},
                       business_thresholds={})
        report = c.compare(baseline=[base], current=[curr])
        assert "planning_accuracy" in str(report.breaking_changes)

    def test_new_failures(self):
        base = EvaluationReport(dataset_id="d1", overall_score=1.0, runtime_metrics={}, business_metrics={}, passed=True)
        curr = EvaluationReport(dataset_id="d2", overall_score=0.8, runtime_metrics={}, business_metrics={}, passed=True)
        c = Comparator()
        report = c.compare(baseline=[base], current=[base, curr])
        assert "d2" in report.new_failures

    def test_resolved_failures(self):
        base = EvaluationReport(dataset_id="d1", overall_score=0.8, runtime_metrics={}, business_metrics={}, passed=True)
        base2 = EvaluationReport(dataset_id="d2", overall_score=0.8, runtime_metrics={}, business_metrics={}, passed=True)
        curr = EvaluationReport(dataset_id="d1", overall_score=0.8, runtime_metrics={}, business_metrics={}, passed=True)
        c = Comparator()
        report = c.compare(baseline=[base, base2], current=[curr])
        assert "d2" in report.resolved_failures

    def test_delta_computation(self):
        base = EvaluationReport(dataset_id="d1", overall_score=1.0, runtime_metrics={"planning_accuracy": 1.0}, business_metrics={}, passed=True)
        curr = EvaluationReport(dataset_id="d1", overall_score=1.0, runtime_metrics={"planning_accuracy": 0.8}, business_metrics={}, passed=True)
        c = Comparator()
        report = c.compare(baseline=[base], current=[curr])
        assert abs(report.deltas["runtime.planning_accuracy"] - (-0.2)) < 0.001


# ── Regression Runner ────────────────────────────────────────────────────────


class TestRegressionRunner:
    def test_no_baseline_yet(self, tmp_path):
        runner = RegressionRunner(baseline_dir=str(tmp_path / "baseline"))
        reports = [EvaluationReport(dataset_id="d1", overall_score=1.0, runtime_metrics={}, business_metrics={}, passed=True)]
        result = runner.run_and_compare(reports)
        assert result is None
        assert (tmp_path / "baseline" / "baseline.json").exists()

    def test_compare_against_baseline(self, tmp_path):
        runner = RegressionRunner(baseline_dir=str(tmp_path / "baseline2"))
        r1 = EvaluationReport(dataset_id="d1", overall_score=1.0, runtime_metrics={"planning": 1.0}, business_metrics={}, passed=True)
        runner.run_and_compare([r1])
        r2 = EvaluationReport(dataset_id="d1", overall_score=0.9, runtime_metrics={"planning": 0.9}, business_metrics={}, passed=True)
        result = runner.run_and_compare([r2])
        assert result is not None
        assert isinstance(result, RegressionReport)

    def test_save_and_load_baseline(self, tmp_path):
        runner = RegressionRunner(baseline_dir=str(tmp_path / "baseline3"))
        reports = [EvaluationReport(dataset_id="d1", overall_score=0.95, runtime_metrics={}, business_metrics={}, passed=True)]
        runner.save_baseline(reports)
        loaded = runner.load_baseline()
        assert loaded is not None
        assert len(loaded) == 1
        assert loaded[0].dataset_id == "d1"
