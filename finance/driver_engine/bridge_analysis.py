"""Bridge analysis engine — deterministic variance decomposition.

Decomposes revenue and cost variances into:
- Price/Volume/Mix (for revenue accounts)
- One-time/Timing/Scope (for cost accounts)
- FX impact (when applicable)

All decomposition is deterministic — no LLM involved.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from shared.models.assertions import Assertion


class BridgeType(StrEnum):
    REVENUE = "revenue"
    COST = "cost"


class BridgeComponent(StrEnum):
    # Revenue decomposition
    PRICE = "price"
    VOLUME = "volume"
    MIX = "mix"
    FX = "fx"
    # Cost decomposition
    ONE_TIME = "one_time"
    TIMING = "timing"
    SCOPE = "scope"
    RATE = "rate"


@dataclass
class BridgeDecomposition:
    """A single decomposed component of a variance bridge."""
    component: BridgeComponent
    amount: Decimal
    percentage: Decimal  # % of total variance
    description: str
    confidence: float  # deterministic confidence based on data quality

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component.value,
            "amount": str(self.amount),
            "percentage": str(self.percentage),
            "description": self.description,
            "confidence": self.confidence,
        }


@dataclass
class BridgeAnalysis:
    """Full bridge analysis result for one account."""
    account_id: str
    account_name: str
    total_variance: Decimal
    bridge_type: BridgeType
    components: list[BridgeDecomposition]
    reconciles: bool  # does sum(components) == total_variance?
    reconciliation_diff: Decimal
    confidence: float
    degraded_modes: list[str] | None = None

    @property
    def component_amounts(self) -> dict[str, Decimal]:
        return {c.component.value: c.amount for c in self.components}

    @property
    def largest_component(self) -> BridgeDecomposition | None:
        if not self.components:
            return None
        return max(self.components, key=lambda c: abs(c.amount))

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "account_name": self.account_name,
            "total_variance": str(self.total_variance),
            "bridge_type": self.bridge_type.value,
            "components": [c.to_dict() for c in self.components],
            "reconciles": self.reconciles,
            "reconciliation_diff": str(self.reconciliation_diff),
            "confidence": self.confidence,
            "degraded_modes": self.degraded_modes or [],
        }


def decompose_revenue_bridge(
    account_id: str,
    account_name: str,
    current_actual: Decimal,
    prior_actual: Decimal,
    budget: Decimal,
    fx_rate_current: Decimal | None = None,
    fx_rate_prior: Decimal | None = None,
    volume_current: Decimal | None = None,
    volume_prior: Decimal | None = None,
) -> BridgeAnalysis:
    """Decompose revenue variance into price/volume/mix + optional FX.

    Formula:
    - Total variance = current_actual - budget
    - Price effect = (current_price - budget_price) x current_volume
    - Volume effect = (current_volume - budget_volume) x budget_price
    - Mix effect = residual after price and volume
    - FX effect = if rates provided, difference due to FX

    When volume data is not available, split proportionally:
    - Price ~ 60% of non-FX variance (typical revenue driver)
    - Volume ~ 25%
    - Mix ~ 15%
    """
    from shared.models.degraded_mode import DegradedMode

    total_variance = current_actual - budget
    components: list[BridgeDecomposition] = []
    degraded: list[str] = []

    if total_variance == Decimal("0"):
        return BridgeAnalysis(
            account_id=account_id,
            account_name=account_name,
            total_variance=total_variance,
            bridge_type=BridgeType.REVENUE,
            components=[],
            reconciles=True,
            reconciliation_diff=Decimal("0"),
            confidence=1.0,
        )

    # FX effect
    fx_effect = Decimal("0")
    if (
        fx_rate_current is not None
        and fx_rate_prior is not None
        and fx_rate_current != fx_rate_prior
    ):
        fx_effect = (fx_rate_current - fx_rate_prior) * current_actual / fx_rate_current
        fx_effect = fx_effect.quantize(Decimal("0.01"))
        fx_pct = (
            (fx_effect / total_variance * 100).quantize(Decimal("0.01"))
            if total_variance != 0
            else Decimal("0")
        )
        components.append(
            BridgeDecomposition(
                component=BridgeComponent.FX,
                amount=fx_effect,
                percentage=fx_pct,
                description=f"FX impact: rate changed from {fx_rate_prior} to {fx_rate_current}",
                confidence=0.9,
            )
        )

    non_fx_variance = total_variance - fx_effect

    # Price/Volume/Mix decomposition
    if volume_current is not None and volume_prior is not None:
        budget_price = budget / volume_prior if volume_prior != 0 else Decimal("0")
        current_price = current_actual / volume_current if volume_current != 0 else Decimal("0")

        price_effect = (current_price - budget_price) * volume_current
        volume_effect = (volume_current - volume_prior) * budget_price
        mix_effect = non_fx_variance - price_effect - volume_effect
    else:
        # Heuristic split when volume data not available
        price_effect = (non_fx_variance * Decimal("0.6")).quantize(Decimal("0.01"))
        volume_effect = (non_fx_variance * Decimal("0.25")).quantize(Decimal("0.01"))
        mix_effect = non_fx_variance - price_effect - volume_effect

    for comp, amount in [
        (BridgeComponent.PRICE, price_effect),
        (BridgeComponent.VOLUME, volume_effect),
        (BridgeComponent.MIX, mix_effect),
    ]:
        pct = (
            (amount / total_variance * 100).quantize(Decimal("0.01"))
            if total_variance != 0
            else Decimal("0")
        )
        has_data = volume_current is not None if comp == BridgeComponent.PRICE else True
        conf = 0.85 if has_data else 0.6
        components.append(
            BridgeDecomposition(
                component=comp,
                amount=amount,
                percentage=pct,
                description=f"{comp.value.title()} effect: ${amount:,.2f}",
                confidence=conf,
            )
        )

    # Reconciliation check
    sum_components = sum(c.amount for c in components)
    diff = (total_variance - sum_components).quantize(Decimal("0.01"))
    reconciles = abs(diff) < Decimal("1.00")

    overall_confidence = min(c.confidence for c in components) if components else 0.8
    if not reconciles:
        overall_confidence *= 0.7

    return BridgeAnalysis(
        account_id=account_id,
        account_name=account_name,
        total_variance=total_variance,
        bridge_type=BridgeType.REVENUE,
        components=components,
        reconciles=reconciles,
        reconciliation_diff=diff,
        confidence=overall_confidence,
        degraded_modes=[d for d in degraded if d != DegradedMode.NONE.value],
    )


def decompose_cost_bridge(
    account_id: str,
    account_name: str,
    current_actual: Decimal,
    prior_actual: Decimal,
    budget: Decimal,
    is_one_time: bool = False,
    timing_shift: bool = False,
    scope_changed: bool = False,
) -> BridgeAnalysis:
    """Decompose cost variance into one-time/timing/scope/rate.

    When flags are available:
    - One-time items (e.g., legal settlement) -> one_time
    - Timing shifts (expense moved between periods) -> timing
    - Scope changes (new headcount, new project) -> scope
    - Residual -> rate

    When flags are not available, heuristic split.
    """
    from shared.models.degraded_mode import DegradedMode

    total_variance = current_actual - budget
    components: list[BridgeDecomposition] = []
    degraded: list[str] = []

    if total_variance == Decimal("0"):
        return BridgeAnalysis(
            account_id=account_id,
            account_name=account_name,
            total_variance=total_variance,
            bridge_type=BridgeType.COST,
            components=[],
            reconciles=True,
            reconciliation_diff=Decimal("0"),
            confidence=1.0,
        )

    if is_one_time:
        one_time_amount = total_variance
        rate_effect = Decimal("0")
        timing_amount = Decimal("0")
        scope_amount = Decimal("0")
    elif timing_shift:
        timing_amount = total_variance
        one_time_amount = Decimal("0")
        rate_effect = Decimal("0")
        scope_amount = Decimal("0")
    elif scope_changed:
        scope_amount = total_variance
        one_time_amount = Decimal("0")
        timing_amount = Decimal("0")
        rate_effect = Decimal("0")
    else:
        # Heuristic split
        one_time_amount = (total_variance * Decimal("0.2")).quantize(Decimal("0.01"))
        timing_amount = (total_variance * Decimal("0.2")).quantize(Decimal("0.01"))
        scope_amount = (total_variance * Decimal("0.3")).quantize(Decimal("0.01"))
        rate_effect = total_variance - one_time_amount - timing_amount - scope_amount

    for comp, amount, has_flag in [
        (BridgeComponent.ONE_TIME, one_time_amount, is_one_time),
        (BridgeComponent.TIMING, timing_amount, timing_shift),
        (BridgeComponent.SCOPE, scope_amount, scope_changed),
        (BridgeComponent.RATE, rate_effect, not any([is_one_time, timing_shift, scope_changed])),
    ]:
        if amount == Decimal("0"):
            continue
        pct = (
            (amount / total_variance * 100).quantize(Decimal("0.01"))
            if total_variance != 0
            else Decimal("0")
        )
        conf = 0.85 if has_flag else 0.5
        components.append(
            BridgeDecomposition(
                component=comp,
                amount=amount,
                percentage=pct,
                description=f"{comp.value.title()} effect: ${amount:,.2f}",
                confidence=conf,
            )
        )

    sum_components = sum(c.amount for c in components)
    diff = (total_variance - sum_components).quantize(Decimal("0.01"))
    reconciles = abs(diff) < Decimal("1.00")

    overall_confidence = min(c.confidence for c in components) if components else 0.8
    if not reconciles:
        overall_confidence *= 0.7

    if not any([is_one_time, timing_shift, scope_changed]):
        degraded.append(DegradedMode.INSUFFICIENT_CAUSAL_EVIDENCE.value)

    return BridgeAnalysis(
        account_id=account_id,
        account_name=account_name,
        total_variance=total_variance,
        bridge_type=BridgeType.COST,
        components=components,
        reconciles=reconciles,
        reconciliation_diff=diff,
        confidence=overall_confidence,
        degraded_modes=degraded,
    )


def decompose_bridge(
    account_id: str,
    account_name: str,
    current_actual: Decimal,
    prior_actual: Decimal,
    budget: Decimal,
    account_type: str = "revenue",
    **kwargs: Any,
) -> BridgeAnalysis:
    """Route to the correct decomposition based on account type."""
    if account_type.lower() in ("revenue", "sales", "income"):
        return decompose_revenue_bridge(
            account_id=account_id,
            account_name=account_name,
            current_actual=current_actual,
            prior_actual=prior_actual,
            budget=budget,
            **kwargs,
        )
    else:
        return decompose_cost_bridge(
            account_id=account_id,
            account_name=account_name,
            current_actual=current_actual,
            prior_actual=prior_actual,
            budget=budget,
            **kwargs,
        )


def build_bridge_assertions(analysis: BridgeAnalysis) -> list["Assertion"]:
    """Convert a BridgeAnalysis into validated Assertion objects."""
    from shared.models.assertions import Assertion, AssertionType, SupportLevel

    assertions = []

    # Main variance assertion
    assertions.append(
        Assertion(
            id=f"bridge_{analysis.account_id}_total",
            type=AssertionType.NUMERIC,
            text=f"{analysis.account_name} total variance: ${analysis.total_variance:,.2f}",
            value=analysis.total_variance,
            evidence_ids=[f"bridge:{analysis.account_id}"],
            support_level=SupportLevel.VERIFIED,
            confidence=analysis.confidence,
            metadata={"bridge_type": analysis.bridge_type.value},
        )
    )

    # Component assertions
    for comp in analysis.components:
        assertions.append(
            Assertion(
                id=f"bridge_{analysis.account_id}_{comp.component.value}",
                type=AssertionType.NUMERIC,
                text=f"{analysis.account_name} {comp.component.value} effect: ${comp.amount:,.2f}",
                value=comp.amount,
                evidence_ids=[f"bridge:{analysis.account_id}:{comp.component.value}"],
                support_level=(
                    SupportLevel.VERIFIED if comp.confidence > 0.7 else SupportLevel.PROBABLE
                ),
                confidence=comp.confidence,
                metadata={"component": comp.component.value, "percentage": str(comp.percentage)},
            )
        )

    return assertions
