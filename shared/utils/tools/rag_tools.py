"""RAG retrieval tools — split into factual, precedent, and policy scopes.

Design:
- factual: financial facts, GL data, trial balances, headcount, vendor spend
  (source_type="financial_fact" or "operational_metric", retrieval_scope="factual")
- precedent: prior commentary, historical analyses, past decisions
  (source_type="precedent", retrieval_scope="precedent")
- policy: accounting policies, revenue recognition rules, expense policies
  (source_type="policy_doc", retrieval_scope="policy")

Precedent and policy may influence phrasing and hypothesis generation,
but must NEVER upgrade a claim to VERIFIED. This is enforced at the
ToolResult contract level via retrieval_scope and source_type.
"""

from datetime import datetime

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

from shared.config import get_settings
from shared.models.database import Actual, AgentRun, BudgetLine, CommentaryDraft
from shared.models.degraded_mode import DegradedMode
from shared.utils.tools.tool_result import (
    ToolResult,
    compute_degraded_mode,
    compute_quality_score,
    compute_query_fingerprint,
)


def _get_engine(engine: Engine | None = None) -> Engine:
    """Return the provided engine or create one from settings."""
    if engine is not None:
        return engine
    return create_engine(get_settings().postgres_uri)


def _now() -> datetime:
    """Return current UTC datetime (patchable in tests)."""
    return datetime.utcnow()


# ── Factual scope ──────────────────────────────────────────────────────────────


def query_factual(
    tenant_id: str,
    period: str,
    engine: Engine | None = None,
    table: str | None = None,
) -> ToolResult:
    """Query factual financial data (GL, TB, HC, vendor, pipeline).

    Parameters
    ----------
    tenant_id : str
        Entity / tenant identifier.
    period : str
        Fiscal period in ``YYYY-MM`` format.
    engine : Engine, optional
        SQLAlchemy Engine. Created from settings when *None*.
    table : str, optional
        Optional table name hint (reserved for future use).

    Returns
    -------
    ToolResult
        Factual financial data with ``retrieval_scope="factual"``.

    Notes
    -----
    This is the only scope that can produce VERIFIED assertions.
    Precedent and policy scopes must never upgrade claims to VERIFIED.
    """
    engine = _get_engine(engine)

    with Session(engine) as session:
        actuals = (
            session.query(Actual)
            .filter(Actual.entity_id == tenant_id, Actual.period == period)
            .all()
        )
        budgets = (
            session.query(BudgetLine)
            .filter(BudgetLine.entity_id == tenant_id, BudgetLine.period == period)
            .all()
        )

        budget_map = {b.account_id: b for b in budgets}

        data = []
        for a in actuals:
            b = budget_map.get(a.account_id)
            data.append({
                "account_id": a.account_id,
                "account_name": a.department or "",
                "actual_amount": float(a.amount),
                "budget_amount": float(b.amount) if b else 0.0,
                "department": a.department or "",
                "period": period,
            })

        row_count = len(data)
        coverage_pct = round(min(1.0, row_count / 20.0), 4) if row_count > 0 else 0.0
        quality_score = compute_quality_score(coverage_pct, row_count, freshness_seconds=None)
        degraded_mode = compute_degraded_mode(coverage_pct, row_count)
        query_fingerprint = compute_query_fingerprint(
            "query_factual",
            tenant_id=tenant_id,
            period=period,
            table=table,
        )

        return ToolResult(
            data=data,
            row_count=row_count,
            coverage_pct=coverage_pct,
            quality_score=quality_score,
            freshness_seconds=None,
            schema_version="1.0",
            source_diversity=2,  # Actual + BudgetLine tables
            source_type="financial_fact",
            retrieval_scope="factual",
            tenant_id=tenant_id,
            required_filters_present=True,
            insufficient_data=row_count == 0,
            degraded_mode=degraded_mode,
            query_fingerprint=query_fingerprint,
        )


# ── Precedent scope ────────────────────────────────────────────────────────────


