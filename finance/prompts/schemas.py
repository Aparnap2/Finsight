"""Pydantic v2 schemas for prompt input/output contracts.

All monetary values use ``MoneyDecimal``, which rejects ``float`` at the
Pydantic boundary — only ``decimal.Decimal``, ``int``, or ``str`` are accepted.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator


def _reject_float_money(v: object) -> object:
    """Reject float values for monetary fields."""
    if isinstance(v, float):
        raise ValueError(
            "Float values are not allowed for monetary fields. "
            "Use decimal.Decimal, int, or str instead."
        )
    return v


MoneyDecimal = Annotated[Decimal, BeforeValidator(_reject_float_money)]
"""Monetary value that rejects ``float`` at the Pydantic boundary."""


class VarianceAnalysisInput(BaseModel):
    """Input schema for variance analysis prompts.

    Carries the full context of a single account's variance for LLM
    explanation generation.
    """

    account_id: str
    account_name: str
    period_id: str
    actual_amount: MoneyDecimal
    budget_amount: MoneyDecimal
    variance_amount: MoneyDecimal
    variance_pct: MoneyDecimal
    direction: str
    is_material: bool
    materiality_tier: str | None = None


class VarianceAnalysisOutput(BaseModel):
    """Output schema for variance analysis prompts.

    The LLM-produced explanation, root causes, impact assessment,
    confidence level, and supporting evidence references.
    """

    explanation: str
    root_causes: list[str]
    impact: str
    confidence: str
    evidence_ids: list[str]


class ExecutiveSummaryInput(BaseModel):
    """Input schema for executive summary prompts.

    Aggregated company-level financial data for narrative generation.
    """

    company_name: str
    period_id: str
    total_revenue: MoneyDecimal
    total_expenses: MoneyDecimal
    net_income: MoneyDecimal
    kpi_count: int
    material_variance_count: int


class ExecutiveSummaryOutput(BaseModel):
    """Output schema for executive summary prompts.

    Structured narrative sections produced by the LLM.
    """

    executive_summary: str
    financial_highlights: str
    key_risks: str
    outlook: str


class BoardReportInput(BaseModel):
    """Input schema for board report prompts.

    Full context pack data for comprehensive board-level report generation.
    """

    company_name: str
    period_id: str
    executive_summary: str
    variance_highlights: list[Any]
    kpi_summary: dict[str, Any]
    recommendations: list[Any]
    risk_assessment: list[Any]
