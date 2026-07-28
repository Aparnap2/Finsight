"""Board Report domain model.

A **Board Report** is the final rendered output of the FinSight pipeline —
a structured document containing financial highlights, KPI summaries,
variance analysis, risk assessment, and recommendations.  It is designed
for executive and board-level consumption.
"""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel

from finance.domain.evidence import EvidenceItem
from finance.domain.kpi import KPIValue
from finance.domain.recommendation import Recommendation
from finance.domain.variance import Variance


class ReportSection(StrEnum):
    """Standard sections of a board report."""

    EXECUTIVE_SUMMARY = "executive_summary"
    """High-level narrative overview of the period's financial performance."""

    FINANCIAL_HIGHLIGHTS = "financial_highlights"
    """Key financial numbers and headlines."""

    KPI_SUMMARY = "kpi_summary"
    """Dashboard of KPI values, trends, and status indicators."""

    VARIANCE_ANALYSIS = "variance_analysis"
    """Detailed variance commentary with root-cause analysis."""

    RISK_ASSESSMENT = "risk_assessment"
    """Assessment of financial and operational risks."""

    RECOMMENDATIONS = "recommendations"
    """Actionable recommendations with expected impact."""

    APPENDIX = "appendix"
    """Supporting data, methodology notes, and disclaimers."""


class BoardReport(BaseModel):
    """A structured financial report for board / executive consumption.

    The Board Report is the final delivery artefact of the FinSight pipeline.
    It consolidates financial analysis, KPIs, variances, evidence, and
    recommendations into a single structured document with markdown-content
    sections for each reporting area.
    """

    id: str
    """Unique report identifier."""

    company_id: str
    """The company this report covers."""

    period_id: str
    """The fiscal period this report covers."""

    title: str
    """Report title (e.g. ``\"Q1 2026 Board Report — CF001\"``)."""

    generated_at: datetime
    """Timestamp when the report was generated."""

    sections: dict[ReportSection, str]
    """Mapping of section type to rendered markdown content."""

    kpis: list[KPIValue] = []
    """KPI values included in this report."""

    material_variances: list[Variance] = []
    """Material variances highlighted in the report."""

    recommendations: list[Recommendation] = []
    """Actionable recommendations presented in the report."""

    evidence_summary: list[EvidenceItem] = []
    """Key evidence items supporting the analysis."""

    data_quality_score: Decimal | None = None
    """Overall data quality score (0.0 to 1.0) for this report's data."""

    is_draft: bool = True
    """Whether this report is a draft (``True``) or finalised (``False``)."""
