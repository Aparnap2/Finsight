"""Cash-flow forecast model — LightGBM time-series regression.

CPU-first forecaster per ``docs/09-platform/mlops.md``: a LightGBM
regressor trained on lag features (28/56/90-day) with recursive
single-step forecasting over a rolling horizon. Monetary forecast values
are converted to ``decimal.Decimal`` at the output boundary.

Optional dependencies:
    - ``lightgbm`` — gradient-boosted regressor (training + prediction).
    - ``shap`` — model explainability (``TreeExplainer``).

Degraded mode: when ``lightgbm`` is unavailable the model falls back to a
deterministic trailing-mean baseline forecast (``degraded=True``); when
``shap`` is unavailable explainability falls back to normalized
lag-target correlation. Neither failure crashes the pipeline.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import polars as pl
from pydantic import BaseModel, Field

from finance.ml.fallback import import_optional
from finance.ml.protocol import ModelMetadata, RiskEvaluation

logger = logging.getLogger(__name__)

#: Lag windows (days) used as training features — matches the MLOps doc's
#: "28d, 56d, 90d" cash-flow feature design.
DEFAULT_LAGS: tuple[int, ...] = (28, 56, 90)

#: Required input columns of the feature batch.
REQUIRED_COLUMNS: frozenset[str] = frozenset({"date", "cash_position"})


def _to_decimal(value: float) -> Decimal:
    """Convert a model output to ``Decimal`` — the money boundary.

    ``str(round(...))`` avoids binary float representation artifacts.
    """
    return Decimal(str(round(float(value), 2)))


def _lag_row(series: list[float], lags: tuple[int, ...]) -> list[float]:
    """Build one lag-feature row from a value series (missing lags -> 0.0)."""
    return [series[-lag] if len(series) >= lag else 0.0 for lag in lags]


def _lag_rows(series: list[float], lags: tuple[int, ...]) -> tuple[list[list[float]], list[float]]:
    """Build the supervised training set from a value series.

    Returns ``(rows, targets)`` where each row is the lag vector ending at
    position ``i`` and the target is the value at position ``i``.
    """
    max_lag = max(lags)
    rows: list[list[float]] = []
    targets: list[float] = []
    for i in range(max_lag, len(series)):
        rows.append(_lag_row(series[:i], lags))
        targets.append(series[i])
    return rows, targets


def _mean(values: list[float]) -> float:
    """Deterministic arithmetic mean over a float list (0.0 when empty)."""
    return sum(values) / len(values) if values else 0.0


def _stdev(values: list[float]) -> float:
    """Deterministic population standard deviation (0.0 when degenerate)."""
    n = len(values)
    if n < 2:
        return 0.0
    mean = _mean(values)
    variance = float(sum((v - mean) ** 2 for v in values)) / n
    return math.sqrt(variance)


def _clamp01(value: float) -> float:
    """Clamp a value into the closed interval [0.0, 1.0]."""
    return max(0.0, min(1.0, value))


class CashFlowPoint(BaseModel):
    """A single forecast point. Monetary value is ``Decimal`` — never float."""

    period: str  # ISO date string
    amount: Decimal


class CashFlowForecast(BaseModel):
    """Typed output of the cash-flow forecaster."""

    model_id: str
    version: str
    horizon_days: int
    points: list[CashFlowPoint] = Field(default_factory=list)
    confidence: float = 0.0
    degraded: bool = False
    degradation_reason: str | None = None

    @property
    def total(self) -> Decimal:
        """Sum of forecast amounts (Decimal arithmetic)."""
        total = Decimal("0")
        for point in self.points:
            total += point.amount
        return total

    @property
    def min_amount(self) -> Decimal:
        """Minimum forecast amount — the liquidity stress point."""
        if not self.points:
            return Decimal("0")
        return min((point.amount for point in self.points), default=Decimal("0"))


class CashFlowExplain(BaseModel):
    """SHAP-style feature attribution for a cash-flow forecast."""

    model_id: str
    version: str
    contributions: dict[str, float] = Field(default_factory=dict)
    degraded: bool = False
    degradation_reason: str | None = None


class CashFlowForecastModel:
    """LightGBM cash-flow forecaster with deterministic degraded mode."""

    def __init__(
        self,
        *,
        model_id: str = "cashflow",
        version: str = "1.0.0",
        lags: tuple[int, ...] = DEFAULT_LAGS,
        horizon_days: int = 13,
    ) -> None:
        self.model_id = model_id
        # Canonical PredictiveProvider identifier (shared with finance/analytics).
        self.name = model_id
        self.version = version
        self._lags = lags
        self._horizon_days = horizon_days
        # Lazy optional dependencies — None when not installed.
        self._lgbm: Any = import_optional("lightgbm")
        self._shap: Any = import_optional("shap")
        self._model: Any = None
        self._trained: bool = False
        self._feature_names: list[str] = []
        self._training_start: datetime | None = None
        self._training_end: datetime | None = None
        self._training_rows: int = 0
        self._metrics: dict[str, Any] = {}
        self._baseline_mean: float | None = None
        # Training rows retained only for the deterministic explain fallback.
        self._train_rows: list[list[float]] = []
        self._train_targets: list[float] = []

    @property
    def available(self) -> bool:
        """True when the LightGBM backend is importable."""
        return self._lgbm is not None

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train(
        self,
        features: pl.DataFrame,
        *,
        target_column: str = "cash_position",
        horizon_days: int | None = None,
    ) -> CashFlowForecastModel:
        """Train (or, in degraded mode, calibrate the baseline) the model.

        Builds the lag feature set from the historical series, fits a
        LightGBM regressor when available, and otherwise records the
        deterministic baseline statistics (trailing mean) used by
        :meth:`predict`. Returns ``self`` for chaining.
        """
        self._validate_features(features)
        self._training_rows = features.height
        now = datetime.now(UTC)
        self._training_end = now
        if horizon_days is not None:
            self._horizon_days = horizon_days

        series = self._series_from(features, target_column)
        rows, targets = _lag_rows(series, self._lags)
        self._feature_names = [f"lag_{lag}d" for lag in self._lags]
        self._baseline_mean = _mean(series)

        if self._lgbm is None:
            # Degraded mode: deterministic baseline only.
            self._trained = True
            self._metrics = {"algorithm": "deterministic_baseline"}
            self._train_rows = rows
            self._train_targets = targets
            logger.warning(
                "lightgbm unavailable — %s degraded to deterministic baseline", self.model_id
            )
            return self

        lgbm_regressor_cls = self._lgbm.LGBMRegressor
        regressor = lgbm_regressor_cls(
            n_estimators=50, max_depth=4, learning_rate=0.1, random_state=42, verbose=-1
        )
        regressor.fit(rows, targets)
        self._model = regressor
        self._trained = True
        # In-sample MAPE as a rough confidence signal (offline eval refines it).
        predictions = [float(p) for p in regressor.predict(rows)]
        self._metrics = {
            "mape": self._mape(targets, predictions),
            "rmse": self._rmse(targets, predictions),
        }
        if self._shap is None:
            # Retain rows only when explainability must be approximated.
            self._train_rows = rows
            self._train_targets = targets
        return self

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    def predict(
        self,
        features: pl.DataFrame,
        *,
        horizon_days: int | None = None,
    ) -> CashFlowForecast:
        """Forecast ``horizon_days`` future cash positions.

        Uses recursive single-step prediction against the trained regressor
        when available; otherwise produces a deterministic trailing-mean
        baseline. All forecast amounts are ``Decimal``.
        """
        horizon = horizon_days if horizon_days is not None else self._horizon_days
        series = self._series_from(features, "cash_position")
        anchor = self._anchor_date(features)

        if not self._trained or self._model is None:
            reason = "model not trained" if not self._trained else "lightgbm unavailable"
            return self._baseline_forecast(series, horizon, anchor, reason)

        buffer = list(series[-max(self._lags):])
        for _ in range(horizon):
            row = _lag_row(buffer, self._lags)
            prediction = float(self._model.predict([row])[0])
            buffer.append(prediction)

        points = [
            CashFlowPoint(
                period=(anchor + timedelta(days=step + 1)).isoformat(),
                amount=_to_decimal(buffer[-horizon + step] if horizon > 0 else 0.0),
            )
            for step in range(horizon)
        ]
        confidence = _clamp01(1.0 - self._metrics.get("mape", 0.5))
        return CashFlowForecast(
            model_id=self.model_id,
            version=self.version,
            horizon_days=horizon,
            points=points,
            confidence=confidence,
        )

    def explain(self, features: pl.DataFrame) -> CashFlowExplain:
        """Return per-feature attribution (SHAP when available).

        Deterministic fallback: normalized absolute lag-target correlation
        computed from the retained training rows.
        """
        series = self._series_from(features, "cash_position")
        if self._shap is not None and self._model is not None:
            rows, _ = _lag_rows(series, self._lags)
            if not rows:
                return CashFlowExplain(
                    model_id=self.model_id, version=self.version, degraded=True
                )
            explainer = self._shap.TreeExplainer(self._model)
            shap_values = explainer.shap_values(rows)
            per_feature = [
                sum(abs(row[j]) for row in shap_values) / len(shap_values)
                for j in range(len(self._feature_names))
            ]
            contributions = self._normalize(per_feature)
            return CashFlowExplain(
                model_id=self.model_id,
                version=self.version,
                contributions=dict(zip(self._feature_names, contributions, strict=False)),
            )

        # Deterministic correlation-based attribution (no shap installed).
        if not self._train_rows or not self._feature_names:
            return CashFlowExplain(
                model_id=self.model_id,
                version=self.version,
                degraded=True,
                degradation_reason="no training data retained for attribution",
            )
        corr_contributions = self._correlation_contributions()
        return CashFlowExplain(
            model_id=self.model_id,
            version=self.version,
            contributions=corr_contributions,
            degraded=True,
            degradation_reason="shap unavailable — normalized lag-target correlation used",
        )

    # ------------------------------------------------------------------
    # RiskProvider
    # ------------------------------------------------------------------

    def evaluate(self, context: dict[str, Any]) -> RiskEvaluation:
        """Score forecast liquidity risk for a single entity context.

        Risk is driven by the forecast's downside: the ratio of negative
        points in the horizon and the depth of the minimum balance.
        """
        entity_id = str(context.get("entity_id", "unknown"))
        amount = context.get("cash_position", Decimal("0"))
        features = pl.DataFrame(
            {
                "date": [str(context.get("date", date.today().isoformat()))],
                "cash_position": [amount],
            }
        )
        forecast = self.predict(features)
        points = forecast.points
        if not points:
            score = 0.0
            evidence: list[dict[str, Any]] = [{"detail": "no forecast points produced"}]
        else:
            negative_ratio = sum(1 for p in points if p.amount < 0) / len(points)
            abs_values = [abs(p.amount) for p in points]
            denominator = max(abs_values) if abs_values else Decimal("1")
            dip_ratio = float(abs(forecast.min_amount) / denominator) if denominator else 0.0
            score = _clamp01(0.5 * negative_ratio + 0.5 * dip_ratio)
            evidence = [
                {
                    "horizon_days": len(points),
                    "min_amount": str(forecast.min_amount),
                    "total": str(forecast.total),
                    "negative_ratio": negative_ratio,
                }
            ]
        metadata: dict[str, Any] = {
            "model_version": self.version,
            "degraded": forecast.degraded,
            "degradation_reason": forecast.degradation_reason,
        }
        return RiskEvaluation(
            provider_id=self.model_id,
            entity_id=entity_id,
            score=score,
            confidence=forecast.confidence,
            evidence=evidence,
            metadata=metadata,
            evaluated_at=datetime.now(UTC),
        )

    def metadata(self) -> ModelMetadata:
        """Return model metadata: schema, training window, metrics."""
        return ModelMetadata(
            model_id=self.model_id,
            version=self.version,
            algorithm="lightgbm" if self._model is not None else "deterministic_baseline",
            training_start=self._training_start,
            training_end=self._training_end,
            training_rows=self._training_rows,
            feature_count=len(self._feature_names),
            feature_names=list(self._feature_names),
            target_column="cash_position",
            metrics=dict(self._metrics),
            framework_version=self._framework_version(),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _baseline_forecast(
        self,
        series: list[float],
        horizon: int,
        anchor: date,
        reason: str,
    ) -> CashFlowForecast:
        """Deterministic trailing-mean baseline (degraded mode)."""
        baseline = _mean(series) if series else (self._baseline_mean or 0.0)
        points = [
            CashFlowPoint(
                period=(anchor + timedelta(days=step + 1)).isoformat(),
                amount=_to_decimal(baseline),
            )
            for step in range(horizon)
        ]
        return CashFlowForecast(
            model_id=self.model_id,
            version=self.version,
            horizon_days=horizon,
            points=points,
            confidence=0.25,
            degraded=True,
            degradation_reason=reason,
        )

    def _series_from(self, features: pl.DataFrame, target: str) -> list[float]:
        """Extract the target series, converting Decimal money to float at the boundary."""
        values = features.select(pl.col(target).cast(pl.Float64)).to_series().to_list()
        return [float(v) for v in values]

    def _validate_features(self, features: pl.DataFrame) -> None:
        """Raise ValueError when required cash-flow columns are missing."""
        missing = sorted(REQUIRED_COLUMNS - set(features.columns))
        if missing:
            raise ValueError(
                f"{self.model_id} requires columns {sorted(REQUIRED_COLUMNS)}, missing: {missing}"
            )

    def _anchor_date(self, features: pl.DataFrame) -> date:
        """Last observation date; falls back to today when unparseable."""
        last = (
            features.select(pl.col("date")).to_series().to_list()[-1]
            if features.height
            else None
        )
        if last is None:
            return date.today()
        try:
            return date.fromisoformat(str(last))
        except ValueError:
            return date.today()

    def _framework_version(self) -> str:
        if self._lgbm is None:
            return "lightgbm not installed"
        return f"lightgbm=={getattr(self._lgbm, '__version__', 'unknown')}"

    def _correlation_contributions(self) -> dict[str, float]:
        """Deterministic attribution: normalized |lag-target correlation|."""
        target_mean = _mean(self._train_targets)
        target_std = _stdev(self._train_targets)
        contributions: list[float] = []
        for j in range(len(self._feature_names)):
            feature_values = [row[j] for row in self._train_rows]
            feature_mean = _mean(feature_values)
            feature_std = _stdev(feature_values)
            if feature_std == 0.0 or target_std == 0.0:
                contributions.append(0.0)
                continue
            covariance = _mean(
                [
                    (row[j] - feature_mean) * (target - target_mean)
                    for row, target in zip(self._train_rows, self._train_targets, strict=False)
                ]
            )
            contributions.append(abs(covariance / (feature_std * target_std)))
        total = sum(contributions) or 1.0
        normalized = [c / total for c in contributions]
        return dict(zip(self._feature_names, normalized, strict=False))

    @staticmethod
    def _normalize(values: list[float]) -> list[float]:
        """Scale a list of non-negative values to sum to 1.0 (zeros kept)."""
        total = sum(values)
        if total <= 0.0:
            return [0.0] * len(values)
        return [v / total for v in values]

    @staticmethod
    def _mape(actual: list[float], predicted: list[float]) -> float:
        """Mean absolute percentage error (0.0 when no signal)."""
        if not actual:
            return 0.0
        total = sum(
            abs(a - p) / abs(a) for a, p in zip(actual, predicted, strict=False) if a != 0
        )
        return float(total) / len(actual)

    @staticmethod
    def _rmse(actual: list[float], predicted: list[float]) -> float:
        """Root mean squared error."""
        if not actual:
            return 0.0
        squared_errors = float(
            sum((a - p) ** 2 for a, p in zip(actual, predicted, strict=False))
        )
        return math.sqrt(squared_errors / len(actual))
