"""Tests for deterministic analytics (``finance/analytics/``).

Covers: descriptive totals / period-over-period / ratios on tiny
hand-computed inputs, diagnostic evidence rows compatible with
``finance/evidence/models.py``, and the predictive provider contract
(null provider returns the input unchanged).
"""

# mypy: disable-error-code="untyped-decorator"

from __future__ import annotations

from decimal import Decimal

import polars as pl
import pytest

from finance.analytics import (
    DiagnosticEvidenceBuilder,
    NullPredictiveProvider,
    PredictiveProvider,
    compute_period_over_period,
    compute_ratio,
    compute_totals,
    default_provider,
    variances_from_frame,
)
from finance.evidence.models import EvidenceItem
from finance.feature_store.base import FeatureStoreError
from shared.models.state import Variance

# =============================================================================
# 1. Descriptive analytics
# =============================================================================


class TestDescriptiveTotals:
    """Grouped totals on a tiny hand-computed frame."""

    def test_totals_by_entity(self) -> None:
        """Sums per entity are exact and stay Decimal."""
        df = pl.DataFrame(
            {
                "entity_id": ["e1", "e1", "e2"],
                "amount": [Decimal("100.00"), Decimal("200.00"), Decimal("50.00")],
                "amount2": [Decimal("10.00"), Decimal("20.00"), Decimal("5.00")],
            }
        )
        out = compute_totals(df, ["entity_id"], ["amount", "amount2"])
        rows = {r["entity_id"]: r for r in out.rows(named=True)}
        assert rows["e1"]["amount_total"] == Decimal("300.00")
        assert rows["e1"]["amount2_total"] == Decimal("30.00")
        assert rows["e2"]["amount_total"] == Decimal("50.00")
        assert rows["e2"]["amount2_total"] == Decimal("5.00")
        assert isinstance(rows["e1"]["amount_total"], Decimal)

    def test_totals_rejects_float_money(self) -> None:
        """A float monetary column raises FeatureStoreError."""
        df = pl.DataFrame({"entity_id": ["e1"], "amount": [1.5]})
        with pytest.raises(FeatureStoreError):
            compute_totals(df, ["entity_id"], ["amount"])


class TestDescriptivePeriodOverPeriod:
    """Period-over-period deltas and growth on a tiny frame."""

    def test_pop_delta_and_growth(self) -> None:
        """Prior/delta/growth are exact; first period growth is null."""
        df = pl.DataFrame(
            {
                "entity_id": ["e1", "e1"],
                "period": ["2026-01", "2026-02"],
                "amount": [Decimal("100.00"), Decimal("150.00")],
            }
        )
        out = compute_period_over_period(df, "entity_id", "period", ["amount"])
        rows = out.rows(named=True)
        first, second = rows
        assert first["amount_prior"] is None
        assert first["amount_delta"] is None
        assert first["amount_growth"] is None
        assert second["amount_prior"] == Decimal("100.00")
        assert second["amount_delta"] == Decimal("50.00")
        assert second["amount_growth"] == Decimal("0.50")

    def test_pop_zero_prior_guard(self) -> None:
        """Growth is 0 when the prior value is 0 (degenerate, documented)."""
        df = pl.DataFrame(
            {
                "entity_id": ["e2", "e2"],
                "period": ["2026-01", "2026-02"],
                "amount": [Decimal("0.00"), Decimal("10.00")],
            }
        )
        out = compute_period_over_period(df, "entity_id", "period", ["amount"])
        second = out.rows(named=True)[1]
        assert second["amount_delta"] == Decimal("10.00")
        assert second["amount_growth"] == Decimal("0.00")


class TestDescriptiveRatio:
    """Decimal ratios with a zero-denominator guard."""

    def test_ratio(self) -> None:
        """num ÷ den is a Decimal; zero denominator yields 0."""
        df = pl.DataFrame(
            {
                "num": [Decimal("100.00"), Decimal("10.00")],
                "den": [Decimal("50.00"), Decimal("0.00")],
            }
        )
        out = compute_ratio(df, "num", "den", out_col="ratio")
        values = out["ratio"].to_list()
        assert values == [Decimal("2.00"), Decimal("0.00")]
        assert all(isinstance(v, Decimal) for v in values)


# =============================================================================
# 2. Diagnostic analytics
# =============================================================================


