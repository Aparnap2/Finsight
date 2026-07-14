def drill_gl_detail(account_id: str, period: str, department: str | None = None) -> list[dict]:
    return [{"account_id": account_id, "period": period, "amount": 100000}]


def fetch_trial_balance(period: str, entity_id: str = "CF001") -> list[dict]:
    return [{"period": period, "total_debits": 500000, "total_credits": 500000}]