def query_precedent(
    tenant_id: str,
    period: str,
    engine: Engine | None = None,
    prior_periods: int = 4,
) -> ToolResult:
    """Query prior commentary, historical analyses, and past decisions.

    Parameters
    ----------
    tenant_id : str
        Entity / tenant identifier.
    period : str
        Fiscal period in ``YYYY-MM`` format.
    engine : Engine, optional
        SQLAlchemy Engine. Created from settings when *None*.
    prior_periods : int
        Number of prior periods to look back (default 4).

    Returns
    -------
    ToolResult
        Prior commentary data with ``retrieval_scope="precedent"``.

    Notes
    -----
    Precedent may influence wording and hypothesis generation.
    Precedent must NEVER directly upgrade a claim to VERIFIED.
    """
    engine = _get_engine(engine)

    with Session(engine) as session:
        base_year = int(period.split("-")[0])
        base_month = int(period.split("-")[1])

        prior_commentaries = []
        for i in range(1, prior_periods + 1):
            m = base_month - i
            y = base_year
            while m <= 0:
                m += 12
                y -= 1
            prior_period = f"{y}-{m:02d}"

            # Find agent runs for this period
            run_ids_subq = (
                select(AgentRun.id)
                .where(AgentRun.entity_id == tenant_id, AgentRun.period == prior_period)
                .subquery()
            )
            drafts = (
                session.query(CommentaryDraft)
                .filter(CommentaryDraft.agent_run_id.in_(select(run_ids_subq)))
                .all()
            )
            for d in drafts:
                prior_commentaries.append({
                    "period": prior_period,
                    "content": d.content_json,
                    "version": d.version,
                    "status": str(d.status) if d.status else None,
                })

        row_count = len(prior_commentaries)
        coverage_pct = round(min(1.0, row_count / prior_periods), 4) if row_count > 0 else 0.0
        quality_score = compute_quality_score(coverage_pct, row_count)
        degraded_mode = (
            DegradedMode.PRECEDENT_ONLY_SUPPORT.value
            if row_count == 0
            else compute_degraded_mode(coverage_pct, row_count)
        )
        query_fingerprint = compute_query_fingerprint(
            "query_precedent",
            tenant_id=tenant_id,
            period=period,
        )

        return ToolResult(
            data=prior_commentaries,
            row_count=row_count,
            coverage_pct=coverage_pct,
            quality_score=quality_score,
            freshness_seconds=None,
            schema_version="1.0",
            source_diversity=1,
            source_type="precedent",
            retrieval_scope="precedent",
            tenant_id=tenant_id,
            required_filters_present=True,
            insufficient_data=row_count == 0,
            degraded_mode=degraded_mode,
            query_fingerprint=query_fingerprint,
        )


# ── Policy scope ───────────────────────────────────────────────────────────────


def query_policy(
    query_text: str,
    session: Session | None = None,
) -> ToolResult:
    """Query policy documents.

    Parameters
    ----------
    query_text : str
        Policy topic keyword or phrase.
    session : Session, optional
        SQLAlchemy Session (unused until policy ingestion is implemented).

    Returns
    -------
    ToolResult
        Policy document data with ``retrieval_scope="policy"``.

    Notes
    -----
    Policy may constrain actions and provide validation rules.
    Policy must NEVER be used as financial evidence.
    Policy ingestion is planned for T1.x scope.
    """
    query_fingerprint = compute_query_fingerprint("query_policy", query_text=query_text)

    return ToolResult(
        data=[{
            "query": query_text,
            "note": "Policy ingestion not yet implemented — returns empty",
        }],
        row_count=0,
        coverage_pct=0.0,
        quality_score=0.0,
        freshness_seconds=None,
        schema_version="1.0",
        source_diversity=0,
        source_type="policy_doc",
        retrieval_scope="policy",
        tenant_id="",
        required_filters_present=False,
        insufficient_data=True,
        degraded_mode=DegradedMode.STALE_SOURCE.value,
        query_fingerprint=query_fingerprint,
    )


# ── Backward-compatible aliases ────────────────────────────────────────────────

query_prior_commentary = query_precedent
query_policy_document = query_policy
