"""Feature flag registry (Layer 0).

Deterministic enablement logic over :class:`TenantConfig` feature flags,
including dependency resolution (e.g. ``rag`` requires ``ml``). No network
access and no external state.
"""

from __future__ import annotations

from finplatform.config.tenant_schema import TenantConfig

#: All features a tenant may enable.
KNOWN_FEATURES: frozenset[str] = frozenset({"forecasting", "recommendations", "rag", "ml"})

#: feature -> features it depends on (all must be enabled for the feature to be on)
DEPENDENCIES: dict[str, tuple[str, ...]] = {"rag": ("ml",)}


class FeatureRegistry:
    """Evaluate and validate tenant feature flags."""

    def is_enabled(self, cfg: TenantConfig, feature: str) -> bool:
        """Return whether ``feature`` is enabled, honoring dependencies.

        Unknown features are never enabled, and a feature whose dependencies
        are not satisfied (e.g. ``rag`` without ``ml``) is reported disabled.
        """
        if feature not in KNOWN_FEATURES:
            return False
        if not getattr(cfg.features, feature, False):
            return False
        return all(self.is_enabled(cfg, dep) for dep in DEPENDENCIES.get(feature, ()))

    def enabled_features(self, cfg: TenantConfig) -> list[str]:
        """Return the sorted list of enabled features, including implied dependencies."""
        return sorted(f for f in KNOWN_FEATURES if self.is_enabled(cfg, f))

    def validate(self, cfg: TenantConfig) -> list[str]:
        """Return warnings for features enabled without their dependencies.

        Each warning names the enabled feature and the missing dependency,
        e.g. ``rag`` enabled while ``ml`` is off.
        """
        warnings: list[str] = []
        for feature, deps in sorted(DEPENDENCIES.items()):
            if not getattr(cfg.features, feature, False):
                continue
            for dep in deps:
                if not getattr(cfg.features, dep, False):
                    warnings.append(
                        f"feature '{feature}' is enabled but requires '{dep}', which is "
                        f"disabled (tenants/{cfg.tenant_id}/tenant.yaml)"
                    )
        return warnings


#: Process-wide feature registry singleton.
FEATURE_REGISTRY = FeatureRegistry()
