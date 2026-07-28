"""Tool for querying headcount data."""

from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.orm import Session

from shared.config import get_settings
from shared.models.database import HeadcountData
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


def query_headcount(
    tenant_id: str,
    period: str,
    department: str | None = None,
    engine: Engine | None = None,
) -> ToolResult:
    """Query headcount data for a tenant/period, optionally filtered by department.

    Parameters
    ----------
    tenant_id : str
        Entity / tenant identifier.
    period : str
        Fiscal period in ``YYYY-MM`` format (e.g. ``"2026-06"``).
    department : str, optional
        When provided, filter to a single department.
    engine : Engine, optional
        SQLAlchemy Engine.  Created from settings when *None*.

    Returns
    -------
    ToolResult
        Enriched result with headcount, compensation, hires, and departures.
    """
    engine = _get_engine(engine)

    with Session(engine) as session:
        stmt = select(HeadcountData).where(
            HeadcountData.entity_id == tenant_id,
            HeadcountData.period == period,
        )
        if department is not None:
            stmt = stmt.where(HeadcountData.department == department)

        rows = session.execute(stmt).scalars().all()
        data = [
            {
                "id": str(r.id),
                "entity_id": str(r.entity_id),
                "period": str(r.period),
                "department": str(r.department),
                "headcount": r.headcount,
                "total_compensation": float(r.total_compensation),
                "new_hires": r.new_hires,
                "departures": r.departures,
            }
            for r in rows
        ]
        row_count = len(data)

        # Aggregate totals
        total_headcount = sum(r["headcount"] for r in data)
        total_compensation = sum(r["total_compensation"] for r in data)
        total_new_hires = sum(r["new_hires"] for r in data)
        total_departures = sum(r["departures"] for r in data)

        # ---- coverage: depts found / total depts in headcount_data ----
        depts_found = (
            session.execute(
                select(func.count(func.distinct(HeadcountData.department))).where(
                    HeadcountData.entity_id == tenant_id,
                    HeadcountData.period == period,
                )
            ).scalar()
            or 0
        )
        total_depts = (
            session.execute(
                select(func.count(func.distinct(HeadcountData.department))).where(
                    HeadcountData.entity_id == tenant_id
                )
            ).scalar()
            or 1
        )
        coverage_pct = round(depts_found / total_depts, 4)

        # ---- freshness – no timestamp on headcount_data ----
        freshness_seconds: int | None = None

    quality_score = compute_quality_score(coverage_pct, row_count, freshness_seconds)
    degraded_mode = compute_degraded_mode(coverage_pct, row_count)
    query_fingerprint = compute_query_fingerprint(
        "query_headcount",
        tenant_id=tenant_id,
        period=period,
        department=department,
    )

    return ToolResult(
        data=data,
        row_count=row_count,
        coverage_pct=coverage_pct,
        quality_score=quality_score,
        freshness_seconds=freshness_seconds,
        schema_version="1.0",
        source_diversity=1,  # HeadcountData only
        source_type="operational_metric",
        retrieval_scope="factual",
        tenant_id=tenant_id,
        required_filters_present=True,
        insufficient_data=coverage_pct < 0.5 or row_count == 0,
        degraded_mode=degraded_mode,
        query_fingerprint=query_fingerprint,
    )
