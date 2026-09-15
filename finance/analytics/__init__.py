"""Deterministic analytics — the prescriptive pyramid (Phase C).

Three modules mirroring the prescriptive analytics pyramid:

* :mod:`finance.analytics.descriptive` — descriptive stats over the
  finance tables (totals, period-over-period, ratios; Decimal-safe);
* :mod:`finance.analytics.diagnostic` — variance / driver decomposition
  that consumes the variance engine and produces evidence rows compatible
  with ``finance/evidence/models.py``;
* :mod:`finance.analytics.predictive` — the ML interface contract only
  (:class:`~finance.analytics.predictive.PredictiveProvider` and the
  degraded-mode :class:`~finance.analytics.predictive.NullPredictiveProvider`).
  No ML is implemented here — a separate mlops task consumes the contract.

All monetary values are ``decimal.Decimal`` (never ``float``).
"""

from __future__ import annotations

from finance.analytics.descriptive import (
    compute_period_over_period,
    compute_ratio,
    compute_totals,
)
from finance.analytics.diagnostic import DiagnosticEvidenceBuilder, variances_from_frame
from finance.analytics.predictive import (
    NullPredictiveProvider,
    PredictiveProvider,
    default_provider,
)

__all__ = [
    "DiagnosticEvidenceBuilder",
    "NullPredictiveProvider",
    "PredictiveProvider",
    "compute_period_over_period",
    "compute_ratio",
    "compute_totals",
    "default_provider",
    "variances_from_frame",
]
