"""Variance detection agent node: compute variances and flag materiality.

Materiality thresholds are tenant-driven — they come from the resolved
:class:`TenantConfig` (or explicit Decimal args), never from hardcoded
defaults. Comparisons use OR semantics (either threshold crossed is
material), reconciled with ``finance/variance_engine/materiality.py`` as
the single source of truth.
"""

from decimal import Decimal
from typing import Any, cast

from finplatform.config.tenant_schema import TenantConfig, TenantConfigError
from shared.models.state import PipelineState, Variance


def compute_variances(
    actuals: list[dict[str, Any]], budget: list[dict[str, Any]]
) -> list[Variance]:
    """Compute per-account variances between actuals and budget as Decimals."""
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
    threshold_amount: Decimal | None = None,
    threshold_pct: Decimal | None = None,
    tenant_config: TenantConfig | None = None,
) -> list[Variance]:
    """Mark variances as material using tenant or explicit thresholds.

    Threshold precedence: explicit ``threshold_amount``/``threshold_pct``
    args > ``tenant_config`` materiality > ``ValueError`` when nothing is
    provided (no hardcoded defaults). A variance is material when EITHER
    the absolute or the percentage threshold is crossed (OR semantics —
    same default as ``MaterialityEngine``'s ``combined_rule="any"``).
    """
    if threshold_amount is None or threshold_pct is None:
        if tenant_config is None:
            raise ValueError(
                "materiality thresholds required: pass explicit threshold_amount/"
                "threshold_pct or tenant_config"
            )
        if threshold_amount is None:
            threshold_amount = tenant_config.materiality.amount
        if threshold_pct is None:
            threshold_pct = tenant_config.materiality.pct
    threshold_amount_d = Decimal(threshold_amount)
    threshold_pct_d = Decimal(threshold_pct)
    for v in variances:
        # OR semantics: any threshold crossed => material (matches
        # MaterialityEngine default combined_rule="any").
        v.is_material = (
            abs(v.variance_amount) >= threshold_amount_d
            or abs(v.variance_pct) >= threshold_pct_d
        )
    return variances


def variance_node(
    state: PipelineState, tenant_config: TenantConfig | None = None
) -> dict[str, Any]:
    """Variance detection graph node: compute variances and flag materiality.

    When no explicit ``tenant_config`` is supplied, the tenant is resolved
    from ``state["tenant_id"]`` via ``TenantConfig.load``. A missing or
    invalid tenant config falls back to explicit args and raises a clear
    ``ValueError`` when no thresholds are available.
    """
    actuals_wrapper = state.get("actuals")
    actuals = cast(
        list[dict[str, Any]],
        actuals_wrapper.get("accounts", []) if isinstance(actuals_wrapper, dict) else [],
    )
    budget_wrapper = state.get("budget")
    budget = cast(
        list[dict[str, Any]],
        budget_wrapper.get("accounts", []) if isinstance(budget_wrapper, dict) else [],
    )
    variances = compute_variances(actuals, budget)
    resolved = tenant_config
    if resolved is None:
        tenant_id = state.get("tenant_id")
        if tenant_id:
            try:
                resolved = TenantConfig.load(tenant_id)
            except TenantConfigError:
                resolved = None
    variances = apply_materiality(variances, tenant_config=resolved)
    return {"variances": variances, "current_step": "variance_complete"}
