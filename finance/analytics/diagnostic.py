"""Diagnostic analytics — variance & driver decomposition.

Consumes the existing variance engine (``finance/variance_engine/``) to
assess actual-vs-budget variances and produces diagnostic evidence rows
compatible with ``finance/evidence/models.py`` (:class:`EvidenceItem`).

The pyramid this module anchors:
    descriptive (``descriptive.py``) → diagnostic (this module) →
    predictive (``predictive.py``, thin ML contract).

All monetary values remain ``decimal.Decimal``.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

import polars as pl

from finance.evidence.models import EvidenceItem
from finance.feature_store.base import assert_columns, assert_money_columns
from finance.variance_engine.materiality import MaterialityEngine
from shared.models.state import Variance

#: Source columns required by :func:`variances_from_frame`.
_REQUIRED_COLUMNS = ("account_id", "account_name", "department", "actual_amount", "budget_amount")

#: Sentinel used to neutralise division-by-zero denominators.
_ZERO = Decimal("0")


def variances_from_frame(df: pl.DataFrame) -> list[Variance]:
    """Convert a polars actual-vs-budget frame into ``Variance`` models.

    The frame must contain ``account_id``, ``account_name``,
    ``department``, ``actual_amount`` and ``budget_amount`` (Decimal).
    ``variance_amount`` (actual − budget) and ``variance_pct``
    ((actual − budget) ÷ |budget| × 100, ``0`` when the budget is ``0``)
    are computed when absent — matching the variance-engine percent
    convention.

    Args:
        df: Source frame (one row per account).

    Returns:
        List of :class:`shared.models.state.Variance` in row order.

    Raises:
        FeatureStoreError: When required columns are missing or the
            monetary columns are not Decimal.
    """
    assert_columns(df, _REQUIRED_COLUMNS)
    assert_money_columns(df, ("actual_amount", "budget_amount"))

    working = df
    if "variance_amount" not in working.columns:
        working = working.with_columns(
            (pl.col("actual_amount") - pl.col("budget_amount")).alias("variance_amount")
        )
    if "variance_pct" not in working.columns:
        working = working.with_columns(
            (
                (pl.col("actual_amount") - pl.col("budget_amount"))
                / pl.col("budget_amount").abs().replace(_ZERO, None)
                * Decimal("100")
            )
            .fill_null(_ZERO)
            .alias("variance_pct")
        )

    variances: list[Variance] = []
    for row in working.iter_rows(named=True):
        variances.append(
            Variance(
                account_id=str(row["account_id"]),
                account_name=str(row["account_name"]),
                department=str(row["department"]) if row.get("department") is not None else "",
                actual_amount=Decimal(str(row["actual_amount"])),
                budget_amount=Decimal(str(row["budget_amount"])),
                variance_amount=Decimal(str(row["variance_amount"])),
                variance_pct=Decimal(str(row["variance_pct"])),
            )
        )
    return variances


class DiagnosticEvidenceBuilder:
    """Build diagnostic evidence rows from the variance engine.

    Wraps :class:`MaterialityEngine` and emits one
    :class:`~finance.evidence.models.EvidenceItem` per variance,
    recording the materiality assessment and the deterministic
    assumptions / limitations of the analysis.
    """

    def __init__(self, engine: MaterialityEngine | None = None) -> None:
        """Build the builder over ``engine`` (defaults to a fresh engine)."""
        self._engine = engine if engine is not None else MaterialityEngine()

    def build_evidence(self, variances: Sequence[Variance]) -> list[EvidenceItem]:
        """Assess ``variances`` and return one evidence row per variance.

        Args:
            variances: Variances to diagnose (assessed for materiality
                in-place via the variance engine).

        Returns:
            List of :class:`~finance.evidence.models.EvidenceItem`, one
            per input variance, in input order.
        """
        evidence: list[EvidenceItem] = []
        for variance in variances:
            assessment = self._engine.assess(variance)
            evidence.append(
                EvidenceItem(
                    claim=(
                        f"Actual {variance.actual_amount} vs budget "
                        f"{variance.budget_amount} for account {variance.account_id} "
                        f"({variance.account_name}) in {variance.department or '<none>'}; "
                        f"variance {variance.variance_amount} ({variance.variance_pct}%)"
                    ),
                    source_type="variance_engine",
                    source_id=f"variance:{variance.account_id}",
                    source_value=variance.variance_amount,
                    supporting_metrics=[
                        "actual_amount",
                        "budget_amount",
                        "variance_pct",
                        f"is_material:{assessment.is_material}",
                        f"materiality_tier:{assessment.tier.value}",
                    ],
                    confidence="high" if assessment.is_material else "medium",
                    assumptions=[
                        "Budget amounts are treated as the plan baseline",
                        "Variance pct is (actual - budget) / |budget| * 100",
                    ],
                    limitations=[
                        "Materiality uses deterministic tier defaults; tenant overrides "
                        "are not applied",
                        "No root-cause analysis is attached to this evidence row",
                    ],
                )
            )
        return evidence

    def build_evidence_from_frame(self, df: pl.DataFrame) -> list[EvidenceItem]:
        """Convert ``df`` to variances, assess, and return evidence rows.

        Args:
            df: Frame compatible with :func:`variances_from_frame`.

        Returns:
            List of :class:`~finance.evidence.models.EvidenceItem`.

        Raises:
            FeatureStoreError: When required columns are missing or the
                monetary columns are not Decimal.
        """
        return self.build_evidence(variances_from_frame(df))


__all__ = [
    "DiagnosticEvidenceBuilder",
    "variances_from_frame",
]
