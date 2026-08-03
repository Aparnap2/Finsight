"""Evaluation runner that drives metrics against golden datasets.

Updated for Phase 4 to consume ``HarnessResult`` directly instead of a
raw dictionary, and to compute runtime + business metrics separately.
Extended for Phase G/H with a headless golden-regression CLI entry
(:func:`main`) that can be wired into CI.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from pydantic import BaseModel

from finance.cognition.harness import HarnessResult
from finance.cognition.state.action import Action, ActionPlan
from finance.evaluation.dataset import GoldenDataset
from finance.evaluation.golden import (
    GoldenRegressionHarness,
    GoldenRegressionReport,
    ReferenceAnalyticsEngine,
    ReferenceAnomalyDetector,
    ReferenceDuplicateDetector,
    ReferenceForecastModel,
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


class EvaluationReport(BaseModel):
    """Result of running evaluation metrics against a single dataset."""

    dataset_id: str
    overall_score: float
    runtime_metrics: dict[str, float]
    business_metrics: dict[str, float]
    passed: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


class EvaluationRunner:
    """Orchestrates evaluation metrics against golden datasets.

    Accepts a ``HarnessResult`` directly so the typed path is enforced
    all the way through.
    """

    def __init__(self, latency_budget_ms: int = 1000) -> None:
        self._variance_accuracy = VarianceAccuracy()
        self._kpi_accuracy = KPIAccuracy()
        self._report_coverage = ReportCoverage()
        self._unsupported_claim_rate = UnsupportedClaimRate()
        self._evidence_coverage = EvidenceCoverage()
        self._policy_compliance = PolicyCompliance()
        self._planning_accuracy = PlanningAccuracy()
        self._replanning_frequency = ReplanningFrequency()
        self._action_success_rate = ActionSuccessRate()
        self._retry_rate = RetryRate()
        self._average_latency = AverageLatency(budget_ms=latency_budget_ms)
        self._tool_failure_rate = ToolFailureRate()
        self._overall_score = OverallScore()

    def run(
        self,
        dataset: GoldenDataset,
        result: HarnessResult,
    ) -> EvaluationReport:
        """Run all metrics against *dataset* using *result*."""
        state = result.state

        # ── Extract data ──────────────────────────────────────────────
        assertions = state.assertions
        action_plan: ActionPlan | None = state.action_plan
        plan_history = state.plan_history or []
        trace_actions = state.context.get("action_traces", [])

        actions: list[Action] = []
        if action_plan is not None:
            actions = action_plan.actions
        if trace_actions:
            actions = trace_actions

        # ── Business metrics ──────────────────────────────────────────
        out = dataset.expected.output
        actual_variances = state.context.get("variances", [])
        actual_kpis = state.context.get("kpis", [])
        actual_report = state.context.get("report_sections", {})

        va_score = self._variance_accuracy.compute(out.variances, actual_variances)
        ka_score = self._kpi_accuracy.compute(out.kpis, actual_kpis)
        rc_score = self._report_coverage.compute(out.report_sections, actual_report)
        uc_score = self._unsupported_claim_rate.compute(assertions)
        ec_score = self._evidence_coverage.compute(assertions)
        pc_score = self._policy_compliance.compute(assertions)

        business_metrics: dict[str, float] = {
            "variance_accuracy": va_score,
            "kpi_accuracy": ka_score,
            "report_coverage": rc_score,
            "unsupported_claim_rate": uc_score,
            "evidence_coverage": ec_score,
            "policy_compliance": pc_score,
        }

        # ── Runtime metrics ───────────────────────────────────────────
        plan_exp = dataset.expected.planning

        pa_score = self._planning_accuracy.compute(
            plan_exp.required_intents,
            plan_exp.forbidden_intents,
            action_plan,
        )
        rf_score = self._replanning_frequency.compute(
            plan_exp.max_replans,
            plan_history,
        )
        asr_score = self._action_success_rate.compute(actions)
        rr_score = self._retry_rate.compute(actions)
        al_score = self._average_latency.compute(actions)
        tf_score = self._tool_failure_rate.compute(actions)

        runtime_metrics: dict[str, float] = {
            "planning_accuracy": pa_score,
            "replanning_frequency": rf_score,
            "action_success_rate": asr_score,
            "retry_rate": rr_score,
            "average_latency": al_score,
            "tool_failure_rate": tf_score,
        }

        # ── Overall ───────────────────────────────────────────────────
        all_scores = {**runtime_metrics, **business_metrics}
        overall_result = self._overall_score.compute(all_scores)

        return EvaluationReport(
            dataset_id=dataset.metadata.id,
            overall_score=overall_result["overall"],
            runtime_metrics=runtime_metrics,
            business_metrics=business_metrics,
            passed=overall_result["passed"],
        )

    def run_all(
        self,
        datasets: list[GoldenDataset],
        results: dict[str, HarnessResult],
    ) -> list[EvaluationReport]:
        """Run evaluation for every dataset in *datasets*.

        *results* is a dict keyed by ``dataset.metadata.id``.
        """
        from finance.cognition.state.models import ReasoningState

        def _result(ds: GoldenDataset) -> HarnessResult:
            stored = results.get(ds.metadata.id)
            if stored is not None:
                return stored
            stub = ReasoningState(query=ds.input.query)
            return HarnessResult(state=stub, run_id="", success=False)

        return [self.run(ds, _result(ds)) for ds in datasets]

    def run_all_dict(
        self,
        datasets: list[GoldenDataset],
        pipeline_outputs: dict[str, dict[str, Any]],
    ) -> list[EvaluationReport]:
        """Legacy: run with dict-based pipeline outputs (backward compat).

        Wraps each dict as a minimal HarnessResult stub for backward
        compatibility with existing callers.
        """
        from finance.cognition.state.models import ReasoningState

        reports: list[EvaluationReport] = []
        for ds in datasets:
            out = pipeline_outputs.get(ds.metadata.id, {})
            stub_state = ReasoningState(
                query=ds.input.query,
                context=out,
            )
            stub_result = HarnessResult(
                state=stub_state,
                run_id="legacy",
                success=True,
            )
            reports.append(self.run(ds, stub_result))
        return reports


# ── Headless golden-regression CLI (CI-friendly) ─────────────────────────────


def run_golden_regression(
    dataset_ids: list[str] | None = None,
    fail_on_error: bool = True,
    use_reference_engines: bool = True,
) -> list[GoldenRegressionReport]:
    """Run the golden regression harness over loaded datasets.

    By default the deterministic reference engines are used so the harness
    can run headlessly in CI without the parallel-built analytics/ML layers.
    Returns the per-dataset reports; raises :class:`GoldenRegressionError`
    on the first failure when *fail_on_error* is True.
    """
    harness = _build_golden_harness(use_reference_engines, fail_on_error)
    datasets = _select_golden_datasets(dataset_ids)
    return harness.run_all(datasets)


def _build_golden_harness(
    use_reference_engines: bool, fail_on_error: bool
) -> GoldenRegressionHarness:
    """Construct the harness with reference engines wired for CI."""
    if not use_reference_engines:
        return GoldenRegressionHarness(fail_on_error=fail_on_error)
    return GoldenRegressionHarness(
        analytics=ReferenceAnalyticsEngine(),
        forecast_model=ReferenceForecastModel(),
        anomaly_detector=ReferenceAnomalyDetector(),
        duplicate_detector=ReferenceDuplicateDetector(),
        fail_on_error=fail_on_error,
    )


def _select_golden_datasets(dataset_ids: list[str] | None) -> list[GoldenDataset]:
    """Load all golden datasets and optionally filter by id."""
    loader = GoldenDatasetLoader()
    datasets = loader.load_all()
    if dataset_ids:
        ids = set(dataset_ids)
        datasets = [ds for ds in datasets if ds.metadata.id in ids]
    return datasets


def main(argv: list[str] | None = None) -> int:
    """Headless entry point for CI: ``python -m finance.evaluation.runner``.

    Prints a JSON summary of golden-regression results and returns exit
    code 0 when everything passes, 1 when a regression is detected.
    """
    parser = argparse.ArgumentParser(
        prog="python -m finance.evaluation.runner",
        description="Run the FinSight golden regression harness headlessly.",
    )
    parser.add_argument(
        "--dataset-id",
        action="append",
        default=None,
        help="Only run this dataset id (repeatable). Default: all.",
    )
    parser.add_argument(
        "--no-fail",
        action="store_true",
        help="Report failures without raising / exiting non-zero.",
    )
    args = parser.parse_args(argv)

    try:
        reports = run_golden_regression(
            dataset_ids=args.dataset_id,
            fail_on_error=not args.no_fail,
        )
    except Exception as exc:  # GoldenRegressionError or loader failures
        payload = {"status": "error", "error": str(exc)}
        print(json.dumps(payload, indent=2, default=str))
        return 1

    summary = {
        "status": "ok",
        "total": len(reports),
        "passed": sum(1 for r in reports if r.passed),
        "failed": sum(1 for r in reports if not r.passed),
        "reports": [r.to_dict() for r in reports],
    }
    print(json.dumps(summary, indent=2, default=str))
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
