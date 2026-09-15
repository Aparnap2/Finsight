"""Machine-learning layer — inference registry, models, degraded mode.

Exposes the platform's three locked ML models (:class:`AnomalyDetectionModel`,
:class:`CashFlowForecastModel`, :class:`DuplicateDetectionModel`), the
:class:`InferenceRegistry` that gates them per tenant, and the shared
protocols from ``docs/09-platform/mlops.md`` (``PredictiveProvider``,
``RiskProvider``, ``ModelMetadata``, ``RiskEvaluation``).

Optional dependencies (``scikit-learn``, ``lightgbm``, ``shap``) are loaded
lazily through :func:`finance.ml.import_optional`; when they are missing the
models degrade to deterministic fallbacks (Z-score rule, trailing-mean
baseline, rule-based duplicate detection) instead of crashing.

Agents access models through the registry only — never through direct ML
imports. See ``docs/14-platform/implementation-plan.md`` Phase D.
"""

from __future__ import annotations

from finance.ml.anomaly import AnomalyDetectionModel, AnomalyResult, AnomalyScore
from finance.ml.cashflow import (
    CashFlowExplain,
    CashFlowForecast,
    CashFlowForecastModel,
    CashFlowPoint,
)
from finance.ml.duplicate import DuplicateDetectionModel, DuplicatePair, DuplicateResult
from finance.ml.fallback import NullPredictiveProvider, import_optional
from finance.ml.protocol import (
    ModelMetadata,
    PredictiveProvider,
    RegisteredProvider,
    RiskDecision,
    RiskEvaluation,
    RiskLevel,
    RiskProvider,
)
from finance.ml.registry import (
    InferenceRegistry,
    ModelNotRegisteredError,
)
from finance.ml.risk import RiskDecisionProvider, wrap_risk

__all__ = [
    "AnomalyDetectionModel",
    "AnomalyResult",
    "AnomalyScore",
    "CashFlowExplain",
    "CashFlowForecast",
    "CashFlowForecastModel",
    "CashFlowPoint",
    "DuplicateDetectionModel",
    "DuplicatePair",
    "DuplicateResult",
    "InferenceRegistry",
    "ModelMetadata",
    "ModelNotRegisteredError",
    "NullPredictiveProvider",
    "PredictiveProvider",
    "RegisteredProvider",
    "RiskDecision",
    "RiskDecisionProvider",
    "RiskEvaluation",
    "RiskLevel",
    "RiskProvider",
    "get_predictive_provider",
    "import_optional",
    "wrap_risk",
]

#: Process-wide inference registry — the single entry point for models.
REGISTRY = InferenceRegistry()


def get_predictive_provider(name: str) -> PredictiveProvider:
    """Return the registered predictive provider for a model name.

    Falls back to a :class:`NullPredictiveProvider` (degraded mode) when the
    model is not registered, so callers never crash on unknown names.
    """
    try:
        return REGISTRY.get_predictive(name)
    except ModelNotRegisteredError:
        return NullPredictiveProvider(name, reason=f"model {name!r} not registered")
