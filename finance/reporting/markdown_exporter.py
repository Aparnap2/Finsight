"""Markdown exporter for BoardReport.

Renders a ``BoardReport`` as a formatted markdown document with
metadata header, ordered sections, KPI and variance tables, and
recommendation bullet lists.
"""

from __future__ import annotations

from decimal import Decimal

from finance.domain.board_report import BoardReport, ReportSection

SECTION_ORDER: list[ReportSection] = [
    ReportSection.EXECUTIVE_SUMMARY,
    ReportSection.FINANCIAL_HIGHLIGHTS,
    ReportSection.KPI_SUMMARY,
    ReportSection.VARIANCE_ANALYSIS,
    ReportSection.RISK_ASSESSMENT,
    ReportSection.RECOMMENDATIONS,
    ReportSection.APPENDIX,
]


class MarkdownExporter:
    """Exports a ``BoardReport`` as a formatted markdown string."""

    def export(self, report: BoardReport) -> str:
        """Render *report* to markdown."""
        lines: list[str] = []

        # ── Title ──────────────────────────────────────────────────────
        lines.append(f"# {report.title}")
        lines.append("")

        # ── Metadata block ─────────────────────────────────────────────
        date_str = report.generated_at.strftime("%Y-%m-%d %H:%M:%S %Z")
        lines.append(
            f"**Company:** {report.company_id} | "
            f"**Period:** {report.period_id} | "
            f"**Generated:** {date_str}"
        )
        if report.data_quality_score is not None:
            lines.append(f"**Quality Score:** {report.data_quality_score}")
        lines.append("---")
        lines.append("")

        # ── Sections ───────────────────────────────────────────────────
        if not report.sections:
            lines.append("No sections provided.")
        else:
            for section in SECTION_ORDER:
                content = report.sections.get(section)
                if content is None:
                    continue

                lines.append(content)
                lines.append("")

                # KPI summary table
                if section == ReportSection.KPI_SUMMARY and report.kpis:
                    lines.append("| KPI | Value | Status |")
                    lines.append("|-----|-------|--------|")
                    for kpi in report.kpis:
                        value_str = self._format_value(kpi.value)
                        status_str = kpi.status or ""
                        lines.append(f"| {kpi.kpi_name} | {value_str} | {status_str} |")
                    lines.append("")

                # Variance analysis table
                if section == ReportSection.VARIANCE_ANALYSIS and report.material_variances:
                    lines.append("| Account | Variance | % | Direction |")
                    lines.append("|---------|----------|---|-----------|")
                    for var in report.material_variances:
                        amount_str = self._format_amount(var.variance_amount)
                        pct_str = f"{var.variance_pct}%"
                        direction_str = (
                            var.direction.value
                            if hasattr(var.direction, "value")
                            else str(var.direction)
                        )
                        lines.append(
                            f"| {var.account_name} | {amount_str} | {pct_str} | {direction_str} |"
                        )
                    lines.append("")

                # Recommendation bullet list
                if section == ReportSection.RECOMMENDATIONS and report.recommendations:
                    for rec in report.recommendations:
                        lines.append(f"- {rec.title}")
                        if rec.description:
                            lines.append(f"  {rec.description}")
                    lines.append("")

        rendered = "\n".join(lines)
        return rendered

    # ── helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _format_value(value: Decimal) -> str:
        """Return the string representation of a Decimal value."""
        return str(value)

    @staticmethod
    def _format_amount(amount: Decimal) -> str:
        """Return a raw string representation of a monetary amount."""
        return str(amount)
