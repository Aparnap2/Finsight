"""Tests for golden regression harness — reference engines, tolerances, CI CLI."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from finance.evaluation.dataset import (
    DatasetInput,
    DatasetMetadata,
    DetectionExpectation,
    ExpectedBehaviour,
    ForecastExpectation,
    GoldenDataset,
    OutputExpectation,
)
from finance.evaluation.golden import (
    GoldenRegressionError,
    GoldenRegressionHarness,
    GoldenRegressionReport,
    ReferenceAnalyticsEngine,
    ReferenceAnomalyDetector,
    ReferenceDuplicateDetector,
    ReferenceForecastModel,
    _money,
)
from finance.evaluation.loader import GoldenDatasetLoader
from finance.evaluation.runner import main, run_golden_regression


def _accounts() -> list[dict[str, Any]]:
    """Deterministic account fixture with one material variance."""
    return [
        {"id": "4010", "name": "Product Revenue", "actual": 1250000, "budget": 1000000},
        {"id": "4020", "name": "Service Revenue", "actual": 750000, "budget": 700000},
        {"id": "5010", "name": "Payroll", "actual": 400000, "budget": 395000},
    ]


def _base_dataset(**overrides: Any) -> GoldenDataset:
    raw = {
        "metadata": DatasetMetadata(id="unit_golden", name="Unit Golden", category="regression"),
        "input": DatasetInput(query="Run golden regression", context={"accounts": _accounts()}),
        "expected": ExpectedBehaviour(output=OutputExpectation()),
    }
    raw.update(overrides)
    return GoldenDataset(**raw)


# ── Reference engines ─────────────────────────────────────────────────────────


class TestReferenceAnalyticsEngine:
    def test_computes_variance_amount_and_pct(self) -> None:
        out = ReferenceAnalyticsEngine().run(_base_dataset())
        variances = {v["account_id"]: v for v in out["variances"]}

        assert variances["4010"]["variance_amount"] == Decimal("250000")
        assert variances["4010"]["variance_pct"] == Decimal("25")
        assert variances["5010"]["variance_amount"] == Decimal("5000")

    def test_materiality_kpi_counts_nonzero_variances(self) -> None:
        out = ReferenceAnalyticsEngine().run(_base_dataset())
        assert out["kpis"] == [{"name": "Material Variance Count", "value": Decimal(3)}]

    def test_report_sections_contains_executive_summary(self) -> None:
        out = ReferenceAnalyticsEngine().run(_base_dataset())
        assert "Analysed 3 accounts" in out["report_sections"]["executive_summary"]


class TestReferenceForecastModel:
    def test_naive_repeats_last_observed_value(self) -> None:
        ds = _base_dataset(
            input=DatasetInput(
                query="forecast",
                context={"history": [100, 110, 121], "forecast_horizon": 2},
            )
        )
        assert ReferenceForecastModel().forecast(ds) == [Decimal("121"), Decimal("121")]

    def test_empty_history_returns_empty_series(self) -> None:
        ds = _base_dataset(input=DatasetInput(query="forecast", context={"history": []}))
        assert ReferenceForecastModel().forecast(ds) == []


class TestReferenceAnomalyDetector:
    def test_flags_only_material_variances(self) -> None:
        flagged = ReferenceAnomalyDetector().detect_anomalies(_base_dataset())
        assert flagged == ["4010"]

    def test_custom_materiality_threshold(self) -> None:
        detector = ReferenceAnomalyDetector(materiality_pct=Decimal("5"))
        flagged = detector.detect_anomalies(_base_dataset())
        assert flagged == ["4010", "4020"]


class TestReferenceDuplicateDetector:
    def test_flags_repeated_identical_rows(self) -> None:
        accounts = [
            {"id": "4010", "name": "Product Revenue", "actual": 1250000, "budget": 1000000},
            {"id": "4010", "name": "Product Revenue", "actual": 1250000, "budget": 1000000},
            {"id": "4020", "name": "Service Revenue", "actual": 750000, "budget": 700000},
        ]
        ds = _base_dataset(input=DatasetInput(query="dupes", context={"accounts": accounts}))
        assert ReferenceDuplicateDetector().detect_duplicates(ds) == ["4010"]


# ── Money safety ──────────────────────────────────────────────────────────────


class TestMoneySafety:
    def test_money_accepts_decimal_int_str(self) -> None:
        assert _money(Decimal("1.5")) == Decimal("1.5")
        assert _money(5) == Decimal("5")
        assert _money("1.50") == Decimal("1.50")

    def test_money_rejects_float(self) -> None:
        with pytest.raises(TypeError):
            _money(1.5)


# ── GoldenRegressionHarness ───────────────────────────────────────────────────


class TestGoldenRegressionHarness:
    def test_pass_when_forecast_matches_expectation(self) -> None:
        ds = _base_dataset(
            input=DatasetInput(
                query="forecast",
                context={"history": [100, 110, 121], "forecast_horizon": 2},
            ),
            expected=ExpectedBehaviour(
                output=OutputExpectation(
                    forecast=ForecastExpectation(
                        actuals=[100, 110, 121],
                        predicted=[121, 121],
                        tolerance_mae=Decimal("0.01"),
                        tolerance_rmse=Decimal("0.01"),
                        tolerance_mape=Decimal("0.001"),
                    )
                )
            ),
        )
        harness = GoldenRegressionHarness(forecast_model=ReferenceForecastModel())
        report = harness.run(ds)
        assert report.passed is True
        assert report.failures == []
        assert report.metrics["forecast_mae"] == 0.0

    def test_fails_loudly_when_forecast_drifts(self) -> None:
        ds = _base_dataset(
            input=DatasetInput(
                query="forecast",
                context={"history": [100, 110, 121], "forecast_horizon": 2},
            ),
            expected=ExpectedBehaviour(
                output=OutputExpectation(
                    forecast=ForecastExpectation(
                        actuals=[100, 110, 121],
                        predicted=[130, 130],
                        tolerance_mae=Decimal("0.01"),
                        tolerance_rmse=Decimal("0.01"),
                        tolerance_mape=Decimal("0.001"),
                    )
                )
            ),
        )
        harness = GoldenRegressionHarness(
            forecast_model=ReferenceForecastModel(), fail_on_error=True
        )
        with pytest.raises(GoldenRegressionError):
            harness.run(ds)

    def test_reports_failure_instead_of_raising_when_not_fail_on_error(self) -> None:
        ds = _base_dataset(
            input=DatasetInput(
                query="forecast",
                context={"history": [100, 110, 121], "forecast_horizon": 2},
            ),
            expected=ExpectedBehaviour(
                output=OutputExpectation(
                    forecast=ForecastExpectation(
                        actuals=[100, 110, 121],
                        predicted=[130, 130],
                        tolerance_mae=Decimal("0.01"),
                        tolerance_rmse=Decimal("0.01"),
                        tolerance_mape=Decimal("0.001"),
                    )
                )
            ),
        )
        harness = GoldenRegressionHarness(forecast_model=ReferenceForecastModel())
        report = harness.run(ds)
        assert report.passed is False
        assert any("forecast_mae" in f for f in report.failures)

    def test_forecast_length_mismatch_fails(self) -> None:
        ds = _base_dataset(
            input=DatasetInput(
                query="forecast",
                context={"history": [100, 110, 121], "forecast_horizon": 2},
            ),
            expected=ExpectedBehaviour(
                output=OutputExpectation(
                    forecast=ForecastExpectation(predicted=[121])  # wrong length
                )
            ),
        )
        harness = GoldenRegressionHarness(forecast_model=ReferenceForecastModel())
        report = harness.run(ds)
        assert report.passed is False
        assert any("length mismatch" in f for f in report.failures)

    def test_detection_precision_at_k(self) -> None:
        ds = _base_dataset(
            expected=ExpectedBehaviour(
                output=OutputExpectation(
                    anomalies=DetectionExpectation(
                        expected_ids=["4010"], forbidden_ids=["4020", "5010"], k=3
                    )
                )
            )
        )
        harness = GoldenRegressionHarness(anomaly_detector=ReferenceAnomalyDetector())
        report = harness.run(ds)
        assert report.passed is True
        assert report.metrics["anomaly_precision_at_k"] == 1.0

    def test_detection_forbidden_ids_flagged(self) -> None:
        class FlagEverything:
            def detect_anomalies(self, ds: Any) -> list[str]:
                return ["4010", "4020", "5010"]

        ds = _base_dataset(
            expected=ExpectedBehaviour(
                output=OutputExpectation(
                    anomalies=DetectionExpectation(
                        expected_ids=["4010"], forbidden_ids=["4020"], k=3
                    )
                )
            )
        )
        harness = GoldenRegressionHarness(anomaly_detector=FlagEverything())
        report = harness.run(ds)
        assert report.passed is False
        assert any("forbidden ids flagged" in f for f in report.failures)

    def test_run_all_returns_reports_for_each_dataset(self) -> None:
        ds1 = _base_dataset(
            expected=ExpectedBehaviour(
                output=OutputExpectation(
                    forecast=ForecastExpectation(
                        actuals=[100, 110, 121],
                        predicted=[121, 121],
                        tolerance_mae=Decimal("0.01"),
                        tolerance_rmse=Decimal("0.01"),
                        tolerance_mape=Decimal("0.001"),
                    )
                )
            )
        )
        ds1.input.context["history"] = [100, 110, 121]
        ds1.input.context["forecast_horizon"] = 2
        reports = GoldenRegressionHarness(
            forecast_model=ReferenceForecastModel()
        ).run_all([ds1])
        assert isinstance(reports[0], GoldenRegressionReport)
        assert reports[0].dataset_id == "unit_golden"

    def test_report_to_dict_is_json_serialisable(self) -> None:
        report = GoldenRegressionReport(dataset_id="x", passed=True, metrics={"m": 1.0})
        assert report.to_dict()["dataset_id"] == "x"


# ── Regression datasets on disk ───────────────────────────────────────────────


class TestRegressionDatasets:
    def test_loader_discovers_regression_datasets(self) -> None:
        loader = GoldenDatasetLoader()
        assert loader.load("regression_forecast_naive") is not None
        assert loader.load("regression_anomaly_materiality") is not None
        assert loader.load("regression_duplicate_rows") is not None

    def test_regression_forecast_dataset_passes_with_reference_engines(self) -> None:
        reports = run_golden_regression(dataset_ids=["regression_forecast_naive"])
        assert reports[0].passed is True

    def test_regression_anomaly_dataset_passes_with_reference_engines(self) -> None:
        reports = run_golden_regression(dataset_ids=["regression_anomaly_materiality"])
        assert reports[0].passed is True

    def test_regression_duplicate_dataset_passes_with_reference_engines(self) -> None:
        reports = run_golden_regression(dataset_ids=["regression_duplicate_rows"])
        assert reports[0].passed is True


# ── Headless CLI ──────────────────────────────────────────────────────────────


class TestGoldenRegressionCli:
    def test_main_returns_zero_on_pass(self, capsys: pytest.CaptureFixture[str]) -> None:
        code = main(["--dataset-id", "regression_forecast_naive"])
        captured = capsys.readouterr()
        assert code == 0
        assert '"status": "ok"' in captured.out

    def test_main_returns_one_when_regression_fails(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def _boom(*args: Any, **kwargs: Any) -> None:
            raise GoldenRegressionError("synthetic regression failure")

        monkeypatch.setattr(
            "finance.evaluation.runner.run_golden_regression", _boom
        )
        code = main(["--dataset-id", "regression_forecast_naive"])
        captured = capsys.readouterr()
        assert code == 1
        assert '"status": "error"' in captured.out
