"""Tools for querying vendor invoice / spend data."""

from datetime import datetime

from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.orm import Session

from shared.config import get_settings
from shared.models.database import VendorInvoice
from shared.utils.tools.tool_result import (
    ToolResult,
    compute_degraded_mode,
    compute_query_fingerprint,
    compute_quality_score,
)


def _get_engine(engine: Engine | None = None) -> Engine:
    if engine is not None:
        return engine
    return create_engine(get_settings().postgres_uri)


def _now() -> datetime:
    """Return current UTC datetime (patchable in tests)."""
    return datetime.utcnow()


def query_vendor_spend(
    tenant_id: str,
    period: str,
    vendor: str | None = None,
    category: str | None = None,
    engine: Engine | None = None,
) -> ToolResult:
    """Query vendor invoices for a tenant/period.

    Parameters
    ----------
    tenant_id : str
        Entity / tenant identifier.
    period : str
        Fiscal period in ``YYYY-MM`` format.
    vendor : str, optional
        Filter to a single vendor name.
    category : str, optional
        Filter to an invoice category.
    engine : Engine, optional
        SQLAlchemy Engine.  Created from settings when *None*.

    Returns
    -------
    ToolResult
        Enriched result with invoices, totals by vendor/category, and coverage.
    """
    engine = _get_engine(engine)

    with Session(engine) as session:
        stmt = select(VendorInvoice).where(
            VendorInvoice.entity_id == tenant_id,
            VendorInvoice.period == period,
        )
        if vendor is not None:
            stmt = stmt.where(VendorInvoice.vendor_name == vendor)
        if category is not None:
            stmt = stmt.where(VendorInvoice.category == category)

        rows = session.execute(stmt).scalars().all()
        data = [
            {
                "id": str(r.id),
                "entity_id": str(r.entity_id),
                "period": str(r.period),
                "vendor_name": str(r.vendor_name),
                "account_id": str(r.account_id),
                "amount": float(r.amount),
                "category": str(r.category) if r.category else None,
                "invoice_date": r.invoice_date.isoformat() if r.invoice_date else None,
            }
            for r in rows
        ]
        row_count = len(data)

        # Aggregate: totals by vendor and category
        totals_by_vendor: dict[str, float] = {}
        totals_by_category: dict[str, float] = {}
        for r in data:
            v = r["vendor_name"]
            totals_by_vendor[v] = totals_by_vendor.get(v, 0) + r["amount"]
            cat = r["category"] or "Uncategorized"
            totals_by_category[cat] = totals_by_category.get(cat, 0) + r["amount"]

        # ---- coverage: vendors invoiced / total vendors on record ----
        vendors_found = (
            session.execute(
                select(func.count(func.distinct(VendorInvoice.vendor_name))).where(
                    VendorInvoice.entity_id == tenant_id,
                    VendorInvoice.period == period,
                )
            ).scalar()
            or 0
        )
        total_vendors = (
            session.execute(
                select(func.count(func.distinct(VendorInvoice.vendor_name))).where(
                    VendorInvoice.entity_id == tenant_id
                )
            ).scalar()
            or 1
        )
        coverage_pct = round(vendors_found / total_vendors, 4)

        # ---- freshness: latest invoice_date ----
        latest_date = (
            session.execute(
                select(func.max(VendorInvoice.invoice_date)).where(
                    VendorInvoice.entity_id == tenant_id,
                    VendorInvoice.period == period,
                )
            ).scalar()
        )
        freshness_seconds: int | None = (
            int((_now() - latest_date).total_seconds())
            if latest_date
            else None
        )

    quality_score = compute_quality_score(coverage_pct, row_count, freshness_seconds)
    degraded_mode = compute_degraded_mode(coverage_pct, row_count)
    query_fingerprint = compute_query_fingerprint(
        "query_vendor_spend",
        tenant_id=tenant_id,
        period=period,
        vendor=vendor,
        category=category,
    )

    return ToolResult(
        data=data,
        row_count=row_count,
        coverage_pct=coverage_pct,
        quality_score=quality_score,
        freshness_seconds=freshness_seconds,
        schema_version="1.0",
        source_diversity=1,  # VendorInvoice only
        source_type="operational_metric",
        retrieval_scope="factual",
        tenant_id=tenant_id,
        required_filters_present=True,
        insufficient_data=coverage_pct < 0.5 or row_count == 0,
        degraded_mode=degraded_mode,
        query_fingerprint=query_fingerprint,
    )
