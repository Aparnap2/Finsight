"""Finance Context Pack models.

The Context Pack is a structured, validated bundle sent to the LLM.
Never send raw spreadsheet data.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class FinanceContextPack(BaseModel):
    """Structured context bundle for LLM consumption.

    Contains everything the model needs to generate commentary:
    company info, KPIs, variances, evidence, and business context.
    Never contains raw spreadsheet rows.
    """

    company_id: str
    period_id: str
    company_name: str
    currency: str = "USD"
    kpis: list[dict[str, Any]] = []
    material_variances: list[dict[str, Any]] = []
    evidence_items: list[dict[str, Any]] = []
    budget_summary: dict[str, Any] = {}
    actual_summary: dict[str, Any] = {}
    forecast_summary: dict[str, Any] = {}
    risks: list[str] = []
    business_context: str = ""
