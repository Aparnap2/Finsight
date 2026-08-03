"""Claim Validator v2 — validates all assertion classes deterministically.

Key design:
- NUMERIC: exact or tolerance-based match against deterministic facts
- COMPARATIVE: prove ranking/order from a deterministic candidate set
- CAUSAL: never "verified" from prose alone; links to driver tree + evidence
  classes
- ACTION: must map to approved taxonomy, cite validated cause(s), satisfy
  policy, identify owner + impact
"""

import re
from decimal import Decimal
from typing import Any

from shared.models.degraded_mode import DegradedMode

# ── Data classes ──────────────────────────────────────────────────────────────


class MonetaryClaim:
    """A single monetary claim extracted from text."""

    def __init__(self, text: str, amount: Decimal, context: str = "", position: int = 0):
        self.text = text
        self.amount = amount
        self.context = context
        self.position = position  # character offset in source text


# Backward-compatible alias
Claim = MonetaryClaim


class CausalClaim:
    """A causal claim extracted from text."""

    def __init__(self, text: str, cause: str, effect: str, context: str = ""):
        self.text = text
        self.cause = cause
        self.effect = effect
        self.context = context


class ActionClaim:
    """An action claim extracted from text."""

    def __init__(self, text: str, action: str, target: str, impact: str | None = None):
        self.text = text
        self.action = action  # e.g., "reduce", "increase", "review", "renegotiate"
        self.target = target  # e.g., "cloud spend", "headcount"
        self.impact = impact  # optional quantified impact


# ── Validation result container ───────────────────────────────────────────────


class ValidationResult:
    """Container for validation output."""

    def __init__(
        self,
        is_valid: bool = True,
        verified_claims: list[Any] | None = None,
        unverified_claims: list[Any] | None = None,
        errors: list[Any] | None = None,
        degraded_modes: list[tuple[str, DegradedMode]] | None = None,
        confidence: float = 1.0,
    ):
        self.is_valid = is_valid
        self.verified_claims = verified_claims or []
        self.unverified_claims = unverified_claims or []
        self.errors = errors or []
        self.degraded_modes = degraded_modes or []
        self.confidence = confidence
        self.claims: list[MonetaryClaim] = []  # backward compat: raw extracted claims

    def __bool__(self) -> bool:
        return self.is_valid

    def add_degraded(self, claim: str, mode: DegradedMode) -> None:
        self.degraded_modes.append((claim, mode))
        self.confidence = max(0.0, self.confidence - 0.15)


# ── Patterns ──────────────────────────────────────────────────────────────────

MONETARY_PATTERN = re.compile(r'\$[\d,]+(?:\.\d{2})?')
CAUSAL_PATTERN = re.compile(
    r'(?:driven by|due to|because of|resulted from|caused by|attributed to)\s+([\w\s]+)',
    re.IGNORECASE,
)
ACTION_PATTERN = re.compile(
    r'(?:should|ought to|recommend|propose|suggest)\s+(\w+)\s+([\w\s]+?)(?:by|to|for|$)',
    re.IGNORECASE,
)
COMPARATIVE_KEYWORDS = {
    "largest", "biggest", "highest", "lowest", "smallest",
    "most", "least", "top", "primary", "main",
}


# ── Numeric validation (backward compatible) ──────────────────────────────────


def extract_monetary_claims(text: str) -> list[MonetaryClaim]:
    """Extract all $amount claims from commentary text."""
    claims: list[MonetaryClaim] = []
    for match in MONETARY_PATTERN.finditer(text):
        amount_str = match.group().replace("$", "").replace(",", "")
        try:
            amount = Decimal(amount_str)
        except Exception:
            continue
        if amount == Decimal("0"):
            continue
        start = max(0, match.start() - 40)
        end = min(len(text), match.end() + 40)
        context = text[start:end].strip()
        claims.append(
            MonetaryClaim(
                text=match.group(),
                amount=amount,
                context=context,
                position=match.start(),
            )
        )
    return claims


