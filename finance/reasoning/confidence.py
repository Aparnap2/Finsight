"""Deterministic confidence scoring for reasoning assertions.

Confidence is computed exclusively from deterministic metadata:

- **source reliability** — how trustworthy each evidence source type is;
- **agreement across evidence** — do independent evidence items concur on
  a common value?
- **materiality** — is the claim's magnitude significant relative to a
  threshold?

The existing deterministic confidence utilities in
``shared.utils.confidence`` are reused as the base fact confidence; the
evidence-level factors above modulate it. Every public function returns a
``Decimal`` in [0, 1] — monetary/confidence values are never ``float``.
"""

from __future__ import annotations

from decimal import Decimal

from finance.evidence.models import EvidenceItem
from shared.models.assertions import Assertion
from shared.utils.confidence import compute_deterministic_confidence

_ZERO = Decimal("0")
_ONE = Decimal("1")
_HALF = Decimal("0.5")
_NEUTRAL = Decimal("0.5")

# Source type -> reliability weight. Deterministic, versioned table;
# unknown source types fall back to the neutral weight.
SOURCE_RELIABILITY: dict[str, Decimal] = {
    "financial_fact": Decimal("0.95"),
    "variance": Decimal("0.90"),
    "gl": Decimal("0.90"),
    "kpi": Decimal("0.85"),
    "transaction": Decimal("0.85"),
    "operational_metric": Decimal("0.80"),
    "headcount": Decimal("0.80"),
    "driver": Decimal("0.75"),
    "policy_doc": Decimal("0.70"),
    "precedent": Decimal("0.55"),
    "manual": Decimal("0.55"),
}
DEFAULT_RELIABILITY = Decimal("0.50")

# Evidence confidence string -> numeric quality proxy (0..1) used to
# derive the base fact confidence from evidence-level metadata.
_EVIDENCE_CONFIDENCE_QUALITY: dict[str, float] = {
    "high": 0.9,
    "medium": 0.7,
    "low": 0.4,
    "tentative": 0.25,
}


def _clamp(value: Decimal) -> Decimal:
    """Clamp a confidence value to [0, 1]."""
    return max(_ZERO, min(_ONE, value))


def source_reliability(source_type: str) -> Decimal:
    """Return the reliability weight for a source type (0..1)."""
    return SOURCE_RELIABILITY.get(source_type, DEFAULT_RELIABILITY)


def average_source_reliability(evidence: list[EvidenceItem]) -> Decimal:
    """Mean reliability weight across the given evidence items.

    Returns the neutral weight when no evidence is provided.
    """
    if not evidence:
        return DEFAULT_RELIABILITY
    total = sum((source_reliability(ev.source_type) for ev in evidence), _ZERO)
    return total / Decimal(len(evidence))


def agreement_score(evidence: list[EvidenceItem]) -> Decimal:
    """Fraction of evidence items that agree on a common value.

    Agreement is measured against the most frequently occurring
    ``source_value``, normalised by the total number of evidence items
    carrying a numeric value. Items without a numeric value are ignored.
    Returns 1.0 when no comparable values exist (no disagreement
    detected). Examples: two agreeing items -> 1.0; a 50/50 split -> 0.5.
    """
    counts: dict[Decimal, int] = {}
    for ev in evidence:
        if ev.source_value is not None:
            counts[ev.source_value] = counts.get(ev.source_value, 0) + 1
    if not counts:
        return _ONE
    most_common = max(counts.values())
    total = sum(counts.values())
    return Decimal(most_common) / Decimal(total)


def materiality_factor(value: Decimal | None, threshold: Decimal) -> Decimal:
    """Scale factor for the magnitude of a claim's value.

    Returns 1.0 when ``|value| >= threshold`` (material), a linear ramp
    below the threshold (floored at 0.1), and a neutral 0.5 when no
    value is available. A threshold <= 0 treats every value as material.
    """
    if value is None:
        return _NEUTRAL
    magnitude = abs(value)
    if threshold <= 0 or magnitude >= threshold:
        return _ONE
    return max(Decimal("0.1"), magnitude / threshold)


def _evidence_quality(evidence: list[EvidenceItem]) -> float:
    """Average numeric quality proxy for the given evidence items."""
    if not evidence:
        return 0.5
    total = sum(
        _EVIDENCE_CONFIDENCE_QUALITY.get(ev.confidence, 0.5) for ev in evidence
    )
    return total / len(evidence)


def score_assertion(
    assertion: Assertion,
    evidence: list[EvidenceItem],
    materiality_threshold: Decimal = Decimal("10000"),
) -> Decimal:
    """Compute a ``Decimal`` confidence in [0, 1] for an assertion.

    The base is the existing deterministic fact confidence
    (``shared.utils.confidence.compute_deterministic_confidence``) fed
    with evidence-derived metadata. The base is then blended with the
    evidence-level factors: source reliability, agreement, materiality.

    Args:
        assertion: The typed assertion being scored.
        evidence: The evidence items supporting the assertion.
        materiality_threshold: Threshold above which a value is material.

    Returns:
        A ``Decimal`` in [0, 1].
    """
    count = len(evidence)
    source_count = len({ev.source_id for ev in evidence})
    quality = _evidence_quality(evidence)

    base_float = compute_deterministic_confidence(
        assertion=assertion,
        evidence_count=count,
        source_count=source_count,
        coverage_pct=quality,
        quality_score=quality,
        is_directly_recomputable=True,
    )
    base = Decimal(str(base_float))

    reliability = average_source_reliability(evidence)
    agreement = agreement_score(evidence)
    materiality = materiality_factor(assertion.value, materiality_threshold)

    # Base carries 40% of the weight; each evidence factor carries 20%.
    score = (
        Decimal("0.4") * base
        + Decimal("0.2") * reliability
        + Decimal("0.2") * agreement
        + Decimal("0.2") * materiality
    )
    return _clamp(score)
