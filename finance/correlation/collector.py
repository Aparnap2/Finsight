"""Deterministic scoped collection with caps and uniform refusal.

Every fact and context ref is checked against the run scope
(tenant + batch) before conversion; any mismatch raises the same
uniform message so callers learn nothing about what exists
elsewhere. Over-cap sources keep the first-N by canonical sort with
a dropped count; identical inputs always yield byte-identical
registries.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from finance.correlation.converter import (
    ContextRef,
    ConvertedEvidence,
    context_to_evidence,
    evidence_id_for,
    fact_to_evidence,
)
from finance.evidence.models import EvidenceItem

SCOPE_REFUSED_MESSAGE = "evidence out of scope: refused (no existence oracle)."
"""Uniform refusal for every scope violation (no oracle)."""

_AUTHORITY_KEYWORDS = frozenset(
    {
        "ledger",
        "posting",
        "posted",
        "confirm",
        "confirms",
        "accounting",
        "authoritative",
        "quickbooks",
    }
)
"""Words that mark a non-authoritative claim as authority-spoofing."""


class DroppedSource(BaseModel):
    """One over-cap source with its deterministic dropped count."""

    model_config = ConfigDict(frozen=True, strict=True)

    source_type: str
    """The capped source group."""

    dropped: int
    """Items beyond the cap (>= 0)."""


class CollectedEvidence(BaseModel):
    """One deterministic collection: ids, items, contents, markers."""

    evidence_ids: tuple[str, ...]
    """Globally sorted evidence ids."""

    items: dict[str, EvidenceItem]
    """Evidence id to EvidenceItem (insertion follows id sort)."""

    contents: dict[str, str]
    """Evidence id to full content (tamper-check bytes)."""

    markers: tuple[str, ...] = ()
    """Machine markers (CAP_EXCEEDED, AUTHORITY_STRIPPED, conflicts)."""

    dropped: tuple[DroppedSource, ...] = ()
    """Per-source dropped counts (empty when nothing capped)."""

    model_config = ConfigDict(frozen=True, strict=True)

    def to_registry(self) -> dict[str, EvidenceItem]:
        """Return the evidence id to item mapping."""
        return dict(self.items)

    def to_contents(self) -> dict[str, str]:
        """Return the evidence id to full-content mapping."""
        return dict(self.contents)


def _check_scope(
    *,
    tenant_id: str,
    batch_id: str,
    company_id: str,
    item_batch_id: str,
) -> None:
    """Refuse out-of-scope inputs with the uniform message."""
    if company_id != tenant_id or item_batch_id != batch_id:
        raise ValueError(SCOPE_REFUSED_MESSAGE)


def _authority_stripped(source_type: str, text: str) -> bool:
    """Detect non-authoritative text claiming authoritative weight."""
    if source_type in ("razorpay", "quickbooks", "cobol_legacy", "sheets"):
        return False
    lowered = text.lower()
    return any(word in lowered for word in _AUTHORITY_KEYWORDS)


def collect_evidence(
    *,
    tenant_id: str,
    case_id: str,
    batch_id: str,
    facts: list[object],
    context_refs: list[ContextRef],
    per_source_cap: int = 32,
    total_cap: int = 32,
) -> CollectedEvidence:
    """Collect and convert one deterministic evidence registry.

    Args:
        tenant_id: Run scope tenant (facts must carry it as company).
        case_id: Owning case (accepted for package binding).
        batch_id: Collection window (facts/refs must carry it).
        facts: Canonical facts to convert (any order; sorted by id).
        context_refs: Context references to convert as UNTRUSTED DATA.
        per_source_cap: Max items kept per source group.
        total_cap: Max items kept overall.

    Returns:
        The collected evidence with sorted ids, markers, and drops.

    Raises:
        ValueError: Uniform refusal on any scope violation.
    """
    converted: list[ConvertedEvidence] = []
    for fact in facts:
        company = getattr(getattr(fact, "provenance", None), "company_id", None)
        window = getattr(fact, "batch_id", None)
        _check_scope(
            tenant_id=tenant_id,
            batch_id=batch_id,
            company_id=company if isinstance(company, str) else "",
            item_batch_id=window if isinstance(window, str) else "",
        )
        converted.append(fact_to_evidence(fact, case_id=case_id))
    for ref in context_refs:
        _check_scope(
            tenant_id=tenant_id,
            batch_id=batch_id,
            company_id=ref.provenance.company_id,
            item_batch_id=ref.batch_id,
        )
        converted.append(
            context_to_evidence(
                source_type=ref.source_type,
                source_id=ref.source_id,
                text=ref.text,
                provenance=ref.provenance,
                case_id=case_id,
            )
        )
    grouped: dict[str, list[ConvertedEvidence]] = {}
    for conv in converted:
        grouped.setdefault(conv.item.source_type, []).append(conv)
    markers: list[str] = []
    dropped: list[DroppedSource] = []
    kept: list[ConvertedEvidence] = []
    for source_type in sorted(grouped):
        group = sorted(grouped[source_type], key=lambda c: c.item.source_id)
        if len(group) > per_source_cap:
            dropped.append(
                DroppedSource(
                    source_type=source_type, dropped=len(group) - per_source_cap
                )
            )
            markers.append(
                f"CAP_EXCEEDED {source_type}: dropped "
                f"{len(group) - per_source_cap} over cap {per_source_cap}"
            )
        kept.extend(group[:per_source_cap])
    for conv in kept:
        text = conv.content_full
        if _authority_stripped(conv.item.source_type, text):
            markers.append(
                f"AUTHORITY_STRIPPED {conv.item.source_type}:"
                f"{conv.item.source_id}: non-authoritative claim "
                "stripped to CONTEXT"
            )
    pairs = sorted(
        ((evidence_id_for(conv), conv) for conv in kept), key=lambda pair: pair[0]
    )
    if len(pairs) > total_cap:
        markers.append(
            f"CAP_EXCEEDED total: dropped {len(pairs) - total_cap} "
            f"over cap {total_cap}"
        )
        pairs = pairs[:total_cap]
    ids = tuple(eid for eid, _ in pairs)
    items = {eid: conv.item for eid, conv in pairs}
    contents = {eid: conv.content_full for eid, conv in pairs}
    conflicts = _conflict_strings(items, contents)
    return CollectedEvidence(
        evidence_ids=ids,
        items=items,
        contents=contents,
        markers=tuple(markers + conflicts),
        dropped=tuple(dropped),
    )


def _conflict_strings(
    items: dict[str, EvidenceItem], contents: dict[str, str]
) -> list[str]:
    """Render conflict markers for same-source diverging content."""
    from finance.correlation.chain import detect_conflicts

    return [
        f"CONFLICTING_EVIDENCE {','.join(marker.ids)}: "
        f"{len(marker.ids)} variants preserved"
        for marker in detect_conflicts(items, contents)
    ]
