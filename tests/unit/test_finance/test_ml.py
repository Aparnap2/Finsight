"""Tests for the ML layer (``finance/ml/``).

Covers: the three locked models (anomaly, cash-flow, duplicate) in both
degraded (no scikit-learn/lightgbm) and mocked full-ML paths, the inference
registry (registration, versioning, per-tenant gating, degraded fallback),
risk decision semantics, and package-level exports.

ML dependencies are never required in CI — the degraded paths are the
default here; the full-ML path is exercised by monkeypatching
``importlib.import_module`` (the ``import_optional`` choke point).
"""

# mypy: disable-error-code="untyped-decorator"

from __future__ import annotations

from decimal import Decimal
from typing import cast

import polars as pl
import pytest

from finance.ml import (
    AnomalyDetectionModel,
    CashFlowForecastModel,
    DuplicateDetectionModel,
    InferenceRegistry,
    ModelNotRegisteredError,
    NullPredictiveProvider,
    PredictiveProvider,
    RegisteredProvider,
    RiskLevel,
    RiskProvider,
    get_predictive_provider,
)
from finance.ml.fallback import import_optional
from finance.ml.risk import RiskDecisionProvider
from finplatform.config.tenant_schema import TenantConfig


def _acme_cfg(features: list[str] | None = None) -> TenantConfig:
    """Real acme-corp tenant config, optionally with overridden features.

    ``TenantConfig.load`` returns a frozen model, so feature overrides are
    applied via ``model_copy``.
    """
    cfg = TenantConfig.load("acme-corp")
    if features is None:
        return cfg
    return cfg.model_copy(update={"features": features})


def _as_registered(provider: object) -> RegisteredProvider:
    """Narrow a concrete model to the registry's storage contract.

    The three models expose richer typed ``predict`` outputs than the
    ``RegisteredProvider`` protocol (which follows the canonical
    ``PredictiveProvider`` DataFrame shape); they fully implement the
    agent-facing risk contract, so registration is safe.
    """
    return cast(RegisteredProvider, provider)


# =============================================================================
# Anomaly detection (degraded Z-score path)
# =============================================================================


class TestAnomalyDetection:
    """Anomaly detector in degraded mode (Z-score rule, no sklearn)."""

    def _train(self, model: AnomalyDetectionModel) -> AnomalyDetectionModel:
        df = pl.DataFrame(
            {
                "entity_id": ["e1", "e2", "e3", "e4", "e5"],
                "amount": [
                    Decimal("100"),
                    Decimal("102"),
                    Decimal("101"),
                    Decimal("99"),
                    Decimal("500"),
                ],
            }
        )
        return model.train(df, feature_columns=["amount"])

    def test_degraded_prediction(self) -> None:
        """Degraded predictions flag the obvious outlier and stay typed."""
        # Train on a tight cluster with some spread; the outlier is only
        # present at predict time (std must be non-zero for the Z-score rule).
        train = pl.DataFrame(
            {
                "entity_id": [f"e{i}" for i in range(1, 9)],
                "amount": [
                    Decimal("98"),
                    Decimal("102"),
                    Decimal("99"),
                    Decimal("101"),
                    Decimal("97"),
                    Decimal("103"),
                    Decimal("100"),
                    Decimal("100"),
                ],
            }
        )
        model = AnomalyDetectionModel().train(train, feature_columns=["amount"])
        assert not model.available
        result = model.predict(
            pl.DataFrame({"entity_id": ["e9"], "amount": [Decimal("500")]})
        )
        assert result.degraded is True
        assert result.scores
        assert result.scores[0].is_anomaly is True
        assert 0.0 <= result.scores[0].score <= 1.0

    def test_untrained_returns_degraded_result(self) -> None:
        """Predicting before training yields a degraded, non-raising result."""
        model = AnomalyDetectionModel()
        result = model.predict(pl.DataFrame({"entity_id": ["x"], "amount": [1.0]}))
        assert result.degraded is True
        assert result.scores == []

    def test_evaluate_uses_top_anomaly(self) -> None:
        """Risk evaluation surfaces the highest-scoring row."""
        model = self._train(AnomalyDetectionModel())
        ev = model.evaluate({"entity_id": "e9", "amount": 500.0})
        assert ev.provider_id == "payment_anomaly"
        assert ev.score > 0.0
        assert "model_version" in ev.metadata

    def test_implements_both_protocols(self) -> None:
        """The model is both a PredictiveProvider and a RiskProvider."""
        model = self._train(AnomalyDetectionModel())
        assert isinstance(model, PredictiveProvider)
        assert isinstance(model, RiskProvider)
        assert model.name == "payment_anomaly"
        assert model.model_id == "payment_anomaly"
        assert model.version == "1.0.0"


# =============================================================================
# Cash-flow forecast (degraded baseline path)
# =============================================================================