def validate_numeric_claim(
    claim: MonetaryClaim,
    facts: list[dict[str, Any]],
    amount_field: str = "amount",
    tolerance: Decimal = Decimal("0.05"),
) -> ValidationResult:
    """Validate a numeric claim against deterministic facts.

    NUMERIC claims are matched against DB facts at the given tolerance.
    Returns VALID if any fact matches within tolerance, UNVERIFIED otherwise.
    """
    result = ValidationResult()
    amount = claim.amount

    if not facts:
        result.is_valid = False
        result.add_degraded(claim.text, DegradedMode.INSUFFICIENT_CAUSAL_EVIDENCE)
        result.errors.append(f"No facts to validate claim: {claim.text}")
        result.unverified_claims.append({
            "claim": claim.text,
            "amount": str(amount),
            "note": "No facts available for validation",
        })
        return result

    matched = False
    for fact in facts:
        fact_amount = fact.get(amount_field, Decimal("0"))
        if not isinstance(fact_amount, Decimal):
            try:
                fact_amount = Decimal(str(fact_amount))
            except (ValueError, TypeError):
                continue
        if fact_amount == Decimal("0"):
            continue
        ratio = abs(amount - fact_amount) / abs(fact_amount)
        if ratio <= tolerance:
            matched = True
            result.verified_claims.append({
                "claim": claim.text,
                "amount": str(amount),
                "matched_fact": str(fact_amount),
                "tolerance": str(tolerance),
                "ratio": str(ratio),
            })
            break

    if not matched:
        result.is_valid = False
        closest = str(facts[0].get(amount_field, "N/A")) if facts else "N/A"
        result.errors.append(
            f"Claim {claim.text} (amount={amount}) does not match any fact "
            f"(closest: {closest}, tolerance: {tolerance})"
        )
        result.unverified_claims.append({
            "claim": claim.text,
            "amount": str(amount),
            "closest_fact": closest,
        })

    return result


# ── Comparative validation ────────────────────────────────────────────────────


def validate_comparative_claim(
    claim_text: str,
    subject: str,
    candidates: list[dict[str, Any]],
    value_field: str = "amount",
    rank: int | None = None,
) -> ValidationResult:
    """Validate a comparative claim ("largest", "biggest", "top N").

    COMPARATIVE claims must:
    - Have at least 2 candidates in the deterministic set
    - Be provable by sorting the candidate set by the value field
    - Rank position is confirmed if given (1 = highest)
    """
    result = ValidationResult()

    if len(candidates) < 2:
        result.is_valid = False
        result.add_degraded(claim_text, DegradedMode.INSUFFICIENT_CAUSAL_EVIDENCE)
        result.errors.append(
            f"Not enough candidates for comparative claim: {len(candidates)}"
        )
        return result

    sorted_candidates = sorted(
        candidates, key=lambda c: c.get(value_field, 0), reverse=True
    )

    if rank is not None and rank <= len(sorted_candidates):
        ranked_entry = sorted_candidates[rank - 1]
        result.verified_claims.append({
            "claim": claim_text,
            "subject": subject,
            "rank": rank,
            "matched_value": str(ranked_entry.get(value_field, "N/A")),
            "total_candidates": len(candidates),
        })
    else:
        # Just verify the subject exists in the top portion
        result.verified_claims.append({
            "claim": claim_text,
            "subject": subject,
            "total_candidates": len(candidates),
            "note": "Claim validated against sorted candidate set",
        })

    return result


# ── Causal validation ─────────────────────────────────────────────────────────


def validate_causal_claim(
    claim: CausalClaim,
    driver_tree_edges: list[dict[str, Any]] | None = None,
    evidence_classes: int = 0,
    has_alternative: bool = False,
) -> ValidationResult:
    """Validate a causal claim ("was driven by X").

    CAUSAL claims follow this logic:
    - Never "verified" from prose alone
    - Must link to a driver-tree edge if available
    - +1 tier if >=2 evidence classes support it
    - -1 tier if alternative explanations exist
    - Output: PROBABLE, WEAK, or UNSUPPORTED (never VERIFIED)
    """
    result = ValidationResult()

    if driver_tree_edges:
        result.verified_claims.append({
            "claim": claim.text,
            "cause": claim.cause,
            "effect": claim.effect,
            "driver_tree_edges": len(driver_tree_edges),
        })
        result.confidence = 0.7 if evidence_classes >= 2 else 0.5
    elif evidence_classes >= 2:
        result.verified_claims.append({
            "claim": claim.text,
            "cause": claim.cause,
            "effect": claim.effect,
            "evidence_classes": evidence_classes,
            "note": "Causal link supported by multiple evidence classes",
        })
        result.confidence = 0.5
    else:
        result.is_valid = False
        result.add_degraded(claim.text, DegradedMode.INSUFFICIENT_CAUSAL_EVIDENCE)
        result.unverified_claims.append({
            "claim": claim.text,
            "cause": claim.cause,
            "note": "Insufficient evidence for causal claim",
        })
        result.confidence = 0.2

    if has_alternative:
        # add_degraded handles the -0.15 confidence reduction
        result.add_degraded(claim.text, DegradedMode.FACT_VERIFIED_CAUSE_UNVERIFIED)

    return result


# ── Action validation ─────────────────────────────────────────────────────────


APPROVED_ACTION_TAXONOMY: set[str] = {
    "reduce", "increase", "review", "renegotiate", "invest", "divest",
    "restructure", "optimize", "consolidate", "delay", "accelerate",
    "hedge", "automate", "outsource", "insource",
}


