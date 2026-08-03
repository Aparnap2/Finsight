"""Tools for querying general-ledger data (actuals and trial balance)."""

from datetime import datetime

from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.orm import Session

from shared.config import get_settings
from shared.models.database import Actual, GLAccount, TrialBalance
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


def query_gl_detail(
    tenant_id: str,
    period: str,
    account_id: str | None = None,
    engine: Engine | None = None,
) -> ToolResult:
    """Query actuals joined with GL accounts for a tenant/period.

    Parameters
    ----------
    tenant_id : str
        The entity / tenant identifier (e.g. 'CF001').
    period : str
        Fiscal period in ``YYYY-MM`` format.
    account_id : str, optional
        When provided, filter to a single GL account.
    engine : Engine, optional
        SQLAlchemy Engine.  Created from settings when *None*.

    Returns
    -------
    ToolResult
        Enriched result with row count, coverage, and freshness metadata.
    """
    engine = _get_engine(engine)

    with Session(engine) as session:
        # ---- fetch detail rows ----
        stmt = (
            select(
                Actual.id,
                Actual.entity_id,
                Actual.period,
                Actual.account_id,
                GLAccount.account_number,
                GLAccount.account_name,
                GLAccount.account_type,
                GLAccount.department,
                Actual.amount,
            )
            .join(GLAccount, Actual.account_id == GLAccount.id)
            .where(Actual.entity_id == tenant_id, Actual.period == period)
        )
        if account_id is not None:
            stmt = stmt.where(Actual.account_id == account_id)

        rows = session.execute(stmt).all()
        data = [
            {
                "id": str(r.id),
                "entity_id": str(r.entity_id),
                "period": str(r.period),
                "account_id": str(r.account_id),
                "account_number": str(r.account_number),
                "account_name": str(r.account_name),
                "account_type": str(r.account_type),
                "department": str(r.department) if r.department else None,
                "amount": float(r.amount),
            }
            for r in rows
        ]

        row_count = len(data)

        # ---- coverage: distinct accounts in actuals / total active accounts ----
        actual_acct_count = (
            session.execute(
                select(func.count(func.distinct(Actual.account_id))).where(
                    Actual.entity_id == tenant_id, Actual.period == period
                )
            ).scalar()
            or 0
        )
        total_active_accts = (
            session.execute(
                select(func.count(GLAccount.id)).where(GLAccount.entity_id == tenant_id)
            ).scalar()
            or 1  # avoid division by zero
        )
        coverage_pct = round(actual_acct_count / total_active_accts, 4)

        # ---- freshness – no timestamp column on actuals ----
        freshness_seconds: int | None = None

    quality_score = compute_quality_score(coverage_pct, row_count, freshness_seconds)
    degraded_mode = compute_degraded_mode(coverage_pct, row_count)
    query_fingerprint = compute_query_fingerprint(
        "query_gl_detail",
        tenant_id=tenant_id,
        period=period,
        account_id=account_id,
    )

    return ToolResult(
        data=data,
        row_count=row_count,
        coverage_pct=coverage_pct,
        quality_score=quality_score,
        freshness_seconds=freshness_seconds,
        schema_version="1.0",
        source_diversity=2,  # Actual + GLAccount
        source_type="financial_fact",
        retrieval_scope="factual",
        tenant_id=tenant_id,
        required_filters_present=True,
        insufficient_data=coverage_pct < 0.5 or row_count == 0,
        degraded_mode=degraded_mode,
        query_fingerprint=query_fingerprint,
    )


def query_trial_balance(
    tenant_id: str,
    period: str,
    engine: Engine | None = None,
) -> ToolResult:
    """Query trial-balance records for a tenant/period.

    Parameters
    ----------
    tenant_id : str
        The entity / tenant identifier.
    period : str
        Fiscal period in ``YYYY-MM`` format.
    engine : Engine, optional
        SQLAlchemy Engine.  Created from settings when *None*.

    Returns
    -------
    ToolResult
        Enriched result with summed debits/credits, account count, and
        coverage metadata.
    """
    engine = _get_engine(engine)

    with Session(engine) as session:
        stmt = (
            select(
                TrialBalance.id,
                TrialBalance.entity_id,
                TrialBalance.period,
                TrialBalance.account_id,
                GLAccount.account_number,
                GLAccount.account_name,
                GLAccount.account_type,
                TrialBalance.debit,
                TrialBalance.credit,
                TrialBalance.balance,
            )
            .join(GLAccount, TrialBalance.account_id == GLAccount.id)
            .where(TrialBalance.entity_id == tenant_id, TrialBalance.period == period)
        )
        rows = session.execute(stmt).all()
        data = [
            {
                "id": str(r.id),
                "entity_id": str(r.entity_id),
                "period": str(r.period),
                "account_id": str(r.account_id),
                "account_number": str(r.account_number),
                "account_name": str(r.account_name),
                "account_type": str(r.account_type),
                "debit": float(r.debit),
                "credit": float(r.credit),
                "balance": float(r.balance),
            }
            for r in rows
        ]
        row_count = len(data)

        # Totals for quick reconcilation checks
        total_debits = sum(r["debit"] for r in data)
        total_credits = sum(r["credit"] for r in data)

        # ---- coverage ----
        tb_acct_count = (
            session.execute(
                select(func.count(func.distinct(TrialBalance.account_id))).where(
                    TrialBalance.entity_id == tenant_id, TrialBalance.period == period
                )
            ).scalar()
            or 0
        )
        total_active_accts = (
            session.execute(
                select(func.count(GLAccount.id)).where(GLAccount.entity_id == tenant_id)
            ).scalar()
            or 1
        )
        coverage_pct = round(tb_acct_count / total_active_accts, 4)

        # ---- freshness – no timestamp on trial_balance ----
        freshness_seconds: int | None = None

    quality_score = compute_quality_score(coverage_pct, row_count, freshness_seconds)
    degraded_mode = compute_degraded_mode(coverage_pct, row_count)
    query_fingerprint = compute_query_fingerprint(
        "query_trial_balance",
        tenant_id=tenant_id,
        period=period,
    )

    return ToolResult(
        data=data,
        row_count=row_count,
        coverage_pct=coverage_pct,
        quality_score=quality_score,
        freshness_seconds=freshness_seconds,
        schema_version="1.0",
        source_diversity=2,  # TrialBalance + GLAccount
        source_type="financial_fact",
        retrieval_scope="factual",
        tenant_id=tenant_id,
        required_filters_present=True,
        insufficient_data=coverage_pct < 0.5 or row_count == 0,
        degraded_mode=degraded_mode,
        query_fingerprint=query_fingerprint,
    )
