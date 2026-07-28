"""Finance Context Pack models.

The Context Pack is a structured, validated bundle sent to the LLM.
Never send raw spreadsheet data.
"""
from __future__ import annotations
from decimal import Decimal
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
    kpis: list[dict] = []
    material_variances: list[dict] = []
    evidence_items: list[dict] = []
    budget_summary: dict = {}
    actual_summary: dict = {}
    forecast_summary: dict = {}
    risks: list[str] = []
    business_context: str = ""
