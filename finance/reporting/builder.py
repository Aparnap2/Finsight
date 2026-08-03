"""Report builder — constructs a ``BoardReport`` from components.

Implements a fluent builder pattern so callers can chain
``.add_section(…)``, ``.add_kpi(…)``, ``.add_variance(…)``
calls before calling ``.build()`` or ``.finalize()``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from finance.domain.board_report import BoardReport, ReportSection
from finance.domain.kpi import KPIValue
from finance.domain.variance import Variance


class ReportBuilder:
    """Fluent builder that assembles a ``BoardReport`` piece by piece.

    Parameters
    ----------
    company_id : str
        The company this report covers.
    period_id : str
        The fiscal period this report covers.
    title : str
        Report title.
    """

    def __init__(
        self,
        company_id: str,
        period_id: str,
        title: str,
    ) -> None:
        self._company_id = company_id
        self._period_id = period_id
        self._title = title
        self._sections: dict[ReportSection, str] = {}
        self._kpis: list[KPIValue] = []
        self._variances: list[Variance] = []
        self._quality_score: Decimal | None = None

    # ── builder methods ────────────────────────────────────────────────

    def add_section(self, section: ReportSection, content: str) -> ReportBuilder:
        """Add a section with *content* to the report.

        Returns ``self`` for method chaining.
        """
        self._sections[section] = content
        return self

    def add_kpi(self, kpi: KPIValue) -> ReportBuilder:
        """Add a KPI value to the report.

        Returns ``self`` for method chaining.
        """
        self._kpis.append(kpi)
        return self

    def add_variance(self, variance: Variance) -> ReportBuilder:
        """Add a material variance to the report.

        Returns ``self`` for method chaining.
        """
        self._variances.append(variance)
        return self

    def set_quality_score(self, score: Decimal) -> ReportBuilder:
        """Set the overall data quality score for the report.

        Returns ``self`` for method chaining.
        """
        self._quality_score = score
        return self

    # ── terminal methods ───────────────────────────────────────────────

    def build(self) -> BoardReport:
        """Build and return a ``BoardReport`` in **draft** state.

        The report receives a generated identifier and the current
        UTC timestamp.
        """
        return self._assemble(is_draft=True)

    def finalize(self) -> BoardReport:
        """Build and return a **finalised** ``BoardReport``.

        Equivalent to ``.build()`` but with ``is_draft=False``.
        """
        return self._assemble(is_draft=False)

    # ── internal helpers ───────────────────────────────────────────────

    def _assemble(self, is_draft: bool) -> BoardReport:
        """Construct the ``BoardReport`` from accumulated state."""
        return BoardReport(
            id=f"br-{uuid.uuid4().hex[:12]}",
            company_id=self._company_id,
            period_id=self._period_id,
            title=self._title,
            generated_at=datetime.now(UTC),
            sections=self._sections,
            kpis=self._kpis,
            material_variances=self._variances,
            data_quality_score=self._quality_score,
            is_draft=is_draft,
        )
