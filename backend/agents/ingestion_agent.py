from backend.models.state import PipelineState


def ingestion_node(state: PipelineState) -> dict:
    period = state["period"]
    entity_id = state["entity_id"]

    actuals = _fetch_actuals(period, entity_id)
    budget = _fetch_budget(period, entity_id)
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


def _fetch_actuals(period: str, entity_id: str) -> list[dict]:
    return [{"account_id": "mock", "amount": 100000}]


def _fetch_budget(period: str, entity_id: str) -> list[dict]:
    return [{"account_id": "mock", "amount": 100000}]


def _check_reconciliation(actuals: list[dict]) -> bool:
    return True


def _detect_anomalies(actuals: list[dict], budget: list[dict]) -> list[str]:
    return []
