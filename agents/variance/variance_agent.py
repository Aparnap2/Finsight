from decimal import Decimal

from shared.models.state import PipelineState, Variance


def compute_variances(actuals: list[dict], budget: list[dict]) -> list[Variance]:
    budget_map = {b["account_id"]: b for b in budget}
    variances = []
    for a in actuals:
        acct_id = a["account_id"]
        act_amt = Decimal(str(a["amount"]))
        bud_amt = Decimal(str(budget_map.get(acct_id, {}).get("amount", 0)))
        var_amt = act_amt - bud_amt
        var_pct = (var_amt / bud_amt) * Decimal("100") if bud_amt != Decimal("0") else Decimal("0")
        variances.append(Variance(
            account_id=acct_id,
            account_name=a.get("account_name", acct_id),
            department=a.get("department", "Unknown"),
            actual_amount=act_amt,
            budget_amount=bud_amt,
            variance_amount=var_amt,
            variance_pct=var_pct.quantize(Decimal("0.01")),
        ))
    return variances


def apply_materiality(
    variances: list[Variance],
    threshold_amount: float = 5000.0,
    threshold_pct: float = 5.0,
) -> list[Variance]:
    threshold_amount_d = Decimal(str(threshold_amount))
    threshold_pct_d = Decimal(str(threshold_pct))
    for v in variances:
        v.is_material = abs(v.variance_amount) >= threshold_amount_d and abs(v.variance_pct) >= threshold_pct_d
    return variances


def variance_node(state: PipelineState) -> dict:
    actuals = state.get("actuals", {}).get("accounts", [])
    budget = state.get("budget", {}).get("accounts", [])
    variances = compute_variances(actuals, budget)
    variances = apply_materiality(variances)
    return {"variances": variances, "current_step": "variance_complete"}
