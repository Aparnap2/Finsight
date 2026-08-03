"""Degraded-mode fallbacks for the predictive layer.

Implements the platform's degraded-mode discipline
(``docs/09-platform/devsecops.md``): when an optional ML dependency is
missing, providers return deterministic fallbacks (baselines / neutral
evaluations) instead of crashing. The agent pipeline must keep running
without scikit-learn, lightgbm, or shap installed.

All optional ML dependencies are loaded through :func:`import_optional` so
``import finance.ml`` (and ``import finance``) succeeds in a bare
environment.

:class:`NullPredictiveProvider` here is the ML-side degraded fallback: it
conforms to the canonical ``PredictiveProvider`` interface shared with
``finance/analytics/predictive.py`` (``name`` + ``predict`` returning the
input frame unchanged) and additionally implements the ``RiskProvider``
shape (``evaluate``/``metadata``) so the registry can hand it to either
consumer.
"""

from __future__ import annotations

import importlib
import logging
from datetime import UTC, datetime
from typing import Any

import polars as pl

from finance.ml.protocol import ModelMetadata, RiskEvaluation

logger = logging.getLogger(__name__)


def import_optional(module_name: str) -> Any:
    """Import an optional dependency, returning ``None`` when unavailable.

    This is the single choke point for ML dependencies (``lightgbm``,
    ``sklearn.ensemble``, ``shap``). Tests monkeypatch
    ``importlib.import_module`` to exercise the failure path.
    """
    try:
        return importlib.import_module(module_name)
    except ImportError:
        logger.warning("optional dependency %r unavailable — degraded mode active", module_name)
        return None


class NullPredictiveProvider:
    """Degraded-mode provider: no ML available.

    Implements the canonical :class:`PredictiveProvider` shape
    (``predict`` returns the input frame unchanged, same row count — "no
    prediction") and the :class:`RiskProvider` shape (``evaluate`` returns
    a neutral, zero-confidence evaluation). Both are deterministic.

    This is the fallback returned by
    :class:`~finance.ml.registry.InferenceRegistry` when a model is not
    registered or a tenant's feature flags gate it off, and by
    :func:`finance.ml.get_predictive_provider` for unknown model names.
    """

    def __init__(self, model_id: str, reason: str = "model unavailable") -> None:
        self.name = model_id
        self.model_id = model_id
        self.version = "0.0.0"
        self._reason = reason

    def predict(self, features: pl.DataFrame) -> pl.DataFrame:
        """Return a clone of ``features`` — no prediction (degraded mode)."""
        return features.clone()

    def evaluate(self, context: dict[str, Any]) -> RiskEvaluation:
        """Return a neutral, zero-confidence risk evaluation (degraded)."""
        return RiskEvaluation(
            provider_id=self.model_id,
            entity_id=str(context.get("entity_id", "unknown")),
            score=0.0,
            confidence=0.0,
            evidence=[{"degraded": True, "reason": self._reason}],
            metadata={"degraded": True, "degradation_reason": self._reason},
            evaluated_at=datetime.now(UTC),
        )

    def metadata(self) -> ModelMetadata:
        """Return metadata identifying this as a degraded (null) provider."""
        return ModelMetadata(
            model_id=self.model_id,
            version=self.version,
            algorithm="null",
            framework_version="n/a",
        )
