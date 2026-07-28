"""TDD tests for Phase 8 — Reporting.

BoardReport exporters (Markdown, JSON) and ReportBuilder.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel


def _make_report(**overrides) -> BaseModel:
    """Build a standard BoardReport for testing."""
    from finance.domain.board_report import BoardReport, ReportSection
    from finance.domain.evidence import EvidenceConfidence, EvidenceItem, EvidenceSource
    from finance.domain.kpi import KPIValue
    from finance.domain.recommendation import Recommendation, RecommendationType
    from finance.domain.variance import Variance

    default = BoardReport(
        id="br-2026-q1",
        company_id="CF001",
        period_id="2026-Q1",
        title="Q1 2026 Board Report — CF001",
        generated_at=datetime(2026, 4, 15, 10, 0, 0, tzinfo=UTC),
        sections={
            ReportSection.EXECUTIVE_SUMMARY: "# Executive Summary\n\nRevenue grew 12% YoY.",
            ReportSection.FINANCIAL_HIGHLIGHTS: "## Financial Highlights\n\n- Revenue: $10.5M",
            ReportSection.KPI_SUMMARY: "## KPIs\n\n- Gross Margin: 62%",
            ReportSection.VARIANCE_ANALYSIS: "## Variances\n\n- Revenue +$1.2M favorable",
            ReportSection.RISK_ASSESSMENT: "## Risks\n\n- Market volatility remains elevated.",
            ReportSection.RECOMMENDATIONS: "## Recommendations\n\n- Expand into new verticals.",
        },
        kpis=[
            KPIValue(
                kpi_id="kpi_gm",
                kpi_name="Gross Margin",
                value=Decimal("62.0"),
                period_id="2026-Q1",
                status="on_track",
            ),
        ],
        material_variances=[
            Variance(
                id="var_revenue",
                account_id="4010",
                account_name="Revenue",
                period_id="2026-Q1",
                actual_amount=Decimal("10500000"),
                budget_amount=Decimal("9300000"),
                variance_amount=Decimal("1200000"),
                variance_pct=Decimal("12.9"),
                direction="favorable",
                is_material=True,
                materiality_tier="tier1",
            ),
        ],
        recommendations=[
            Recommendation(
                id="rec_001",
                type=RecommendationType.REVENUE_OPTIMIZATION,
                title="Expand into new verticals",
                description="Target healthcare and fintech.",
                expected_impact=Decimal("500000"),
                confidence=EvidenceConfidence.HIGH,
                created_at=datetime(2026, 4, 15, 10, 0, 0, tzinfo=UTC),
                updated_at=datetime(2026, 4, 15, 10, 0, 0, tzinfo=UTC),
            ),
        ],
        evidence_summary=[
            EvidenceItem(
                id="ev_001",
                claim="Revenue variance evidence",
                source_type=EvidenceSource.VARIANCE,
                source_id="var_revenue",
                source_value=Decimal("10500000"),
                confidence=EvidenceConfidence.HIGH,
                created_at=datetime(2026, 4, 15, 10, 0, 0, tzinfo=UTC),
            ),
        ],
        data_quality_score=Decimal("0.92"),
        is_draft=False,
    )
    return default.model_copy(update=overrides)


# ── BoardReport Model ────────────────────────────────────────────────────────


class TestBoardReportModel:
    """BoardReport serialization and field validation."""

    def test_board_report_creation(self):
        """Create a valid BoardReport."""
        report = _make_report()
        assert report.id == "br-2026-q1"
        assert report.title == "Q1 2026 Board Report — CF001"
        assert report.is_draft is False
        assert report.data_quality_score == Decimal("0.92")
        assert len(report.sections) == 6
        assert len(report.kpis) == 1
        assert len(report.material_variances) == 1
        assert len(report.recommendations) == 1
        assert len(report.evidence_summary) == 1

    def test_report_section_enum_values(self):
        """ReportSection enum has expected values."""
        from finance.domain.board_report import ReportSection
        assert ReportSection.EXECUTIVE_SUMMARY.value == "executive_summary"
        assert ReportSection.FINANCIAL_HIGHLIGHTS.value == "financial_highlights"
        assert ReportSection.KPI_SUMMARY.value == "kpi_summary"
        assert ReportSection.VARIANCE_ANALYSIS.value == "variance_analysis"
        assert ReportSection.RISK_ASSESSMENT.value == "risk_assessment"
        assert ReportSection.RECOMMENDATIONS.value == "recommendations"
        assert ReportSection.APPENDIX.value == "appendix"

    def test_report_draft_default(self):
        """BoardReport defaults to draft."""
        from finance.domain.board_report import BoardReport
        report = BoardReport(
            id="test",
            company_id="CF001",
            period_id="2026-Q1",
            title="Test",
            generated_at=datetime.now(UTC),
            sections={},
        )
        assert report.is_draft is True


# ── JSON Exporter ────────────────────────────────────────────────────────────


class TestJSONExporter:
    """JSONExporter serializes BoardReport to JSON."""

    def test_export_to_json(self):
        """Export a BoardReport to a JSON string."""
        from finance.reporting.json_exporter import JSONExporter
        report = _make_report()
        exporter = JSONExporter()
        json_str = exporter.export(report)
        data = json.loads(json_str)
        assert data["id"] == "br-2026-q1"
        assert data["company_id"] == "CF001"
        assert data["is_draft"] is False
        assert len(data["sections"]) == 6
        assert len(data["kpis"]) == 1

    def test_export_includes_metadata(self):
        """JSON export includes generated_at as ISO string."""
        from finance.reporting.json_exporter import JSONExporter
        report = _make_report()
        exporter = JSONExporter()
        data = json.loads(exporter.export(report))
        assert "generated_at" in data
        assert data["generated_at"] == "2026-04-15T10:00:00+00:00"

    def test_export_with_indent(self):
        """JSONExporter supports indented output."""
        from finance.reporting.json_exporter import JSONExporter
        report = _make_report()
        exporter = JSONExporter(indent=2)
        json_str = exporter.export(report)
        # Indented JSON has newlines between fields
        assert "\n  " in json_str


# ── Markdown Exporter ────────────────────────────────────────────────────────


class TestMarkdownExporter:
    """MarkdownExporter renders BoardReport as formatted markdown."""

    def test_export_includes_title(self):
        """Markdown output includes the report title as H1."""
        from finance.reporting.markdown_exporter import MarkdownExporter
        report = _make_report()
        exporter = MarkdownExporter()
        md = exporter.export(report)
        assert "# Q1 2026 Board Report — CF001" in md

    def test_export_includes_metadata_block(self):
        """Markdown output includes metadata header."""
        from finance.reporting.markdown_exporter import MarkdownExporter
        report = _make_report()
        exporter = MarkdownExporter()
        md = exporter.export(report)
        assert "**Company:**" in md
        assert "CF001" in md
        assert "**Period:**" in md
        assert "2026-Q1" in md
        assert "**Generated:**" in md
        assert "2026-04-15" in md

    def test_export_includes_sections(self):
        """Each report section is rendered in order."""
        from finance.reporting.markdown_exporter import MarkdownExporter
        report = _make_report()
        exporter = MarkdownExporter()
        md = exporter.export(report)
        assert "# Executive Summary" in md
        assert "## Financial Highlights" in md
        assert "## KPIs" in md
        assert "## Variances" in md
        assert "## Risks" in md
        assert "## Recommendations" in md

    def test_export_includes_kpi_summary_table(self):
        """KPI values rendered as a markdown table."""
        from finance.reporting.markdown_exporter import MarkdownExporter
        report = _make_report()
        exporter = MarkdownExporter()
        md = exporter.export(report)
        assert "Gross Margin" in md
        assert "62.0" in md
        assert "|" in md  # table markers

    def test_export_includes_variance_summary_table(self):
        """Material variances rendered as a markdown table."""
        from finance.reporting.markdown_exporter import MarkdownExporter
        report = _make_report()
        exporter = MarkdownExporter()
        md = exporter.export(report)
        assert "Revenue" in md
        assert "12,000.00" in md or "1200000" in md
        assert "12.9%" in md

    def test_export_includes_recommendations(self):
        """Recommendations rendered as list items."""
        from finance.reporting.markdown_exporter import MarkdownExporter
        report = _make_report()
        exporter = MarkdownExporter()
        md = exporter.export(report)
        assert "Expand into new verticals" in md
        assert "healthcare and fintech" in md.lower() or "healthcare" in md.lower()

    def test_export_includes_quality_score(self):
        """Data quality score is included when present."""
        from finance.reporting.markdown_exporter import MarkdownExporter
        report = _make_report()
        exporter = MarkdownExporter()
        md = exporter.export(report)
        assert "0.92" in md
        assert "Quality" in md

    def test_export_empty_sections(self):
        """Exporter handles empty sections gracefully."""
        from finance.domain.board_report import BoardReport
        from finance.reporting.markdown_exporter import MarkdownExporter
        report = BoardReport(
            id="empty",
            company_id="TST",
            period_id="2026",
            title="Empty Report",
            generated_at=datetime.now(UTC),
            sections={},
        )
        exporter = MarkdownExporter()
        md = exporter.export(report)
        assert "Empty Report" in md
        assert "No sections" in md or len(md) > 0


# ── ReportBuilder ────────────────────────────────────────────────────────────


class TestReportBuilder:
    """ReportBuilder assembles a BoardReport from components."""

    def test_builder_creates_report(self):
        """ReportBuilder constructs a complete BoardReport."""
        from finance.domain.board_report import ReportSection
        from finance.reporting.builder import ReportBuilder

        builder = ReportBuilder(
            company_id="CF001",
            period_id="2026-Q1",
            title="Q1 2026 Board Report",
        )
        builder.add_section(ReportSection.EXECUTIVE_SUMMARY, "Good quarter.")
        builder.add_section(ReportSection.FINANCIAL_HIGHLIGHTS, "Revenue up.")
        builder.set_quality_score(Decimal("0.95"))

        report = builder.build()
        assert report.company_id == "CF001"
        assert report.period_id == "2026-Q1"
        assert report.title == "Q1 2026 Board Report"
        assert report.sections[ReportSection.EXECUTIVE_SUMMARY] == "Good quarter."
        assert report.data_quality_score == Decimal("0.95")
        assert report.is_draft is True

    def test_builder_can_finalize(self):
        """Builder can mark report as finalized (not draft)."""
        from finance.domain.board_report import ReportSection
        from finance.reporting.builder import ReportBuilder

        builder = ReportBuilder(company_id="C1", period_id="P1", title="Report")
        builder.add_section(ReportSection.EXECUTIVE_SUMMARY, "Summary")
        report = builder.finalize()
        assert report.is_draft is False

    def test_builder_adds_kpi(self):
        """Builder accepts KPIValue objects."""
        from decimal import Decimal

        from finance.domain.board_report import ReportSection
        from finance.domain.kpi import KPIValue
        from finance.reporting.builder import ReportBuilder

        kpi = KPIValue(
                kpi_id="k1",
                kpi_name="Revenue",
                value=Decimal("100"),
                period_id="P1",
                status="on_track",
            )

        builder = ReportBuilder(company_id="C1", period_id="P1", title="R")
        builder.add_section(ReportSection.EXECUTIVE_SUMMARY, "S")
        builder.add_kpi(kpi)

        report = builder.build()
        assert len(report.kpis) == 1
        assert report.kpis[0].kpi_name == "Revenue"

    def test_builder_adds_variance(self):
        """Builder accepts Variance objects."""
        from decimal import Decimal

        from finance.domain.board_report import ReportSection
        from finance.domain.variance import Variance
        from finance.reporting.builder import ReportBuilder

        var = Variance(id="v1", account_id="4010", account_name="Rev", period_id="P1",
                       actual_amount=Decimal("100"), budget_amount=Decimal("90"),
                       variance_amount=Decimal("10"), variance_pct=Decimal("11.1"),
                       direction="favorable", is_material=True)

        builder = ReportBuilder(company_id="C1", period_id="P1", title="R")
        builder.add_section(ReportSection.EXECUTIVE_SUMMARY, "S")
        builder.add_variance(var)

        report = builder.build()
        assert len(report.material_variances) == 1
