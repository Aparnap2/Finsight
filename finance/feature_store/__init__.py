"""Deterministic Feature Store — Phase C of the FinSight analytics layer.

A pure, deterministic analytics layer that transforms the finance domain
tables (``actuals``, ``budget_lines``, ``vendor_invoices``,
``headcount_data``, ``sales_pipeline``, ``forecast_lines``) into stable,
versioned feature groups.

* :data:`FEATURE_GROUPS` maps each group key to its builder module.
* :class:`~finance.feature_store.registry.FeatureRegistry` discovers and
  builds features by group.
* :func:`build_features` is the entry point: given a mapping of group →
  source ``polars.DataFrame``, it returns group → feature frame.

Guarantees:
    * No I/O, no LLM calls — pure compute on in-memory polars frames.
    * All monetary columns are ``decimal.Decimal`` (never ``float``).
    * Every group exposes a semantic ``FEATURE_VERSION`` and a stable
      ``FEATURE_NAMES`` column contract.
    * Output frames are validated (pandera structural schema + Decimal
      money-column checks) via ``finance.feature_store.base``.
"""

from __future__ import annotations

from finance.feature_store.registry import (
    FEATURE_GROUPS,
    FEATURE_REGISTRY,
    FeatureLookupError,
    FeatureRegistry,
    build_features,
)

__all__ = [
    "FEATURE_GROUPS",
    "FEATURE_REGISTRY",
    "FeatureLookupError",
    "FeatureRegistry",
    "build_features",
]
