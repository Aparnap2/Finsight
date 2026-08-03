"""Anomaly detection model — Isolation Forest with z-score fallback.

CPU-first unsupervised anomaly detection per ``docs/09-platform/mlops.md``:
Isolation Forest on engineered numeric features (amount Z-score,
inter-payment interval, hour-of-day, ...). Monetary features arrive as
``Decimal`` and are converted to float only at the model boundary.

Optional dependencies:
    - ``sklearn.ensemble`` — Isolation Forest (training + scoring).

Degraded mode: when scikit-learn is unavailable the model falls back to a
deterministic per-feature Z-score rule (``z_threshold``) computed from the
training distribution. The fallback is fully deterministic and needs no
ML dependencies.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import polars as pl
from pydantic import BaseModel, Field

from finance.ml.fallback import import_optional
from finance.ml.protocol import ModelMetadata, RiskEvaluation

logger = logging.getLogger(__name__)


def _clamp01(value: float) -> float:
    """Clamp a value into the closed interval [0.0, 1.0]."""
    return max(0.0, min(1.0, value))


class AnomalyScore(BaseModel):
    """Anomaly score for a single row. Higher score = more anomalous."""

    row_id: str
    score: float  # 0.0 (normal) to 1.0 (strong anomaly)
    is_anomaly: bool
    confidence: float
    feature_contributions: dict[str, float] = Field(default_factory=dict)


class AnomalyResult(BaseModel):
    """Typed output of the anomaly detector."""

    model_id: str
    version: str
    scores: list[AnomalyScore] = Field(default_factory=list)
    degraded: bool = False
    degradation_reason: str | None = None


class AnomalyDetectionModel:
    """Isolation Forest anomaly detector with deterministic Z-score fallback."""

    def __init__(
        self,
        *,
        model_id: str = "payment_anomaly",
        version: str = "1.0.0",
        contamination: float = 0.05,
        z_threshold: float = 3.0,
    ) -> None:
        self.model_id = model_id
        # Canonical PredictiveProvider identifier (shared with finance/analytics).
        self.name = model_id
        self.version = version
        self._contamination = contamination
        self._z_threshold = z_threshold
        # Lazy optional dependency — None when scikit-learn is not installed.
        self._sklearn_ensemble: Any = import_optional("sklearn.ensemble")
        self._iforest: Any = None
        self._id_column: str = "entity_id"
        self._numeric_features: list[str] = []
        self._stats: dict[str, tuple[float, float]] = {}  # feature -> (mean, std)
        self._trained: bool = False
        self._training_rows: int = 0
        self._training_end: datetime | None = None
        self._metrics: dict[str, Any] = {}

    @property
    def available(self) -> bool:
        """True when the scikit-learn backend is importable."""
        return self._sklearn_ensemble is not None

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train(
        self,
        features: pl.DataFrame,
        *,
        id_column: str = "entity_id",
        feature_columns: list[str] | None = None,
    ) -> AnomalyDetectionModel:
        """Fit the Isolation Forest (when available) and always record the
        deterministic feature statistics used by the Z-score fallback.

        ``feature_columns`` selects the numeric feature set; defaults to all
        columns except the id column. Returns ``self`` for chaining.
        """
        self._id_column = id_column
        self._numeric_features = self._resolve_features(features, feature_columns)
        self._training_rows = features.height
        self._training_end = datetime.now(UTC)

        frame = self._numeric_frame(features)
        rows = [[float(row[col]) for col in self._numeric_features] for row in frame.to_dicts()]
        self._stats = self._feature_stats(rows)
        self._trained = True

        if self._sklearn_ensemble is None:
            self._metrics = {"algorithm": "zscore_fallback"}
            logger.warning(
                "scikit-learn unavailable — %s degraded to Z-score rule", self.model_id
            )
            return self

        isolation_forest_cls = self._sklearn_ensemble.IsolationForest
        forest = isolation_forest_cls(
            n_estimators=50, contamination=self._contamination, random_state=42
        )
        forest.fit(rows)
        self._iforest = forest
        self._metrics = {"algorithm": "isolation_forest", "contamination": self._contamination}
        return self

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    def predict(self, features: pl.DataFrame) -> AnomalyResult:
        """Score every row and flag anomalies with confidence.

        Uses the trained Isolation Forest when available; otherwise the
        deterministic Z-score rule. Monetary feature columns (Decimal) are
        converted to float at the model boundary.
        """
        if not self._trained:
            return AnomalyResult(
                model_id=self.model_id,
                version=self.version,
                scores=[],
                degraded=True,
                degradation_reason="model not trained",
            )

        frame = self._numeric_frame(features)
        rows = [[float(row[col]) for col in self._numeric_features] for row in frame.to_dicts()]
        ids = self._row_ids(features)

        if self._iforest is not None:
            raw_scores = list(self._iforest.decision_function(rows))
            labels = list(self._iforest.predict(rows))
            scores = [
                self._build_score(
                    row_id=ids[i],
                    score=_clamp01(0.5 - float(raw_scores[i])),
                    is_anomaly=int(labels[i]) == -1,
                    confidence=_clamp01(abs(float(raw_scores[i])) * 2.0),
                    z_row=self._z_scores(rows[i]),
                )
                for i in range(len(rows))
            ]
            return AnomalyResult(model_id=self.model_id, version=self.version, scores=scores)

        # Deterministic Z-score fallback (no scikit-learn).
        scores = [
            self._build_score(
                row_id=ids[i],
                score=self._z_row_score(rows[i]),
                is_anomaly=self._z_max(rows[i]) > self._z_threshold,
                confidence=_clamp01(self._z_row_score(rows[i]) / (2.0 * self._z_threshold)),
                z_row=self._z_scores(rows[i]),
            )
            for i in range(len(rows))
        ]
        return AnomalyResult(
            model_id=self.model_id,
            version=self.version,
            scores=scores,
            degraded=True,
            degradation_reason="scikit-learn unavailable — Z-score rule used",
        )

    # ------------------------------------------------------------------
    # RiskProvider
    # ------------------------------------------------------------------

    def evaluate(self, context: dict[str, Any]) -> RiskEvaluation:
        """Score a single entity for anomaly risk.

        The context is a feature dict for one entity; missing numeric
        features default to 0.0. The anomaly score maps directly to risk.
        """
        entity_id = str(context.get("entity_id", "unknown"))
        if not self._trained:
            return RiskEvaluation(
                provider_id=self.model_id,
                entity_id=entity_id,
                score=0.0,
                confidence=0.0,
                evidence=[{"detail": "model not trained"}],
                metadata={"degraded": True, "degradation_reason": "model not trained"},
                evaluated_at=datetime.now(UTC),
            )
        features = self._context_to_features(context, entity_id)
        result = self.predict(features)
        top = max(result.scores, key=lambda s: s.score) if result.scores else None
        if top is None:
            score = 0.0
            evidence: list[dict[str, Any]] = [{"detail": "no rows scored"}]
        else:
            score = top.score
            evidence = [
                {
                    "is_anomaly": top.is_anomaly,
                    "feature_contributions": top.feature_contributions,
                }
            ]
        return RiskEvaluation(
            provider_id=self.model_id,
            entity_id=top.row_id if top is not None else entity_id,
            score=score,
            confidence=top.confidence if top is not None else 0.0,
            evidence=evidence,
            metadata={
                "model_version": self.version,
                "degraded": result.degraded,
                "degradation_reason": result.degradation_reason,
            },
            evaluated_at=datetime.now(UTC),
        )

    def metadata(self) -> ModelMetadata:
        """Return model metadata: schema, training window, metrics."""
        return ModelMetadata(
            model_id=self.model_id,
            version=self.version,
            algorithm="isolation_forest" if self._iforest is not None else "zscore_fallback",
            training_end=self._training_end,
            training_rows=self._training_rows,
            feature_count=len(self._numeric_features),
            feature_names=list(self._numeric_features),
            target_column=self._id_column,
            metrics=dict(self._metrics),
            framework_version=self._framework_version(),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_features(
        self, features: pl.DataFrame, feature_columns: list[str] | None
    ) -> list[str]:
        """Select numeric feature columns (explicit list or all but the id)."""
        if feature_columns is not None:
            return [c for c in feature_columns if c in features.columns]
        return [
            c
            for c in features.columns
            if c != self._id_column and not self._is_date_like(c)
        ]

    @staticmethod
    def _is_date_like(column: str) -> bool:
        return column.lower() in {"date", "period", "period_end", "created_at"}

    def _numeric_frame(self, features: pl.DataFrame) -> pl.DataFrame:
        """Project to numeric features only (float at the model boundary)."""
        return features.select(
            [
                pl.col(col).cast(pl.Float64, strict=False).fill_null(0.0)
                for col in self._numeric_features
            ]
        )

    def _row_ids(self, features: pl.DataFrame) -> list[str]:
        """Row identifiers from the id column, falling back to row index."""
        if self._id_column in features.columns:
            raw = features.select(pl.col(self._id_column)).to_series().to_list()
            return [str(v) for v in raw]
        return [str(i) for i in range(features.height)]

    def _context_to_features(self, context: dict[str, Any], entity_id: str) -> pl.DataFrame:
        """Build a one-row feature frame from an entity context dict."""
        row = {
            self._id_column: entity_id,
            **{col: float(context.get(col, 0.0)) for col in self._numeric_features},
        }
        return pl.DataFrame([row])

    def _feature_stats(self, rows: list[list[float]]) -> dict[str, tuple[float, float]]:
        """Per-feature (mean, std) over the training rows (deterministic)."""
        stats: dict[str, tuple[float, float]] = {}
        n = len(rows)
        for j, col in enumerate(self._numeric_features):
            values = [row[j] for row in rows]
            mean = sum(values) / n if n else 0.0
            variance = sum((v - mean) ** 2 for v in values) / n if n else 0.0
            stats[col] = (mean, variance**0.5)
        return stats

    def _z_scores(self, row: list[float]) -> dict[str, float]:
        """Per-feature Z-scores for one row against training stats."""
        z: dict[str, float] = {}
        for j, col in enumerate(self._numeric_features):
            mean, std = self._stats.get(col, (0.0, 0.0))
            z[col] = 0.0 if std == 0.0 else (row[j] - mean) / std
        return z

    def _z_max(self, row: list[float]) -> float:
        """Maximum absolute Z-score across features for one row."""
        return max([abs(v) for v in self._z_scores(row).values()] or [0.0])

    def _z_row_score(self, row: list[float]) -> float:
        """Aggregate row anomaly score: max |Z| mapped into 0..1."""
        z_max = self._z_max(row)
        return z_max / (z_max + self._z_threshold)

    def _build_score(
        self,
        *,
        row_id: str,
        score: float,
        is_anomaly: bool,
        confidence: float,
        z_row: dict[str, float],
    ) -> AnomalyScore:
        return AnomalyScore(
            row_id=row_id,
            score=_clamp01(score),
            is_anomaly=is_anomaly,
            confidence=_clamp01(confidence),
            feature_contributions={col: abs(v) for col, v in z_row.items()},
        )

    def _framework_version(self) -> str:
        if self._sklearn_ensemble is None:
            return "scikit-learn not installed"
        return "scikit-learn installed"
