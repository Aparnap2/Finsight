"""Fact-to-evidence conversion: the only provenance-shape bridge.

Maps ``FactProvenance`` (strict, hash/time inside the envelope) onto
``EvidenceProvenance`` (triple) plus the sibling ``EvidenceItem``
lineage fields, verbatim and without recomputation: tenant from
company, hash copied (never recomputed, so truncation cannot break
the ladder), time copied (never normalized). Source money becomes
``source_value``; context text never manufactures amounts.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from finance.evidence.models import EvidenceItem, EvidenceProvenance
from finance.facts.books import BooksFact
from finance.facts.expected import ExpectedFact
from finance.facts.legacy import LegacyFact
from finance.facts.provenance import FactProvenance
from finance.facts.provider import ProviderNetFact

MAX_STORED_CHARS = 2000
"""Store-row content budget (matches the P4 evidence boundary)."""

_TRUNCATION_SUFFIX = "\n[TRUNCATED]\n"
"""Deterministic overflow marker; the full hash is preserved."""

_AUTHORITATIVE_SOURCES = frozenset({"razorpay", "quickbooks", "cobol_legacy"})
"""Sources whose records carry authoritative weight."""

_ADVISORY_SOURCES = frozenset({"sheets"})
"""Sources that inform but never decide."""


def trust_class_for(source: str) -> str:
    """Return the trust class for a source system (never upgrades).

    Authoritative systems keep their weight; sheets is advisory;
    everything else (gmail, slack, unknown) is context. Unknown
    sources default to ``CONTEXT`` — fail-closed, never promoted.
    """
    if source in _AUTHORITATIVE_SOURCES:
        return "AUTHORITATIVE"
    if source in _ADVISORY_SOURCES:
        return "ADVISORY"
    return "CONTEXT"


def _require_provenance(provenance: FactProvenance) -> None:
    """Reject blank provenance triples before any evidence exists."""
    if (
        not provenance.adapter.strip()
        or not provenance.endpoint.strip()
        or not provenance.correlation_id.strip()
    ):
        raise ValueError(
            "PROVENANCE_MISSING: adapter/endpoint/correlation_id "
            "must all be non-blank."
        )


def truncate_content(text: str) -> str:
    """Truncate store-bound content deterministically (hash untouched)."""
    if len(text) <= MAX_STORED_CHARS:
        return text
    return text[:MAX_STORED_CHARS] + _TRUNCATION_SUFFIX


class ContextRef(BaseModel):
    """One non-fact context reference (gmail/slack/notes are DATA)."""

    model_config = ConfigDict(frozen=True, strict=True)

    source_type: str
    """Origin system, e.g. gmail, slack, sheets-note."""

    source_id: str
    """Stable id within the origin system."""

    text: str
    """Raw text; carried verbatim, never parsed for amounts."""

    provenance: FactProvenance
    """Ingest identity; blank triples are refused at conversion."""

    batch_id: str
    """Collection window this reference belongs to."""


class ConvertedEvidence(BaseModel):
    """One converted unit: item + trust + full and stored content."""

    item: EvidenceItem
    """The evidence item (hash/time copied verbatim from the fact)."""

    trust_class: str
    """AUTHORITATIVE, ADVISORY, or CONTEXT (never upgraded)."""

    content_full: str
    """Complete rendered text; the tamper-check bytes."""

    content_stored: str
    """Truncated store text; the full hash is preserved regardless."""

    model_config = ConfigDict(frozen=True, strict=True)


def _evidence_id(source_type: str, source_id: str, content_full: str) -> str:
    """Derive a stable evidence id binding source to exact content."""
    from hashlib import sha256

    short = sha256(content_full.encode("utf-8")).hexdigest()[:12]
    return f"{source_type}:{source_id}:{short}"


def _render_fact_content(
    source_type: str,
    source_id: str,
    batch_id: str,
    body: str,
    trust_class: str,
) -> str:
    """Render deterministic full content for one converted fact."""
    return f"{source_type} {source_id} batch {batch_id} [{trust_class}]: {body}"


def fact_to_evidence(fact: object, *, case_id: str) -> ConvertedEvidence:
    """Convert one canonical fact into evidence (verbatim lineage).

    Args:
        fact: One of ExpectedFact, ProviderNetFact, BooksFact,
            LegacyFact (anything else is refused fail-closed).
        case_id: Owning case, recorded by the collector (accepted here
            for signature stability across fact and context paths).

    Returns:
        The converted unit with trust class and both contents.

    Raises:
        ValueError: On blank provenance or an unknown fact shape.
    """
    del case_id
    if isinstance(fact, ExpectedFact):
        return _convert(
            source_type="sheets",
            source_id=fact.fact_id,
            batch_id=fact.batch_id,
            body=f"expected total={fact.expected_total} INR (advisory)",
            amount=fact.expected_total,
            provenance=fact.provenance,
        )
    if isinstance(fact, ProviderNetFact):
        return _convert(
            source_type="razorpay",
            source_id=fact.fact_id,
            batch_id=fact.batch_id,
            body=(
                f"gross={fact.gross} fee={fact.fee} refund={fact.refund} "
                f"adjustment={fact.adjustment} pending={fact.pending} "
                f"net={fact.net} INR"
            ),
            amount=fact.gross,
            provenance=fact.provenance,
        )
    if isinstance(fact, BooksFact):
        extra = ""
        if fact.booked_fee is not None:
            extra += f" booked_fee={fact.booked_fee}"
        if fact.duplicate_key is not None:
            extra += f" duplicate_key={fact.duplicate_key}"
        return _convert(
            source_type="quickbooks",
            source_id=fact.fact_id,
            batch_id=fact.batch_id,
            body=(
                f"period={fact.period} open={fact.period_open} "
                f"total={fact.qb_total} INR{extra}"
            ),
            amount=fact.qb_total,
            provenance=fact.provenance,
        )
    if isinstance(fact, LegacyFact):
        return _convert(
            source_type="cobol_legacy",
            source_id=fact.fact_id,
            batch_id=fact.batch_id,
            body=(
                f"accepted={fact.accepted_total} "
                f"rejected={fact.rejected_total} "
                f"reason={fact.rejected_reason or '-'} "
                f"account={fact.account_code or '-'} INR"
            ),
            amount=(
                fact.rejected_total
                if fact.rejected_total != 0
                else fact.accepted_total
            ),
            provenance=fact.provenance,
        )
    raise ValueError(
        f"unknown fact shape for evidence conversion: {type(fact).__name__}."
    )


def _convert(
    *,
    source_type: str,
    source_id: str,
    batch_id: str,
    body: str,
    amount: Decimal,
    provenance: FactProvenance,
) -> ConvertedEvidence:
    """Build one converted unit from rendered parts."""
    _require_provenance(provenance)
    trust_class = trust_class_for(source_type)
    content_full = _render_fact_content(
        source_type, source_id, batch_id, body, trust_class
    )
    return ConvertedEvidence(
        item=EvidenceItem(
            claim=content_full,
            source_type=source_type,
            source_id=source_id,
            source_value=amount,
            tenant_id=provenance.company_id,
            content_hash=provenance.content_hash,
            retrieved_at=provenance.retrieved_at,
            provenance=EvidenceProvenance(
                adapter=provenance.adapter,
                endpoint=provenance.endpoint,
                correlation_id=provenance.correlation_id,
            ),
        ),
        trust_class=trust_class,
        content_full=content_full,
        content_stored=truncate_content(content_full),
    )


def context_to_evidence(
    *,
    source_type: str,
    source_id: str,
    text: str,
    provenance: FactProvenance,
    case_id: str,
) -> ConvertedEvidence:
    """Convert one context reference into UNTRUSTED DATA evidence.

    Context text is carried verbatim and never yields ``source_value``,
    so evidence wording can never manufacture a financial fact.

    Args:
        source_type: Origin system (gmail, slack, sheets-note, ...).
        source_id: Stable id within the origin system.
        text: Raw text, preserved exactly.
        provenance: Ingest identity (blank triples refused).
        case_id: Owning case (accepted for signature stability).

    Returns:
        The converted unit marked CONTEXT (never upgraded).

    Raises:
        ValueError: On blank provenance (PROVENANCE_MISSING).
    """
    del case_id
    _require_provenance(provenance)
    content_full = f"{source_type} {source_id} UNTRUSTED DATA: {text}"
    return ConvertedEvidence(
        item=EvidenceItem(
            claim=content_full,
            source_type=source_type,
            source_id=source_id,
            source_value=None,
            tenant_id=provenance.company_id,
            content_hash=provenance.content_hash,
            retrieved_at=provenance.retrieved_at,
            provenance=EvidenceProvenance(
                adapter=provenance.adapter,
                endpoint=provenance.endpoint,
                correlation_id=provenance.correlation_id,
            ),
        ),
        trust_class="CONTEXT",
        content_full=content_full,
        content_stored=truncate_content(content_full),
    )


def evidence_id_for(converted: ConvertedEvidence) -> str:
    """Derive the stable evidence id for one converted unit."""
    return _evidence_id(
        converted.item.source_type,
        converted.item.source_id,
        converted.content_full,
    )
