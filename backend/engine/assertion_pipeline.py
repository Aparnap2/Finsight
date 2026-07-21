"""Assertion pipeline — transforms raw tool data into validated, confidence-scored assertions.

Flow:
1. Collect ToolResults from all tools
2. Build Assertion objects (typed claims with evidence)
3. Validate each assertion by class
4. Compute deterministic confidence
5. Surface only valid/passing assertions to commentary
"""

from decimal import Decimal
from typing import Any

from backend.models.assertions import Assertion, AssertionType, SupportLevel
from backend.models.degraded_mode import DegradedMode
from backend.engine.confidence import compute_deterministic_confidence
from backend.validators.claim_validator import (
    validate_numeric_claim,
    validate_comparative_claim,
    validate_causal_claim,
    validate_action_claim,
    MonetaryClaim,
    CausalClaim,
    ActionClaim,
)
from backend.tools.tool_result import ToolResult


class AssertionPipelineResult:
    """Result of running the assertion pipeline."""

    def __init__(
        self,
        assertions: list[Assertion] | None = None,
        rejected: list[dict] | None = None,
        degraded_modes: list[str] | None = None,
        summary: str | None = None,
    ):
        self.assertions = assertions or []
        self.rejected = rejected or []
        self.degraded_modes = degraded_modes or []
        self.summary = summary or ""

    @property
    def has_valid_assertions(self) -> bool:
        return len(self.assertions) > 0

    @property
    def highest_confidence(self) -> float:
        if not self.assertions:
            return 0.0
        return max(a.confidence for a in self.assertions)

    @property
    def all_verified(self) -> bool:
        return all(
            a.support_level == SupportLevel.VERIFIED
            for a in self.assertions
            if a.type != AssertionType.HYPOTHESIS
        )


def build_numeric_assertion(
    account_name: str,
    actual: Decimal,
    budget: Decimal,
    variance: Decimal,
    variance_pct: Decimal,
    tool_results: list[ToolResult],
) -> Assertion | None:
    """Build a NUMERIC assertion from variance data.

    A numeric assertion represents a directly verifiable fact:
    'Account X had actual $A vs budget $B, a variance of $V.'
    """
    if not tool_results:
        return None

    # Aggregate metadata from all tool results
    total_evidence = sum(tr.row_count for tr in tool_results)
    total_sources = sum(tr.source_diversity for tr in tool_results)
    avg_coverage = sum(tr.coverage_pct for tr in tool_results) / len(tool_results)
    avg_quality = sum(tr.quality_score for tr in tool_results) / len(tool_results)
    freshness = min(
        (tr.freshness_seconds for tr in tool_results if tr.freshness_seconds is not None),
        default=None,
    )
    degraded = [tr.degraded_mode for tr in tool_results if tr.degraded_mode]

    evidence_ids = [f"tool:{id(tr)}" for tr in tool_results]

    assertion = Assertion(
        id=f"num_{account_name.lower().replace(' ', '_')}",
        type=AssertionType.NUMERIC,
        text=(
            f"{account_name}: actual ${actual:,} vs budget ${budget:,}, "
            f"variance ${variance:,} ({variance_pct:+.2f}%)"
        ),
        value=variance,
        evidence_ids=evidence_ids,
        support_level=SupportLevel.VERIFIED,
        confidence=0.0,  # will be computed below
        metadata={
            "account_name": account_name,
            "actual_amount": str(actual),
            "budget_amount": str(budget),
            "variance_pct": str(variance_pct),
            "tool_count": len(tool_results),
            "degraded_modes": degraded,
        },
    )

    # Compute deterministic confidence
    assertion.confidence = compute_deterministic_confidence(
        assertion=assertion,
        evidence_count=total_evidence,
        source_count=total_sources,
        coverage_pct=avg_coverage,
        quality_score=avg_quality,
        freshness_seconds=freshness,
        is_directly_recomputable=True,  # variances are directly recomputable from actuals/budget
    )

    return assertion


