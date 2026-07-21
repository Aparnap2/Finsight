from decimal import Decimal

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session
from backend.models.database import Actual, BudgetLine, GLAccount, TrialBalance
from backend.models.state import PipelineState


def ingestion_node(state: PipelineState, engine: Engine | None = None) -> dict:
    period = state["period"]
    entity_id = state["tenant_id"]

    if engine:
        actuals = _fetch_actuals_from_db(period, entity_id, engine)
        budget = _fetch_budget_from_db(period, entity_id, engine)
    else:
        actuals = _fetch_actuals_mock(period, entity_id)
        budget = _fetch_budget_mock(period, entity_id)

    is_reconciled = _check_reconciliation(actuals)
    anomalies = _detect_anomalies(actuals, budget)

    return {
        "actuals": {
            "period": period,
            "entity_id": entity_id,
            "accounts": actuals,
            "is_reconciled": is_reconciled,
            "anomalies": anomalies,
        },
        "budget": {
            "period": period,
            "entity_id": entity_id,
            "accounts": budget,
        },
        "current_step": "ingestion_complete",
    }


def _fetch_actuals_from_db(period: str, entity_id: str, engine: Engine) -> list[dict]:
    with Session(engine) as session:
        stmt = (
            select(Actual, GLAccount.account_name, GLAccount.department)
            .join(GLAccount, Actual.account_id == GLAccount.id)
            .where(Actual.entity_id == entity_id, Actual.period == period)
        )
        rows = session.execute(stmt).all()
        return [
            {
                "account_id": str(actual.account_id),
                "account_name": str(account_name),
                "department": str(department),
                "amount": Decimal(actual.amount),
            }
            for actual, account_name, department in rows
        ]


def _fetch_budget_from_db(period: str, entity_id: str, engine: Engine) -> list[dict]:
    with Session(engine) as session:
        stmt = (
            select(BudgetLine, GLAccount.account_name, GLAccount.department)
            .join(GLAccount, BudgetLine.account_id == GLAccount.id)
            .where(BudgetLine.entity_id == entity_id, BudgetLine.period == period)
        )
        rows = session.execute(stmt).all()
        return [
            {
                "account_id": str(budget.account_id),
                "account_name": str(account_name),
                "department": str(department),
                "amount": Decimal(budget.amount),
            }
            for budget, account_name, department in rows
        ]


def _fetch_actuals_mock(period: str, entity_id: str) -> list[dict]:
    return [{"account_id": "mock", "amount": 100000}]


def _fetch_budget_mock(period: str, entity_id: str) -> list[dict]:
    return [{"account_id": "mock", "amount": 100000}]


def _check_reconciliation(actuals: list[dict]) -> bool:
    return True


def _detect_anomalies(actuals: list[dict], budget: list[dict]) -> list[str]:
    return []
