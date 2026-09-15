"""Context Builder — assembles structured Finance Context Packs.

The Context Builder gathers all relevant data (KPIs, variances, evidence,
business context) and packages it into a validated FinanceContextPack
that is sent to the LLM for commentary generation.
"""
from __future__ import annotations

from finance.context.models import FinanceContextPack


class ContextBuilder:
    """Assembles Finance Context Packs from engine outputs."""

    def build_context(
        self,
        company_id: str,
        period_id: str,
    ) -> FinanceContextPack:
        return FinanceContextPack(
            company_id=company_id,
            period_id=period_id,
            company_name="",
            currency="USD",
            kpis=[],
            material_variances=[],
            evidence_items=[],
            budget_summary={},
            actual_summary={},
            forecast_summary={},
            risks=[],
            business_context="",
        )
