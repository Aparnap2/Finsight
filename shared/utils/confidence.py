"""Deterministic confidence computation engine.

Confidence is computed from verifiable metadata only:
- evidence_count, source_count, coverage_pct, quality_score
- freshness, contradiction_count, assertion_class
- data quality status, bridge reconciliation, direct recomputability

Each assertion class has a separate scoring function.
"""

from decimal import Decimal
from shared.models.assertions import Assertion, AssertionType, SupportLevel
from shared.models.degraded_mode import DegradedMode


def compute_fact_confidence(
    evidence_count: int,
    source_count: int,
    coverage_pct: float,
    quality_score: float,
    freshness_seconds: int | None = None,
    max_age_seconds: int = 86400 * 90,  # 90 days
    is_directly_recomputable: bool = False,
) -> float:
    """Confidence for NUMERIC assertions (directly verifiable facts).

    Base: evidence_count / (evidence_count + 1)  (saturating at ~0.91 with 10 sources)
    Modifiers:
      - +0.05 if coverage_pct > 0.8
      - +0.05 if quality_score > 0.8
      - +0.05 if is_directly_recomputable (can rederive from source data)
      - -0.10 if freshness_seconds and freshness_seconds > max_age_seconds
      - clamped to [0.0, 1.0]
    """
    base = evidence_count / (evidence_count + 1) if evidence_count > 0 else 0.0
    modifier = 0.0
    if coverage_pct > 0.8:
        modifier += 0.05
    if quality_score > 0.8:
        modifier += 0.05
    if is_directly_recomputable:
        modifier += 0.05
    if freshness_seconds is not None and freshness_seconds > max_age_seconds:
        modifier -= 0.10
    return max(0.0, min(1.0, base + modifier))


def compute_comparative_confidence(
    fact_confidence: float,
    candidate_count: int,
    rank_position: int | None = None,
) -> float:
    """Confidence for COMPARATIVE assertions (ranking, ordering, "largest").

    - Starts from fact_confidence of the underlying facts
    - Reduced if few candidates to compare (need >=2 for meaningful comparison)
    - Slightly higher if the claim is about the top rank (1st/2nd are more reliable)

    Base: fact_confidence * min(1.0, candidate_count / 3.0)
    Modifier: +0.05 if rank_position == 1
    Clamped to [0.0, fact_confidence]
    """
    if candidate_count < 2:
        return fact_confidence * 0.5  # Not enough candidates for meaningful comparison
    base = fact_confidence * min(1.0, candidate_count / 3.0)
    if rank_position == 1:
        base += 0.05
    return max(0.0, min(fact_confidence, base))


def compute_causal_confidence(
    fact_confidence: float,
    evidence_class_count: int,
    driver_tree_verified: bool = False,
    has_alternative_explanations: bool = False,
    degraded_modes: list[DegradedMode] | None = None,
) -> float:
    """Confidence for CAUSAL assertions ("was driven by X").

    Causal claims are inherently less certain than facts:
    - Starts from fact_confidence * 0.8 (cap at 0.8 for causal)
    - +0.10 if multiple evidence classes support the claim (e.g., both financial + operational)
    - +0.05 if driver tree is verified
    - -0.15 if alternative explanations exist
    - -0.10 per degraded mode
    - Max 0.85 (causal never reaches "verified" level)
    - Min 0.0
    """
    base = fact_confidence * 0.8
    if evidence_class_count >= 2:
        base += 0.10
    if driver_tree_verified:
        base += 0.05
    if has_alternative_explanations:
        base -= 0.15
    if degraded_modes:
        base -= 0.10 * len([m for m in degraded_modes if m != DegradedMode.NONE])
    return max(0.0, min(0.85, base))