class TestVariancesFromFrame:
    """Frame → Variance model conversion."""

    def test_variances_computed(self) -> None:
        """variance_amount and variance_pct are computed Decimal-safe."""
        df = pl.DataFrame(
            {
                "account_id": ["4010", "6010"],
                "account_name": ["Consulting Revenue", "Office Supplies"],
                "department": ["Sales", "G&A"],
                "actual_amount": [Decimal("600000.00"), Decimal("260000.00")],
                "budget_amount": [Decimal("500000.00"), Decimal("250000.00")],
            }
        )
        variances = variances_from_frame(df)
        assert len(variances) == 2
        assert variances[0].account_id == "4010"
        assert variances[0].variance_amount == Decimal("100000.00")
        assert variances[0].variance_pct == Decimal("20.00")
        assert variances[1].variance_amount == Decimal("10000.00")
        assert variances[1].variance_pct == Decimal("4.00")

    def test_zero_budget_pct_guard(self) -> None:
        """A zero budget yields variance_pct 0, not an error."""
        df = pl.DataFrame(
            {
                "account_id": ["7010"],
                "account_name": ["Other Income"],
                "department": ["Corporate"],
                "actual_amount": [Decimal("50000.00")],
                "budget_amount": [Decimal("0.00")],
            }
        )
        variances = variances_from_frame(df)
        assert variances[0].variance_pct == Decimal("0.00")

    def test_float_money_rejected(self) -> None:
        """A float monetary column raises FeatureStoreError."""
        df = pl.DataFrame(
            {
                "account_id": ["4010"],
                "account_name": ["Revenue"],
                "department": ["Sales"],
                "actual_amount": [1.5],
                "budget_amount": [Decimal("1.00")],
            }
        )
        with pytest.raises(FeatureStoreError):
            variances_from_frame(df)


class TestDiagnosticEvidence:
    """Evidence rows are compatible with finance/evidence/models.py."""

    @pytest.fixture
    def variances(self) -> list[Variance]:
        """One material (CRITICAL revenue) and one non-material variance."""
        return variances_from_frame(
            pl.DataFrame(
                {
                    "account_id": ["4010", "6010"],
                    "account_name": ["Consulting Revenue", "Office Supplies"],
                    "department": ["Sales", "G&A"],
                    "actual_amount": [Decimal("600000.00"), Decimal("260000.00")],
                    "budget_amount": [Decimal("500000.00"), Decimal("250000.00")],
                }
            )
        )

    def test_evidence_rows_are_evidence_items(self, variances: list[Variance]) -> None:
        """Every diagnostic row is a finance.evidence.models.EvidenceItem."""
        evidence = DiagnosticEvidenceBuilder().build_evidence(variances)
        assert len(evidence) == 2
        for item in evidence:
            assert isinstance(item, EvidenceItem)
            assert item.source_type == "variance_engine"
            assert isinstance(item.source_value, Decimal)
            assert item.assumptions
            assert item.limitations

    def test_material_variance_flagged_high_confidence(self, variances: list[Variance]) -> None:
        """A material variance carries high confidence and the tier metric."""
        evidence = DiagnosticEvidenceBuilder().build_evidence(variances)
        revenue = evidence[0]
        assert revenue.source_id == "variance:4010"
        assert revenue.source_value == Decimal("100000.00")
        assert "is_material:True" in revenue.supporting_metrics
        assert "materiality_tier:critical" in revenue.supporting_metrics
        assert revenue.confidence == "high"
        assert "4010" in revenue.claim

    def test_non_material_variance_medium_confidence(self, variances: list[Variance]) -> None:
        """A non-material variance carries medium confidence."""
        evidence = DiagnosticEvidenceBuilder().build_evidence(variances)
        supplies = evidence[1]
        assert "is_material:False" in supplies.supporting_metrics
        assert supplies.confidence == "medium"

    def test_build_evidence_from_frame(self) -> None:
        """The frame-based entry point composes conversion + assessment."""
        df = pl.DataFrame(
            {
                "account_id": ["4010"],
                "account_name": ["Consulting Revenue"],
                "department": ["Sales"],
                "actual_amount": [Decimal("600000.00")],
                "budget_amount": [Decimal("500000.00")],
            }
        )
        evidence = DiagnosticEvidenceBuilder().build_evidence_from_frame(df)
        assert len(evidence) == 1
        assert evidence[0].source_id == "variance:4010"


# =============================================================================
# 3. Predictive analytics contract
# =============================================================================


class TestPredictiveProvider:
    """The predictive provider contract and degraded-mode fallback."""

    def test_null_provider_returns_input_unchanged(self) -> None:
        """Null provider returns an equal frame with identical columns."""
        df = pl.DataFrame(
            {"entity_id": ["e1"], "vendor_count": [2], "vendor_total_amount": [Decimal("300.00")]}
        )
        provider = NullPredictiveProvider()
        out = provider.predict(df)
        assert out.columns == df.columns
        assert out.height == df.height
        assert out.equals(df)
        assert out is not df  # cloned, not the same object

    def test_null_provider_satisfies_protocol(self) -> None:
        """Null provider is recognized as a PredictiveProvider."""
        provider = NullPredictiveProvider()
        assert isinstance(provider, PredictiveProvider)
        assert provider.name == "null"

    def test_default_provider_is_null(self) -> None:
        """The default provider is the degraded-mode null provider."""
        provider = default_provider()
        assert isinstance(provider, NullPredictiveProvider)
