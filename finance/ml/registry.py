"""Inference registry — model lifecycle, per-tenant availability, degraded mode.

Implements the registry from ``docs/09-platform/mlops.md`` with three
additions required by the platform:

- **Versioning** — every registration records its semantic version; the
  current version and full history are queryable per model name.
- **Per-tenant availability** — model access is gated by the tenant's
  feature flags (``finplatform/config/features.py``): all models require
  ``ml``; the cash-flow forecaster additionally requires ``forecasting``.
- **Degraded mode** — when a model is not registered, its optional ML
  dependency is missing, or the tenant's flags gate it off, callers receive
  a :class:`~finance.ml.fallback.NullPredictiveProvider` that returns
  deterministic fallbacks instead of crashing.

Agents access models through :meth:`InferenceRegistry.get` /
:meth:`InferenceRegistry.get_for_tenant` only — never through ML imports.
"""

from __future__ import annotations

from typing import Any

from finance.ml.fallback import NullPredictiveProvider
from finance.ml.protocol import (
    PredictiveProvider,
    RegisteredProvider,
    RiskEvaluation,
    RiskProvider,
)
from finplatform.config.features import FEATURE_REGISTRY
from finplatform.config.tenant_schema import TenantConfig

#: Feature flags each model requires to be available for a tenant.
#: All models require ``ml``; feature-specific models require their own flag.
MODEL_REQUIRED_FEATURES: dict[str, tuple[str, ...]] = {
    "cashflow": ("forecasting", "ml"),
    "payment_anomaly": ("ml",),
    "duplicate_invoice": ("ml",),
    "vendor_risk": ("ml",),
    "late_payment": ("ml",),
    "duplicate_vendor": ("ml",),
}


class ModelNotRegisteredError(KeyError):
    """Raised when a model name is not registered in the inference registry."""


class InferenceRegistry:
    """Registry of available providers with versioning and tenant gating.

    Usage::

        registry = InferenceRegistry()
        registry.register("payment_anomaly", AnomalyDetectionModel())
        registry.register("cashflow", CashFlowForecastModel())

        # Agent call — no knowledge of the provider type
        result = registry.get("payment_anomaly").evaluate({"entity_id": "T1"})
    """

    def __init__(
        self,
        *,
        required_features: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self._providers: dict[str, RegisteredProvider] = {}
        self._by_version: dict[tuple[str, str], RegisteredProvider] = {}
        self._version_history: dict[str, list[str]] = {}
        self._required_features: dict[str, tuple[str, ...]] = (
            dict(required_features) if required_features is not None else MODEL_REQUIRED_FEATURES
        )

    # ------------------------------------------------------------------
    # Registration & lookup
    # ------------------------------------------------------------------

    def register(self, name: str, provider: RegisteredProvider) -> None:
        """Register a provider under a name, recording its version."""
        self._providers[name] = provider
        self._by_version[(name, provider.version)] = provider
        history = self._version_history.setdefault(name, [])
        if provider.version not in history:
            history.append(provider.version)

    def get(self, name: str) -> RiskProvider:
        """Return a RiskProvider for ``name``.

        Registered providers implement the full :class:`RegisteredProvider`
        shape (predictive + risk), so they are returned as-is and already
        satisfy the agent-facing :class:`RiskProvider` contract.
        """
        provider = self._providers.get(name)
        if provider is None:
            raise ModelNotRegisteredError(f"Unknown provider: {name}")
        return provider

    def get_predictive(self, name: str) -> PredictiveProvider:
        """Return the raw predictive provider for ``name``."""
        provider = self._providers.get(name)
        if provider is None:
            raise ModelNotRegisteredError(f"Unknown provider: {name}")
        return provider

    def lookup(self, name: str, version: str | None = None) -> RiskProvider:
        """Look up a specific version; ``None`` returns the current model."""
        if version is None:
            return self.get(name)
        provider = self._by_version.get((name, version))
        if provider is None:
            raise ModelNotRegisteredError(f"Unknown version {version!r} of provider: {name}")
        return provider

    def version(self, name: str) -> str:
        """Current semantic version of a registered model."""
        provider = self._providers.get(name)
        if provider is None:
            raise ModelNotRegisteredError(f"Unknown provider: {name}")
        return provider.version

    def versions(self, name: str) -> list[str]:
        """Full version history (oldest first) for a registered model."""
        if name not in self._version_history:
            raise ModelNotRegisteredError(f"Unknown provider: {name}")
        return list(self._version_history[name])

    def list_providers(self) -> list[dict[str, str]]:
        """List registered providers as ``{name, model_id, version}`` dicts."""
        return [
            {"name": name, "model_id": p.model_id, "version": p.version}
            for name, p in self._providers.items()
        ]

    def evaluate_all(self, contexts: dict[str, dict[str, Any]]) -> dict[str, RiskEvaluation]:
        """Batch evaluate multiple providers (unknown names are skipped)."""
        return {
            name: self.get(name).evaluate(ctx)
            for name, ctx in contexts.items()
            if name in self._providers
        }

    # ------------------------------------------------------------------
    # Per-tenant availability & degraded mode
    # ------------------------------------------------------------------

    def required_features(self, name: str) -> tuple[str, ...]:
        """Feature flags a model requires; unknown models default to (``ml``,)."""
        return self._required_features.get(name, ("ml",))

    def is_available_for_tenant(self, name: str, cfg: TenantConfig) -> bool:
        """True when the model is registered and every required feature flag
        is enabled for the tenant (honoring feature dependencies)."""
        if name not in self._providers:
            return False
        return all(
            FEATURE_REGISTRY.is_enabled(cfg, feature)
            for feature in self.required_features(name)
        )

    def get_for_tenant(self, name: str, cfg: TenantConfig) -> RiskProvider:
        """Return the model for a tenant, or a degraded fallback when gated.

        The fallback is a :class:`NullPredictiveProvider` with an explicit
        reason, so the pipeline never crashes on feature-flag gating.
        """
        if self.is_available_for_tenant(name, cfg):
            return self.get(name)
        return NullPredictiveProvider(name, reason=self._unavailability_reason(name, cfg))

    def get_predictive_for_tenant(
        self, name: str, cfg: TenantConfig
    ) -> PredictiveProvider:
        """Predictive variant of :meth:`get_for_tenant` (degraded fallback)."""
        if self.is_available_for_tenant(name, cfg):
            return self.get_predictive(name)
        return NullPredictiveProvider(name, reason=self._unavailability_reason(name, cfg))

    def _unavailability_reason(self, name: str, cfg: TenantConfig) -> str:
        if name not in self._providers:
            return f"model {name!r} not registered"
        disabled = [
            feature
            for feature in self.required_features(name)
            if not FEATURE_REGISTRY.is_enabled(cfg, feature)
        ]
        return (
            f"tenant {cfg.tenant_id} has feature flag(s) disabled: {', '.join(disabled)}"
        )
