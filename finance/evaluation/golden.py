"""Golden regression harness for the deterministic analytics + ML layers.

Runs golden datasets through the deterministic analytics layer (variance /
KPI / report engines) and the optional ML layers (forecast, anomaly, and
duplicate detection), then compares the produced outputs against the
expected outputs stored in the dataset with tolerance.

The analytics and ML layers are consumed through thin interfaces
(:class:`AnalyticsEngine`, :class:`ForecastModel`, :class:`AnomalyDetector`,
:class:`DuplicateDetector`).  ``finance/analytics``, ``finance/ml``,
``finance/feature_store`` and ``finance/reasoning`` are built in parallel;
until they land, the harness ships deterministic *reference* implementations
so it can run headlessly in CI.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from pydantic import BaseModel

from finance.evaluation.dataset import (
    DetectionExpectation,
    ForecastExpectation,
    GoldenDataset,
    OutputExpectation,
)
from finance.evaluation.metrics import (
    KPIAccuracy,
    MeanAbsoluteError,
    MeanAbsolutePercentageError,
    PrecisionAtK,
    ReportCoverage,
    RootMeanSquaredError,
    VarianceAccuracy,
)

# ── Thin interfaces for the parallel-built layers ───────────────────────────


class AnalyticsEngine(Protocol):
    """Deterministic analytics layer (assumed shape of ``finance/analytics``).

    Produces the same output envelope the reasoning pipeline stores in state:
    variances, KPIs, and report sections.  Implementations must be
    deterministic and money-safe (Decimal).
    """

    def run(self, dataset: GoldenDataset) -> dict[str, Any]: ...


class ForecastModel(Protocol):
    """Optional ML forecast layer (assumed shape of ``finance/ml``).

    Returns a predicted series aligned with ``dataset.expected.output.forecast``.
    """

    def forecast(self, dataset: GoldenDataset) -> list[Decimal]: ...


class AnomalyDetector(Protocol):
    """Optional ML anomaly layer (assumed shape of ``finance/ml``).

    Returns record ids flagged as anomalies.
    """

    def detect_anomalies(self, dataset: GoldenDataset) -> list[str]: ...


class DuplicateDetector(Protocol):
    """Optional ML duplicate layer (assumed shape of ``finance/ml``).

    Returns record ids flagged as duplicates.
    """

    def detect_duplicates(self, dataset: GoldenDataset) -> list[str]: ...


# ── Reference implementations (deterministic, CI-runnable) ─────────────────


class ReferenceAnalyticsEngine:
    """Deterministic variance/KPI/report analytics used until ``finance/analytics`` lands.

    Computes per-account variance (amount = actual - budget; pct relative to
    budget) and a single KPI derived from the material variance count.
    All monetary arithmetic uses Decimal.
    """

    def run(self, dataset: GoldenDataset) -> dict[str, Any]:
        accounts = dataset.input.context.get("accounts", [])
        variances: list[dict[str, Any]] = []
        for acct in accounts:
            account_id = str(acct.get("id", ""))
            actual = _money(acct.get("actual", 0))
            budget = _money(acct.get("budget", 0))
            variance_amount = actual - budget
            if budget != 0:
                variance_pct = (variance_amount / budget) * Decimal("100")
            else:
                variance_pct = Decimal("0")
            variances.append(
                {
                    "account_id": account_id,
                    "variance_amount": variance_amount,
                    "variance_pct": variance_pct,
                }
            )
        material_count = sum(1 for v in variances if _is_material(v))
        kpis = [{"name": "Material Variance Count", "value": Decimal(material_count)}]
        report_sections = {
            "executive_summary": (
                f"Analysed {len(accounts)} accounts; "
                f"{material_count} material variances."
            )
        }
        return {
            "variances": variances,
            "kpis": kpis,
            "report_sections": report_sections,
        }


class ReferenceForecastModel:
    """Naive forecast: repeats the last observed actual for the horizon.

    Reads ``input.context["history"]`` (observed series) and
    ``input.context["forecast_horizon"]`` (how many steps ahead to predict).
    Serves as a deterministic placeholder for the ML forecast layer.
    """

    def forecast(self, dataset: GoldenDataset) -> list[Decimal]:
        history = dataset.input.context.get("history", [])
        horizon = int(dataset.input.context.get("forecast_horizon", 1))
        if not history:
            return []
        last = _money(history[-1])
        return [last] * horizon


class ReferenceAnomalyDetector:
    """Flags accounts whose variance exceeds a materiality threshold."""

    def __init__(self, materiality_pct: Decimal = Decimal("10")) -> None:
        self._threshold = materiality_pct

    def detect_anomalies(self, dataset: GoldenDataset) -> list[str]:
        accounts = dataset.input.context.get("accounts", [])
        flagged: list[str] = []
        for acct in accounts:
            actual = _money(acct.get("actual", 0))
            budget = _money(acct.get("budget", 0))
            if budget == 0:
                continue
            pct = abs((actual - budget) / budget) * Decimal("100")
            if pct >= self._threshold:
                flagged.append(str(acct.get("id", "")))
        return flagged


class ReferenceDuplicateDetector:
    """Flags accounts that appear more than once with identical values."""

    def detect_duplicates(self, dataset: GoldenDataset) -> list[str]:
        accounts = dataset.input.context.get("accounts", [])
        seen: set[tuple[str, Decimal, Decimal]] = set()
        flagged: list[str] = []
        for acct in accounts:
            key = (
                str(acct.get("id", "")),
                _money(acct.get("actual", 0)),
                _money(acct.get("budget", 0)),
            )
            if key in seen:
                flagged.append(key[0])
            seen.add(key)
        return flagged


# ── Regression harness ──────────────────────────────────────────────────────


class GoldenRegressionError(RuntimeError):
    """Raised by the golden regression harness when a dataset fails."""


class GoldenRegressionReport(BaseModel):
    """Result of running one dataset through the golden regression harness."""

    dataset_id: str
    passed: bool
    metrics: dict[str, float]
    failures: list[str] = []
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


@dataclass
class GoldenRegressionHarness:
    """Runs golden datasets through analytics + optional ML layers.

    Each enabled layer is compared against the dataset's stored expectation
    with tolerance:

    * analytics   → VarianceAccuracy, KPIAccuracy, ReportCoverage
    * forecast    → MAE / RMSE / MAPE vs ``ForecastExpectation`` tolerances
    * anomaly     → Precision@K on expected/forbidden ids
    * duplicate   → Precision@K on expected/forbidden ids

    With ``fail_on_error=True`` a failing dataset raises
    :class:`GoldenRegressionError` (loud failure for CI).  Otherwise the
    report carries the failure list.
    """

    analytics: AnalyticsEngine | None = None
    forecast_model: ForecastModel | None = None
    anomaly_detector: AnomalyDetector | None = None
    duplicate_detector: DuplicateDetector | None = None
    kpi_tolerance: Decimal | None = None
    fail_on_error: bool = False

    def run(self, dataset: GoldenDataset) -> GoldenRegressionReport:
        """Run *dataset* through the harness and return a typed report."""
        metrics: dict[str, float] = {}
        failures: list[str] = []
        out: OutputExpectation = dataset.expected.output

        # ── Analytics layer ──────────────────────────────────────────
        if self.analytics is not None:
            actual = self.analytics.run(dataset)
            va = VarianceAccuracy.compute(out.variances, actual.get("variances", []))
            ka = KPIAccuracy(tolerance=self.kpi_tolerance).compute(
                out.kpis, actual.get("kpis", [])
            )
            rc = ReportCoverage.compute(
                out.report_sections, actual.get("report_sections", {})
            )
            metrics["variance_accuracy"] = va
            metrics["kpi_accuracy"] = ka
            metrics["report_coverage"] = rc
            if va < 1.0 and out.variances:
                failures.append(f"variance_accuracy={va:.3f} < 1.0")
            if ka < 1.0 and out.kpis:
                failures.append(f"kpi_accuracy={ka:.3f} < 1.0")
            if rc < 1.0 and out.report_sections:
                failures.append(f"report_coverage={rc:.3f} < 1.0")

        # ── Forecast layer ───────────────────────────────────────────
        if self.forecast_model is not None and out.forecast is not None:
            failures.extend(
                self._check_forecast(
                    out.forecast, self.forecast_model.forecast(dataset), metrics
                )
            )

        # ── Anomaly layer ────────────────────────────────────────────
        if self.anomaly_detector is not None and out.anomalies is not None:
            failures.extend(
                self._check_detection(
                    "anomaly",
                    out.anomalies,
                    self.anomaly_detector.detect_anomalies(dataset),
                    metrics,
                )
            )

        # ── Duplicate layer ──────────────────────────────────────────
        if self.duplicate_detector is not None and out.duplicates is not None:
            failures.extend(
                self._check_detection(
                    "duplicate",
                    out.duplicates,
                    self.duplicate_detector.detect_duplicates(dataset),
                    metrics,
                )
            )

        report = GoldenRegressionReport(
            dataset_id=dataset.metadata.id,
            passed=not failures,
            metrics=metrics,
            failures=failures,
            detail="; ".join(failures) or "all golden checks passed",
        )
        if self.fail_on_error and not report.passed:
            raise GoldenRegressionError(
                f"Golden regression failed for '{dataset.metadata.id}': "
                f"{report.detail}"
            )
        return report

    def run_all(
        self, datasets: list[GoldenDataset]
    ) -> list[GoldenRegressionReport]:
        """Run every dataset and raise on the first failure if configured."""
        return [self.run(ds) for ds in datasets]

    # ── Internal checkers ────────────────────────────────────────────

    def _check_forecast(
        self,
        expected: ForecastExpectation,
        predicted: list[Decimal],
        metrics: dict[str, float],
    ) -> list[str]:
        """Compare the model's forecast against the stored golden series.

        The golden ``predicted`` series is the recorded expected output of
        the forecast layer.  MAE / RMSE / MAPE measure how far the current
        model output has drifted from that golden output; each must stay
        within its configured tolerance.  ``actuals`` are the ground-truth
        observed series used to build the golden output.
        """
        failures: list[str] = []
        if len(predicted) != len(expected.predicted):
            return [
                f"forecast: length mismatch "
                f"(got {len(predicted)}, expected {len(expected.predicted)})"
            ]
        if not expected.predicted:
            return failures

        mae = MeanAbsoluteError.compute(expected.predicted, predicted)
        rmse = RootMeanSquaredError.compute(expected.predicted, predicted)
        mape = MeanAbsolutePercentageError.compute(expected.predicted, predicted)

        if mae is None or rmse is None or mape is None:
            return ["forecast: degenerate series (empty or mismatched length)"]

        metrics["forecast_mae"] = float(mae)
        metrics["forecast_rmse"] = float(rmse)
        metrics["forecast_mape"] = float(mape)

        if mae > expected.tolerance_mae:
            failures.append(f"forecast_mae={mae} > tol={expected.tolerance_mae}")
        if rmse > expected.tolerance_rmse:
            failures.append(f"forecast_rmse={rmse} > tol={expected.tolerance_rmse}")
        if mape > expected.tolerance_mape:
            failures.append(f"forecast_mape={mape} > tol={expected.tolerance_mape}")
        return failures

    def _check_detection(
        self,
        layer: str,
        expected: DetectionExpectation,
        detected: list[str],
        metrics: dict[str, float],
    ) -> list[str]:
        failures: list[str] = []
        p_at_k = PrecisionAtK.compute(expected.expected_ids, detected, expected.k)
        metrics[f"{layer}_precision_at_k"] = p_at_k
        if p_at_k < 1.0 and expected.expected_ids:
            failures.append(f"{layer}_precision_at_k={p_at_k:.3f} < 1.0")
        forbidden_hits = set(detected) & set(expected.forbidden_ids)
        if forbidden_hits:
            failures.append(
                f"{layer}: forbidden ids flagged: {sorted(forbidden_hits)}"
            )
        return failures


# ── Internal helpers ─────────────────────────────────────────────────────────


def _money(value: Any) -> Decimal:
    """Convert a raw JSON/context value to Decimal without float precision loss."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        raise TypeError(
            "Float values are not allowed for monetary fields. "
            "Use decimal.Decimal, int, or str instead."
        )
    return Decimal(str(value))


def _is_material(variance: dict[str, Any]) -> bool:
    """A variance is material when its amount is non-zero."""
    try:
        return abs(_money(variance.get("variance_amount", 0))) > 0
    except (TypeError, ValueError):
        return False
