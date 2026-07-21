"""Tools for querying sales-pipeline data."""

from datetime import datetime

from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.models.database import SalesPipeline
from backend.tools.tool_result import (
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


def query_sales_pipeline(
    tenant_id: str,
    period: str,
    product: str | None = None,
    region: str | None = None,
    engine: Engine | None = None,
) -> ToolResult:
    """Query sales-pipeline deals for a tenant/period.

    Parameters
    ----------
    tenant_id : str
        Entity / tenant identifier.
    period : str
        Fiscal period in ``YYYY-MM`` format.
    product : str, optional
        Filter to a single product line.
    region : str, optional
        Filter to a single region.
    engine : Engine, optional
        SQLAlchemy Engine.  Created from settings when *None*.

    Returns
    -------
    ToolResult
        Enriched result with deals, pipeline value by stage, and coverage.
    """
    engine = _get_engine(engine)

    with Session(engine) as session:
        stmt = select(SalesPipeline).where(
            SalesPipeline.entity_id == tenant_id,
            SalesPipeline.period == period,
        )
        if product is not None:
            stmt = stmt.where(SalesPipeline.product == product)
        if region is not None:
            stmt = stmt.where(SalesPipeline.region == region)

        rows = session.execute(stmt).scalars().all()
        data = [
            {
                "id": str(r.id),
                "entity_id": str(r.entity_id),
                "period": str(r.period),
                "deal_name": str(r.deal_name),
                "stage": str(r.stage) if r.stage else None,
                "expected_close_date": (
                    r.expected_close_date.isoformat() if r.expected_close_date else None
                ),
                "amount": float(r.amount),
                "region": str(r.region) if r.region else None,
                "product": str(r.product) if r.product else None,
            }
            for r in rows
        ]
        row_count = len(data)

        # Aggregate: pipeline value by stage
        value_by_stage: dict[str, float] = {}
        for r in data:
            stage = r["stage"] or "Unknown"
            value_by_stage[stage] = value_by_stage.get(stage, 0) + r["amount"]

        total_pipeline_value = sum(r["amount"] for r in data)

        # ---- coverage: deals in period / total distinct deals across all periods ----
        deals_found = (
            session.execute(
                select(func.count(func.distinct(SalesPipeline.deal_name))).where(
                    SalesPipeline.entity_id == tenant_id,
                    SalesPipeline.period == period,
                )
            ).scalar()
            or 0
        )
        total_distinct_deals = (
            session.execute(
                select(func.count(func.distinct(SalesPipeline.deal_name))).where(
                    SalesPipeline.entity_id == tenant_id
                )
            ).scalar()
            or 1
        )
        coverage_pct = round(deals_found / total_distinct_deals, 4)

        # ---- freshness: latest expected_close_date ----
        latest_date = (
            session.execute(
                select(func.max(SalesPipeline.expected_close_date)).where(
                    SalesPipeline.entity_id == tenant_id,
                    SalesPipeline.period == period,
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
        "query_sales_pipeline",
        tenant_id=tenant_id,
        period=period,
        product=product,
        region=region,
    )

    return ToolResult(
        data=data,
        row_count=row_count,
        coverage_pct=coverage_pct,
        quality_score=quality_score,
        freshness_seconds=freshness_seconds,
        schema_version="1.0",
        source_diversity=1,  # SalesPipeline only
        source_type="operational_metric",
        retrieval_scope="factual",
        tenant_id=tenant_id,
        required_filters_present=True,
        insufficient_data=coverage_pct < 0.5 or row_count == 0,
        degraded_mode=degraded_mode,
        query_fingerprint=query_fingerprint,
    )