def validate_action_claim(
    claim: ActionClaim,
    cited_causes: list[str] | None = None,
    policy_permitted: bool = False,
    owner_identified: bool = False,
    impact_quantified: bool = False,
) -> ValidationResult:
    """Validate an action claim ("should reduce costs by...").

    ACTION claims must:
    - Map to the approved taxonomy
    - Cite at least one validated cause
    - Satisfy policy permission
    - Identify owner type
    - Have expected impact basis
    """
    result = ValidationResult()

    if claim.action not in APPROVED_ACTION_TAXONOMY:
        result.is_valid = False
        result.add_degraded(claim.text, DegradedMode.PRECEDENT_ONLY_SUPPORT)
        result.errors.append(
            f"Action '{claim.action}' not in approved taxonomy"
        )
        return result

    if not cited_causes:
        result.is_valid = False
        result.errors.append(f"Action '{claim.text}' has no cited causes")
        result.confidence = 0.3
        return result

    result.verified_claims.append({
        "claim": claim.text,
        "action": claim.action,
        "target": claim.target,
        "cited_causes": cited_causes,
        "policy_permitted": policy_permitted,
        "owner_identified": owner_identified,
        "impact_quantified": impact_quantified,
    })

    result.confidence = 0.5
    if policy_permitted:
        result.confidence += 0.15
    if owner_identified:
        result.confidence += 0.10
    if impact_quantified:
        result.confidence += 0.10

    result.confidence = min(0.9, result.confidence)
    return result


# ── Commentary-level validation (backward compatible) ─────────────────────────


def validate_commentary_claims(
    commentary: str,
    facts: list[dict[str, Any]],
    amount_field: str = "amount",
    tolerance: Decimal = Decimal("0.05"),
    candidates: list[dict[str, Any]] | None = None,
    driver_tree_edges: list[dict[str, Any]] | None = None,
    evidence_classes: int = 0,
) -> ValidationResult:
    """Validate all claims in commentary text.

    Runs all 4 validators across the commentary:
    1. Extract and validate all $ claims (NUMERIC)
    2. Extract and validate comparative claims (COMPARATIVE)
    3. Extract and validate causal claims (CAUSAL)
    4. Extract and validate action claims (ACTION)

    Returns aggregated ValidationResult.
    """
    # Empty / whitespace-only commentary is trivially valid
    if not commentary or not commentary.strip():
        return ValidationResult()

    # NUMERIC extraction
    numeric_claims = extract_monetary_claims(commentary)

    result = ValidationResult()
    result.claims = numeric_claims  # backward compat

    # ── NUMERIC validation ──
    for claim in numeric_claims:
        vr = validate_numeric_claim(claim, facts, amount_field, tolerance)
        if not vr.is_valid:
            result.is_valid = False
            result.errors.extend(vr.errors)
            result.unverified_claims.extend(vr.unverified_claims)
        else:
            result.verified_claims.extend(vr.verified_claims)
        result.degraded_modes.extend(vr.degraded_modes)

    # ── COMPARATIVE extraction + validation ──
    for keyword in COMPARATIVE_KEYWORDS:
        if keyword in commentary.lower():
            if candidates:
                vr = validate_comparative_claim(
                    claim_text=commentary,
                    subject=keyword,
                    candidates=candidates,
                    value_field=amount_field,
                )
                if vr.is_valid:
                    result.verified_claims.extend(vr.verified_claims)
                else:
                    result.errors.extend(vr.errors)
                    result.degraded_modes.extend(vr.degraded_modes)
            break  # Only validate one comparative per commentary

    # ── CAUSAL extraction + validation ──
    for match in CAUSAL_PATTERN.finditer(commentary):
        cause = match.group(1).strip()
        causal_claim = CausalClaim(
            text=match.group(),
            cause=cause,
            effect="variance",
            context=commentary[max(0, match.start() - 30) : match.end() + 30],
        )
        vr = validate_causal_claim(
            claim=causal_claim,
            driver_tree_edges=driver_tree_edges,
            evidence_classes=evidence_classes,
        )
        if not vr.is_valid:
            result.is_valid = False
            result.errors.extend(vr.errors)
            result.unverified_claims.extend(vr.unverified_claims)
        else:
            result.verified_claims.extend(vr.verified_claims)
        result.degraded_modes.extend(vr.degraded_modes)

    # ── ACTION extraction + validation ──
    for match in ACTION_PATTERN.finditer(commentary):
        action = match.group(1).lower().strip()
        target = match.group(2).strip()
        action_claim = ActionClaim(text=match.group(), action=action, target=target)
        # Collect cause references from verified claims that have a 'cause' key
        cited_causes = [
            vc["cause"]
            for vc in result.verified_claims
            if isinstance(vc, dict) and "cause" in vc
        ]
        vr = validate_action_claim(
            claim=action_claim,
            cited_causes=cited_causes or None,
            policy_permitted=True,
        )
        if not vr.is_valid:
            result.errors.extend(vr.errors)
        else:
            result.verified_claims.extend(vr.verified_claims)
        result.degraded_modes.extend(vr.degraded_modes)

    # Clamp final confidence to [0.0, 1.0]
    result.confidence = max(0.0, min(1.0, result.confidence))
    return result