def build_comparative_assertion(
    subject: str,
    candidates: list[dict],
    value_field: str = "amount",
    rank: int | None = None,
    tool_results: list[ToolResult] | None = None,
) -> Assertion | None:
    """Build a COMPARATIVE assertion (e.g., 'X is the largest variance')."""
    if len(candidates) < 2:
        return None

    sorted_candidates = sorted(candidates, key=lambda c: c.get(value_field, 0), reverse=True)
    top = sorted_candidates[0]

    text = f"{subject} is the largest at ${top.get(value_field, 0):,}"
    if rank:
        text = f"{subject} is ranked #{rank} at ${top.get(value_field, 0):,}"

    evidence_ids = [
        f"candidate:{c.get('account_id', i)}" for i, c in enumerate(sorted_candidates[:5])
    ]

    # Validate the comparative claim
    validation = validate_comparative_claim(
        claim_text=text,
        subject=subject,
        candidates=candidates,
        value_field=value_field,
        rank=rank,
    )

    confidence = compute_deterministic_confidence(
        assertion=Assertion(
            id=f"cmp_{subject.lower().replace(' ', '_')}",
            type=AssertionType.COMPARATIVE,
            text=text,
            value=Decimal(str(top.get(value_field, 0))),
            evidence_ids=evidence_ids,
        ),
        evidence_count=len(sorted_candidates),
        source_count=len(set(c.get("account_id", "") for c in sorted_candidates)),
        coverage_pct=1.0,
        quality_score=0.9 if validation.is_valid else 0.5,
        candidate_count=len(candidates),
        rank_position=rank,
    )

    return Assertion(
        id=f"cmp_{subject.lower().replace(' ', '_')}",
        type=AssertionType.COMPARATIVE,
        text=text,
        value=Decimal(str(top.get(value_field, 0))),
        evidence_ids=evidence_ids,
        support_level=SupportLevel.VERIFIED if validation.is_valid else SupportLevel.PROBABLE,
        confidence=confidence,
        metadata={"candidate_count": len(candidates), "rank": rank, "validated": validation.is_valid},
    )


def build_causal_assertion(
    cause: str,
    effect: str,
    driver_tree_edges: list[dict] | None = None,
    evidence_classes: int = 1,
    has_alternative: bool = False,
    tool_results: list[ToolResult] | None = None,
) -> Assertion | None:
    """Build a CAUSAL assertion ('driven by X')."""
    text = f"Variance driven by {cause}"

    validation = validate_causal_claim(
        claim=CausalClaim(text=text, cause=cause, effect=effect),
        driver_tree_edges=driver_tree_edges,
        evidence_classes=evidence_classes,
        has_alternative=has_alternative,
    )

    if not validation.is_valid and not driver_tree_edges:
        return None  # Reject unsupported causal claims

    evidence_ids = [f"driver:{e.get('from', 'unknown')}" for e in (driver_tree_edges or [])]

    # Causal assertions never reach VERIFIED
    support = SupportLevel.PROBABLE if driver_tree_edges else SupportLevel.WEAK
    if has_alternative:
        support = SupportLevel.WEAK

    assertion = Assertion(
        id=f"causal_{cause.lower().replace(' ', '_')}",
        type=AssertionType.CAUSAL,
        text=text,
        value=Decimal("0"),
        evidence_ids=evidence_ids,
        support_level=support,
        confidence=0.0,
        metadata={
            "cause": cause,
            "effect": effect,
            "driver_tree_edges": len(driver_tree_edges or []),
            "evidence_classes": evidence_classes,
            "has_alternative": has_alternative,
        },
    )

    # Extract DegradedMode values from (str, DegradedMode) tuples
    degraded_mode_values: list[DegradedMode] | None = None
    if validation.degraded_modes:
        degraded_mode_values = [dm[1] for dm in validation.degraded_modes]

    assertion.confidence = compute_deterministic_confidence(
        assertion=assertion,
        evidence_count=len(evidence_ids),
        source_count=evidence_classes,
        coverage_pct=0.7 if driver_tree_edges else 0.3,
        quality_score=0.7 if validation.is_valid else 0.3,
        evidence_class_count=evidence_classes,
        driver_tree_verified=bool(driver_tree_edges),
        has_alternative_explanations=has_alternative,
        degraded_modes=degraded_mode_values,
    )

    return assertion


