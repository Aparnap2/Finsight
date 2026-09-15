"""Tests for the Board Report domain model.

Covers ``finance/domain/board_report.py``: the ``ReportSection`` enum and
the ``BoardReport`` aggregate. Key invariants: sections map each report
section to rendered markdown, reports default to draft, and the data
quality score is a Decimal in the 0.0-1.0 range (documented contract).
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from finance.domain.board_report import BoardReport, ReportSection


def _now() -> datetime:
    """A fixed timestamp for generated_at."""
    return datetime(2026, 7, 15, 12, 0, 0, tzinfo=UTC)


def _report(**overrides: object) -> BoardReport:
    """Build a default board report."""
    defaults: dict[str, object] = {
        "id": "BR-001",
        "company_id": "CF001",
        "period_id": "2026-Q2",
        "title": "Q2 2026 Board Report — CF001",
        "generated_at": _now(),
        "sections": {
            ReportSection.EXECUTIVE_SUMMARY: "# Executive Summary\nRevenue grew 8%.",
        },
    }
    defaults.update(overrides)
    return BoardReport(**defaults)


# =============================================================================
# ReportSection enum
# =============================================================================


class TestReportSection:
    """ReportSection enum values."""

    def test_executive_summary_value(self) -> None:
        """EXECUTIVE_SUMMARY serializes to 'executive_summary'."""
        assert ReportSection.EXECUTIVE_SUMMARY.value == "executive_summary"

    def test_financial_highlights_value(self) -> None:
        """FINANCIAL_HIGHLIGHTS serializes to 'financial_highlights'."""
        assert ReportSection.FINANCIAL_HIGHLIGHTS.value == "financial_highlights"

    def test_kpi_summary_value(self) -> None:
        """KPI_SUMMARY serializes to 'kpi_summary'."""
        assert ReportSection.KPI_SUMMARY.value == "kpi_summary"

    def test_variance_analysis_value(self) -> None:
        """VARIANCE_ANALYSIS serializes to 'variance_analysis'."""
        assert ReportSection.VARIANCE_ANALYSIS.value == "variance_analysis"

    def test_risk_assessment_value(self) -> None:
        """RISK_ASSESSMENT serializes to 'risk_assessment'."""
        assert ReportSection.RISK_ASSESSMENT.value == "risk_assessment"

    def test_recommendations_value(self) -> None:
        """RECOMMENDATIONS serializes to 'recommendations'."""
        assert ReportSection.RECOMMENDATIONS.value == "recommendations"

    def test_appendix_value(self) -> None:
        """APPENDIX serializes to 'appendix'."""
        assert ReportSection.APPENDIX.value == "appendix"


# =============================================================================
# BoardReport
# =============================================================================


class TestBoardReport:
    """Board report construction."""

    def test_constructs_with_required_fields(self) -> None:
        """A board report builds with required fields."""
        report = _report()
        assert report.id == "BR-001"
        assert report.company_id == "CF001"
        assert report.period_id == "2026-Q2"
        assert report.title == "Q2 2026 Board Report — CF001"

    def test_sections_stored(self) -> None:
        """Section content is preserved."""
        report = _report()
        assert report.sections[ReportSection.EXECUTIVE_SUMMARY].startswith(
            "# Executive Summary"
        )

    def test_is_draft_defaults_to_true(self) -> None:
        """Reports default to draft."""
        assert _report().is_draft is True

    def test_kpis_default_to_empty(self) -> None:
        """kpis defaults to an empty list."""
        assert _report().kpis == []

    def test_material_variances_default_to_empty(self) -> None:
        """material_variances defaults to an empty list."""
        assert _report().material_variances == []

    def test_recommendations_default_to_empty(self) -> None:
        """recommendations defaults to an empty list."""
        assert _report().recommendations == []

    def test_evidence_summary_default_to_empty(self) -> None:
        """evidence_summary defaults to an empty list."""
        assert _report().evidence_summary == []

    def test_data_quality_score_defaults_to_none(self) -> None:
        """data_quality_score defaults to None."""
        assert _report().data_quality_score is None

    def test_finalised_report_representable(self) -> None:
        """A finalised (non-draft) report is representable."""
        assert _report(is_draft=False).is_draft is False

    def test_data_quality_score_settable(self) -> None:
        """The data quality score is settable."""
        report = _report(data_quality_score=Decimal("0.95"))
        assert report.data_quality_score == Decimal("0.95")

    def test_multiple_sections_stored(self) -> None:
        """A report carries multiple sections."""
        report = _report(
            sections={
                ReportSection.EXECUTIVE_SUMMARY: "Summary",
                ReportSection.RISK_ASSESSMENT: "Risks",
            }
        )
        assert len(report.sections) == 2

    def test_sections_accept_string_keys(self) -> None:
        """Section keys are coerced from their string values."""
        report = _report(sections={"executive_summary": "Summary"})
        assert report.sections[ReportSection.EXECUTIVE_SUMMARY] == "Summary"

    def test_id_required(self) -> None:
        """A board report requires an id."""
        with pytest.raises(ValidationError):
            _report(id=None)

    def test_company_id_required(self) -> None:
        """A board report requires a company id."""
        with pytest.raises(ValidationError):
            _report(company_id=None)

    def test_period_id_required(self) -> None:
        """A board report requires a period id."""
        with pytest.raises(ValidationError):
            _report(period_id=None)

    def test_title_required(self) -> None:
        """A board report requires a title."""
        with pytest.raises(ValidationError):
            _report(title=None)

    def test_generated_at_required(self) -> None:
        """A board report requires a generated_at timestamp."""
        with pytest.raises(ValidationError):
            _report(generated_at=None)

    def test_sections_required(self) -> None:
        """A board report requires sections."""
        with pytest.raises(ValidationError):
            _report(sections=None)

    def test_round_trip_serialization(self) -> None:
        """A board report round-trips through model_dump."""
        report = _report(data_quality_score=Decimal("0.95"))
        dumped = report.model_dump()
        rebuilt = BoardReport(**dumped)
        assert rebuilt == report