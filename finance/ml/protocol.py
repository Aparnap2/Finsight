"""Predictive modelling protocols (finance/ml boundary layer).

Two contracts live at this boundary:

- :class:`PredictiveProvider` — the predictive contract fed by the feature
  store. Its canonical definition lives in
  ``finance/analytics/predictive.py`` (the deterministic analytics layer);
  this module **re-exports** that definition so both layers share a single
  interface: ``name`` + ``predict(features: pl.DataFrame) -> pl.DataFrame``
  (input frame augmented with prediction columns, same row count).
- :class:`RiskProvider` — the agent-facing contract from
  ``docs/09-platform/mlops.md``. Agents call ``evaluate()`` without knowing
  whether the provider is a rule set, a trained model, or a hybrid.

Also defines the typed outputs shared across providers: :class:`RiskEvaluation`,
:class:`ModelMetadata`, and :class:`RiskDecision` (produced by
``finance/ml/risk.py``).

All monetary values carried in model outputs are ``decimal.Decimal`` — floats
exist only inside model internals and are converted back at the boundary.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

import polars as pl
from pydantic import BaseModel, Field

#: Canonical predictive interface — shared with finance/analytics (DataOps).
#: Re-exported so ``finance.ml.PredictiveProvider`` is the SAME class object
#: as ``finance.analytics.predictive.PredictiveProvider``.
from finance.analytics.predictive import PredictiveProvider

__all__ = [
    "ModelMetadata",
    "PredictiveProvider",
    "RegisteredProvider",
    "RiskDecision",
    "RiskEvaluation",
    "RiskLevel",
    "RiskProvider",
]


@runtime_checkable
class RiskProvider(Protocol):
    """Interface for risk evaluation — rules, ML, or hybrid.

    Agents call ``evaluate()`` without knowing the implementation. This is
    the protocol defined in ``docs/09-platform/mlops.md`` and mirrors the
    ``ToolResult`` pattern used across the evidence layers.
    """

    model_id: str
    """Unique model identifier — matches the model registry entry."""

    version: str
    """Semantic version of the model or rule set."""

    def evaluate(self, context: dict[str, Any]) -> RiskEvaluation:
        """Score a single entity (vendor, invoice, transaction).

        Args:
            context: Feature dictionary for the entity. Keys must match the
                feature schema registered in the model metadata.
        Returns:
            RiskEvaluation with score, evidence, and metadata.
        """
        ...

    def metadata(self) -> ModelMetadata:
        """Return model metadata: schema, training window, metrics."""
        ...


@runtime_checkable
class RegisteredProvider(Protocol):
    """A provider registrable in the inference registry.

    Combines the predictive contract (``name`` + ``predict``) and the
    agent-facing risk contract (``model_id`` + ``version`` + ``evaluate``
    + ``metadata``). Concrete models (anomaly, cash flow, duplicate) and
    the degraded fallback all implement this single shape, so the registry
    can hand a registered provider to either a predictive or a risk
    consumer without narrowing.
    """

    name: str
    """Stable provider identifier (predictive lineage)."""

    model_id: str
    """Unique model identifier (risk lineage)."""

    version: str
    """Semantic version of the model or rule set."""

    def predict(self, features: pl.DataFrame) -> pl.DataFrame:
        """Return ``features`` augmented with prediction columns."""
        ...

    def evaluate(self, context: dict[str, Any]) -> RiskEvaluation:
        """Score a single entity; see :class:`RiskProvider.evaluate`."""
        ...

    def metadata(self) -> ModelMetadata:
        """Return model metadata; see :class:`RiskProvider.metadata`."""
        ...


class RiskLevel(StrEnum):
    """Deterministic risk tiers produced by the decision layer.

    Mirrors the tiered sensitivity model used by ``MaterialityEngine``.
    """

    LOW = "low"
    REVIEW = "review"
    HIGH = "high"


class RiskEvaluation(BaseModel):
    """Typed output of a RiskProvider evaluation.

    Mirrors the ``Assertion`` model structure — every ML judgment carries
    evidence and confidence, just like deterministic assertions. ``score``
    and ``confidence`` are risk/probability values (0.0–1.0), not monetary
    amounts, so floats are appropriate here.
    """

    provider_id: str
    entity_id: str
    score: float  # 0.0 (low risk) to 1.0 (high risk)
    confidence: float  # model confidence in this prediction
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    evaluated_at: datetime


class RiskDecision(BaseModel):
    """Business decision derived from a RiskEvaluation.

    Uses OR semantics compatible with ``MaterialityEngine``
    (``combined_rule="any"``): an entity escalates when its score exceeds a
    threshold OR its score exceeds a lower threshold with sufficient
    confidence. Uncertainty (low confidence) routes to human review.
    """

    provider_id: str
    entity_id: str
    level: RiskLevel
    action: str  # "auto_approve" | "route_for_review" | "escalate"
    score: float
    confidence: float
    reasons: list[str] = Field(default_factory=list)
    evaluated_at: datetime


class ModelMetadata(BaseModel):
    """Metadata for a registered model version.

    Follows the structured-metadata pattern of ``DatasetMetadata`` in
    ``finance/evaluation/`` per ``docs/09-platform/mlops.md``.
    """

    model_id: str
    version: str  # semver
    algorithm: str  # "lightgbm", "isolation_forest", "hybrid_rules", ...
    training_start: datetime | None = None
    training_end: datetime | None = None
    training_rows: int = 0
    feature_count: int = 0
    feature_names: list[str] = Field(default_factory=list)
    target_column: str = ""
    metrics: dict[str, float] = Field(default_factory=dict)
    artifact_path: str = ""
    framework_version: str = ""  # e.g. "lightgbm==4.x" or "not-installed"
    deployed_at: datetime | None = None
    retired_at: datetime | None = None