def build_action_assertion(
    action: str,
    target: str,
    cited_causes: list[str] | None = None,
    policy_permitted: bool = False,
    owner_identified: bool = False,
    impact_quantified: bool = False,
    tool_results: list[ToolResult] | None = None,
) -> Assertion | None:
    """Build an ACTION assertion ('should reduce X by Y')."""
    text = f"Should {action} {target}"
    if impact_quantified:
        text = f"Should {action} {target} with quantified impact"

    validation = validate_action_claim(
        claim=ActionClaim(text=text, action=action, target=target),
        cited_causes=cited_causes,
        policy_permitted=policy_permitted,
        owner_identified=owner_identified,
        impact_quantified=impact_quantified,
    )

    if not validation.is_valid:
        return None  # Reject unsupported actions

    evidence_ids = [f"cause:{c}" for c in (cited_causes or [])]

    assertion = Assertion(
        id=f"action_{action}_{target.lower().replace(' ', '_')}",
        type=AssertionType.ACTION,
        text=text,
        value=Decimal("0"),
        evidence_ids=evidence_ids,
        support_level=SupportLevel.PROBABLE if validation.is_valid else SupportLevel.WEAK,
        confidence=0.0,
        metadata={
            "action": action,
            "target": target,
            "policy_permitted": policy_permitted,
            "owner_identified": owner_identified,
            "impact_quantified": impact_quantified,
        },
    )

    assertion.confidence = compute_deterministic_confidence(
        assertion=assertion,
        evidence_count=len(evidence_ids),
        source_count=len(cited_causes or []),
        coverage_pct=1.0,
        quality_score=validation.confidence,
        taxonomy_valid=True,
        policy_permitted=policy_permitted,
        owner_identified=owner_identified,
        impact_quantified=impact_quantified,
    )

    return assertion


def run_assertion_pipeline(
    variances: list[dict],
    tool_results: dict[str, list[ToolResult]],
    candidates: list[dict] | None = None,
    driver_tree_edges: list[dict] | None = None,
) -> AssertionPipelineResult:
    """Run the full assertion pipeline.

    Takes variance data and tool results, produces validated assertions.
    """
    assertions: list[Assertion] = []
    rejected: list[dict] = []
    all_degraded: set[str] = set()

    # Build NUMERIC assertions from each variance
    for v in variances:
        account_name = v.get("account_name", "Unknown")
        tool_results_for_account = tool_results.get("gl", [])

        assertion = build_numeric_assertion(
            account_name=account_name,
            actual=v.get("actual_amount", Decimal("0")),
            budget=v.get("budget_amount", Decimal("0")),
            variance=v.get("variance_amount", Decimal("0")),
            variance_pct=v.get("variance_pct", Decimal("0")),
            tool_results=tool_results_for_account,
        )
        if assertion:
            assertions.append(assertion)
        else:
            rejected.append({"account": account_name, "reason": "No tool results for variance"})

        # Track degraded modes
        for tr in tool_results_for_account:
            if tr.degraded_mode:
                all_degraded.add(tr.degraded_mode)

    # Build COMPARATIVE assertion if we have candidates
    if candidates:
        cmp = build_comparative_assertion(
            subject="variance",
            candidates=candidates,
            value_field="variance_amount",
            tool_results=tool_results.get("gl", []),
        )
        if cmp:
            assertions.append(cmp)

    # Build CAUSAL assertion if driver tree exists
    if driver_tree_edges:
        for edge in driver_tree_edges:
            causal = build_causal_assertion(
                cause=edge.get("from", "unknown"),
                effect=edge.get("to", "variance"),
                driver_tree_edges=driver_tree_edges,
                evidence_classes=2,
                has_alternative=False,
                tool_results=tool_results.get("headcount", []),
            )
            if causal:
                assertions.append(causal)

    # Sort by confidence descending
    assertions.sort(key=lambda a: a.confidence, reverse=True)

    n = len(assertions)
    n_rejected = len(rejected)

    summary = (
        f"Assertion pipeline complete: {n} assertions built "
        f"({sum(1 for a in assertions if a.support_level == SupportLevel.VERIFIED)} verified, "
        f"{sum(1 for a in assertions if a.support_level == SupportLevel.PROBABLE)} probable, "
        f"{sum(1 for a in assertions if a.support_level == SupportLevel.WEAK)} weak), "
        f"{n_rejected} rejected, "
        f"{len(all_degraded)} degraded modes: {', '.join(sorted(all_degraded)) if all_degraded else 'none'}"
    )

    return AssertionPipelineResult(
        assertions=assertions,
        rejected=rejected,
        degraded_modes=sorted(all_degraded),
        summary=summary,
    )