def compute_hypothesis_confidence(
    fact_confidence: float,
    supporting_precedent_count: int = 0,
    supporting_source_count: int = 0,
    plausible_mechanism: bool = False,
) -> float:
    """Confidence for HYPOTHESIS assertions ("possibly due to...").

    Hypotheses are speculative by nature:
    - Max 0.5 (never reaches "probable")
    - +0.05 if precedent supports the hypothesis
    - +0.05 if plausible mechanism exists
    - Clamped to [0.0, 0.5]
    """
    base = fact_confidence * 0.3
    if supporting_precedent_count > 0:
        base += 0.05
    if supporting_source_count > 0:
        base += 0.05
    if plausible_mechanism:
        base += 0.05
    return max(0.0, min(0.5, base))


def compute_action_confidence(
    causal_confidence: float,
    taxonomy_valid: bool = False,
    policy_permitted: bool = False,
    impact_quantified: bool = False,
    owner_identified: bool = False,
) -> float:
    """Confidence for ACTION assertions ("should reduce costs by...").

    Actions depend on:
    - Their supporting causal analysis
    - Whether the action is in the approved taxonomy
    - Whether policy permits it
    - Whether impact is quantified and owner identified

    Base: causal_confidence * 0.7
    +0.10 if taxonomy_valid
    +0.10 if policy_permitted
    +0.05 if impact_quantified
    +0.05 if owner_identified
    Clamped to [0.0, 0.9]
    """
    base = causal_confidence * 0.7
    if taxonomy_valid:
        base += 0.10
    if policy_permitted:
        base += 0.10
    if impact_quantified:
        base += 0.05
    if owner_identified:
        base += 0.05
    return max(0.0, min(0.9, base))


def compute_deterministic_confidence(
    assertion: Assertion,
    evidence_count: int = 0,
    source_count: int = 0,
    coverage_pct: float = 0.0,
    quality_score: float = 0.0,
    freshness_seconds: int | None = None,
    candidate_count: int | None = None,
    rank_position: int | None = None,
    evidence_class_count: int = 1,
    driver_tree_verified: bool = False,
    has_alternative_explanations: bool = False,
    degraded_modes: list[DegradedMode] | None = None,
    supporting_precedent_count: int = 0,
    supporting_source_count: int = 0,
    plausible_mechanism: bool = False,
    taxonomy_valid: bool = False,
    policy_permitted: bool = False,
    impact_quantified: bool = False,
    owner_identified: bool = False,
    is_directly_recomputable: bool = False,
) -> float:
    """Route to the correct confidence function based on assertion type.

    Returns a single confidence score in [0.0, 1.0].
    """
    fact_conf = compute_fact_confidence(
        evidence_count=evidence_count or len(assertion.evidence_ids),
        source_count=source_count,
        coverage_pct=coverage_pct,
        quality_score=quality_score,
        freshness_seconds=freshness_seconds,
        is_directly_recomputable=is_directly_recomputable,
    )

    if assertion.type == AssertionType.NUMERIC:
        return fact_conf

    elif assertion.type == AssertionType.COMPARATIVE:
        return compute_comparative_confidence(
            fact_confidence=fact_conf,
            candidate_count=candidate_count or evidence_count,
            rank_position=rank_position,
        )

    elif assertion.type == AssertionType.CAUSAL:
        return compute_causal_confidence(
            fact_confidence=fact_conf,
            evidence_class_count=evidence_class_count,
            driver_tree_verified=driver_tree_verified,
            has_alternative_explanations=has_alternative_explanations,
            degraded_modes=degraded_modes,
        )

    elif assertion.type == AssertionType.HYPOTHESIS:
        return compute_hypothesis_confidence(
            fact_confidence=fact_conf,
            supporting_precedent_count=supporting_precedent_count,
            supporting_source_count=supporting_source_count,
            plausible_mechanism=plausible_mechanism,
        )

    elif assertion.type == AssertionType.ACTION:
        return compute_action_confidence(
            causal_confidence=fact_conf,
            taxonomy_valid=taxonomy_valid,
            policy_permitted=policy_permitted,
            impact_quantified=impact_quantified,
            owner_identified=owner_identified,
        )

    return fact_conf
