"""Predictive analytics — the ML interface contract (scaffolding only).

Defines the contract that the separate ML/Ops task must implement:
:class:`PredictiveProvider`. This module intentionally contains **no ML**
— deterministic code in ``finance/`` must not ship model weights or
training logic.

The pyramid this module anchors:
    descriptive (``descriptive.py``) → diagnostic (``diagnostic.py``) →
    predictive (this module, thin contract).

Degraded mode:
    :class:`NullPredictiveProvider` is the fallback provider used when no
    ML provider is configured — it returns the input feature frame
    unchanged ("no prediction"), so downstream consumers degrade
    gracefully instead of failing.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import polars as pl


@runtime_checkable
class PredictiveProvider(Protocol):
    """Contract implemented by ML prediction providers (separate ML task).

    A provider consumes a feature frame produced by the deterministic
    feature store (``finance/feature_store/``) and returns a frame of the
    same row count augmented with prediction columns (e.g.
    ``<metric>_forecast``, ``prediction_source``). Implementations must be
    pure functions of their input: same features → same prediction.
    """

    name: str
    """Stable provider identifier used for lineage and logging."""

    def predict(self, features: pl.DataFrame) -> pl.DataFrame:
        """Return the input frame augmented with prediction columns.

        Args:
            features: Feature frame from the deterministic feature store.

        Returns:
            A frame with the same row count as ``features``, augmented
            with prediction columns. Implementations must not mutate the
            input frame.
        """


class NullPredictiveProvider:
    """Degraded-mode provider: returns the input features unchanged.

    Implements :class:`PredictiveProvider` without making a prediction,
    so pipelines remain deterministic when no ML provider is configured.
    """

    name = "null"

    def predict(self, features: pl.DataFrame) -> pl.DataFrame:
        """Return a clone of ``features`` (no prediction added).

        Args:
            features: Feature frame from the deterministic feature store.

        Returns:
            A copy of ``features`` with identical rows.
        """
        return features.clone()


def default_provider() -> PredictiveProvider:
    """Return the default provider — the degraded-mode null provider.

    ML providers are registered by the separate mlops task; until one is
    configured, this function yields :class:`NullPredictiveProvider`.
    """
    return NullPredictiveProvider()


__all__ = [
    "NullPredictiveProvider",
    "PredictiveProvider",
    "default_provider",
]