class TestCashFlowForecast:
    """Cash-flow forecaster in degraded mode (trailing-mean baseline)."""

    def _series(self) -> pl.DataFrame:
        return pl.DataFrame(
            {
                "date": [f"2026-01-{i:02d}" for i in range(1, 11)],
                "cash_position": [Decimal("100")] * 10,
            }
        )

    def test_baseline_forecast(self) -> None:
        """Degraded forecast uses the trailing mean and marks degraded."""
        model = CashFlowForecastModel().train(self._series(), horizon_days=3)
        assert not model.available
        result = model.predict(self._series(), horizon_days=3)
        assert result.degraded is True
        assert result.horizon_days == 3
        assert len(result.points) == 3
        assert all(p.amount == Decimal("100") for p in result.points)
        assert all(isinstance(p.amount, Decimal) for p in result.points)

    def test_total_and_min(self) -> None:
        """Aggregate helpers stay Decimal and handle empty points."""
        model = CashFlowForecastModel()
        result = model.predict(self._series(), horizon_days=4)
        assert result.total == Decimal("400")
        assert result.min_amount == Decimal("100")
        empty = model.predict(pl.DataFrame({"date": [], "cash_position": []}), horizon_days=2)
        assert empty.total == Decimal("0")
        assert empty.min_amount == Decimal("0")

    def test_missing_columns_raise(self) -> None:
        """A batch lacking required columns is rejected with ValueError."""
        model = CashFlowForecastModel()
        with pytest.raises(ValueError):
            model.train(pl.DataFrame({"date": ["2026-01-01"], "oops": [1.0]}))


# =============================================================================
# Duplicate detection (degraded rules path)
# =============================================================================


class TestDuplicateDetection:
    """Duplicate detector in degraded mode (rules only)."""

    def _reference(self) -> pl.DataFrame:
        return pl.DataFrame(
            {
                "entity_id": ["inv-1", "inv-2"],
                "vendor_name": ["Acme Supplies", "Acme Supplies"],
                "invoice_number": ["INV-100", "INV-200"],
                "amount": [Decimal("1500.00"), Decimal("1500.00")],
            }
        )

    def test_duplicate_within_batch(self) -> None:
        """Exact duplicate pairs are detected deterministically."""
        model = DuplicateDetectionModel().train(self._reference())
        result = model.predict(
            pl.DataFrame(
                {
                    "entity_id": ["inv-3"],
                    "vendor_name": ["Acme Supplies"],
                    "invoice_number": ["INV-100"],
                    "amount": [Decimal("1500.00")],
                }
            )
        )
        assert result.degraded is True
        assert len(result.pairs) >= 1
        dup = next(p for p in result.pairs if p.is_duplicate)
        assert "exact_text" in dup.matched_on
        assert dup.confidence >= 0.9

    def test_distinct_invoice_not_duplicate(self) -> None:
        """Different invoice numbers are not flagged as duplicates."""
        model = DuplicateDetectionModel().train(self._reference())
        result = model.predict(
            pl.DataFrame(
                {
                    "entity_id": ["inv-9"],
                    "vendor_name": ["Other Vendor"],
                    "invoice_number": ["INV-900"],
                    "amount": [Decimal("42.00")],
                }
            )
        )
        assert all(not p.is_duplicate for p in result.pairs)


# =============================================================================
# Full-ML path (mocked scikit-learn / lightgbm)
# =============================================================================


class _FakeIsolationForest:
    """Minimal sklearn-compatible IsolationForest stub."""

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    def fit(self, rows: list[list[float]]) -> None:
        """Accept any training matrix."""

    def decision_function(self, rows: list[list[float]]) -> list[float]:
        """Deep outlier → strongly negative score (high anomaly)."""
        return [10.0] * len(rows)

    def predict(self, rows: list[list[float]]) -> list[int]:
        return [1] * len(rows)


class TestFullMlPath:
    """Anomaly detector with a mocked scikit-learn backend."""

    def test_iforest_used_when_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With sklearn importable, the Isolation Forest path is used."""
        fake = type("FakeSklearnEnsemble", (), {"IsolationForest": _FakeIsolationForest})
        monkeypatch.setattr(
            "importlib.import_module",
            lambda name: fake if name == "sklearn.ensemble" else None,
        )
        assert import_optional("sklearn.ensemble") is not None
        model = AnomalyDetectionModel().train(
            pl.DataFrame(
                {
                    "entity_id": ["e1", "e2"],
                    "amount": [Decimal("100"), Decimal("500")],
                }
            ),
            feature_columns=["amount"],
        )
        assert model.available
        result = model.predict(pl.DataFrame({"entity_id": ["e9"], "amount": [Decimal("500")]}))
        assert result.degraded is False


# =============================================================================
# Inference registry
# =============================================================================


class TestInferenceRegistry:
    """Registry: registration, versioning, tenant gating, degraded fallback."""

    def _registry(self) -> InferenceRegistry:
        registry = InferenceRegistry()
        registry.register("payment_anomaly", _as_registered(AnomalyDetectionModel()))
        registry.register("cashflow", _as_registered(CashFlowForecastModel()))
        registry.register("duplicate_invoice", _as_registered(DuplicateDetectionModel()))
        return registry

    def test_registration_and_lookup(self) -> None:
        """Registered providers resolve as both risk and predictive."""
        registry = self._registry()
        assert registry.get("payment_anomaly") is cast(
            RiskProvider, registry.get_predictive("payment_anomaly")
        )
        assert registry.version("cashflow") == "1.0.0"
        assert registry.versions("cashflow") == ["1.0.0"]

    def test_unknown_model_raises(self) -> None:
        """Unknown names raise ModelNotRegisteredError."""
        registry = self._registry()
        with pytest.raises(ModelNotRegisteredError):
            registry.get("nope")

    def test_tenant_gating_disabled_feature(self) -> None:
        """A tenant without the ``ml`` flag gets a degraded fallback."""
        registry = self._registry()
        cfg = _acme_cfg(features=[])  # no "ml"
        assert not registry.is_available_for_tenant("payment_anomaly", cfg)
        provider = registry.get_for_tenant("payment_anomaly", cfg)
        assert isinstance(provider, NullPredictiveProvider)
        ev = provider.evaluate({"entity_id": "e1"})
        assert ev.metadata.get("degraded") is True

    def test_tenant_available_with_flag(self) -> None:
        """With ``ml`` enabled the real model is returned."""
        registry = self._registry()
        assert registry.is_available_for_tenant("payment_anomaly", _acme_cfg())
        assert not isinstance(
            registry.get_for_tenant("payment_anomaly", _acme_cfg()), NullPredictiveProvider
        )

    def test_cashflow_requires_forecasting_flag(self) -> None:
        """Cash flow additionally requires ``forecasting``."""
        registry = self._registry()
        cfg_no_forecast = _acme_cfg(features=["ml"])  # missing "forecasting"
        assert not registry.is_available_for_tenant("cashflow", cfg_no_forecast)
        assert registry.is_available_for_tenant("cashflow", _acme_cfg())

    def test_versions_history(self) -> None:
        """Re-registering a new version keeps the full history."""
        registry = InferenceRegistry()
        registry.register("m", _as_registered(AnomalyDetectionModel(version="1.0.0")))
        registry.register("m", _as_registered(AnomalyDetectionModel(version="1.1.0")))
        assert registry.versions("m") == ["1.0.0", "1.1.0"]
        assert registry.version("m") == "1.1.0"


# =============================================================================
# Risk decision layer
# =============================================================================


class TestRiskDecision:
    """OR-semantics decisions mirror the materiality engine."""

    def test_high_risk_threshold(self) -> None:
        """A high score yields an escalate decision."""
        registry = InferenceRegistry()
        registry.register("payment_anomaly", _as_registered(AnomalyDetectionModel()))
        wrapped = RiskDecisionProvider(registry.get("payment_anomaly"))
        ev = wrapped._provider.evaluate({"entity_id": "e1"})
        ev.score = 0.95
        decision = wrapped.decide(ev)
        assert decision.level == RiskLevel.HIGH
        assert decision.action == "escalate"

    def test_low_risk_auto_approve(self) -> None:
        """A low score with high confidence auto-approves."""
        registry = InferenceRegistry()
        registry.register("payment_anomaly", _as_registered(AnomalyDetectionModel()))
        wrapped = RiskDecisionProvider(registry.get("payment_anomaly"))
        ev = wrapped._provider.evaluate({"entity_id": "e1"})
        ev.score = 0.05
        ev.confidence = 0.95
        decision = wrapped.decide(ev)
        assert decision.level == RiskLevel.LOW
        assert decision.action == "auto_approve"


# =============================================================================
# Package exports
# =============================================================================


def test_package_exports() -> None:
    """The public ML surface re-exports the three models and protocols."""
    assert AnomalyDetectionModel.__name__ == "AnomalyDetectionModel"
    assert CashFlowForecastModel.__name__ == "CashFlowForecastModel"
    assert DuplicateDetectionModel.__name__ == "DuplicateDetectionModel"
    assert NullPredictiveProvider.__name__ == "NullPredictiveProvider"
    assert get_predictive_provider is not None


def test_get_predictive_provider_unknown_returns_null() -> None:
    """Unknown model names degrade to the null provider, not an exception."""
    provider = get_predictive_provider("does_not_exist")
    assert isinstance(provider, NullPredictiveProvider)
    assert provider.name == "does_not_exist"
