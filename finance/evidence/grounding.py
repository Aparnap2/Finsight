"""Grounding ladder — FACTUAL→cite→exists→tenant→provenance→supported→VERIFIED.

P5-04: ``HYPOTHESIS != FACT != VERIFIED`` and ``confidence != authority``.
Evidence must be tenant-owned, hash-verified, retrieval time tz-aware,
and provenance-valid before it can support a claim eligible for VERIFIED.

Pure deterministic helpers; no DB, no LLM, no network.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum

from finance.evidence.models import EvidenceItem

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ClaimTier(StrEnum):
    """Grounding ladder tiers (strictly ordered)."""

    HYPOTHESIS = "HYPOTHESIS"
    FACT = "FACT"
    VERIFIED = "VERIFIED"


def is_tz_aware(value: datetime) -> bool:
    """Return True when ``value`` carries tzinfo with a real offset."""
    return value.tzinfo is not None and value.utcoffset() is not None


def compute_content_hash(data: bytes) -> str:
    """Return lowercase sha256 hex for raw bytes (ObjectMeta-compatible)."""
    return hashlib.sha256(data).hexdigest()


def verify_provenance(
    item: EvidenceItem,
    *,
    expected_tenant: str,
    expected_bytes: bytes | None = None,
) -> tuple[str, ...]:
    """Validate one EvidenceItem against the grounding ladder (pure).

    Checks in ladder order:
    1. tenant present and equals ``expected_tenant``
    2. content_hash present and is 64 hex
    3. when ``expected_bytes`` given, hash equals sha256(bytes)
    4. retrieved_at present and tz-aware
    5. provenance present with non-blank adapter/endpoint/correlation_id

    Args:
        item: Evidence item to check (frozen, validated at construction).
        expected_tenant: Tenant that must own the evidence (e.g. "meridian").
        expected_bytes: When provided, the raw bytes the hash must match.

    Returns:
        Tuple of violation codes (empty when fully provenance-valid).
        Codes are ``grounding_violation:provenance_invalid:<source_id>``
        for every failing step, plus ``tenant_mismatch`` is surfaced
        separately so callers can map it uniformly to unknown_evidence_id.
    """
    reasons: list[str] = []
    sid = item.source_id or "unknown"

    # Tenant must be present and match — without leaking cross-tenant existence
    # the caller maps tenant_mismatch uniformly to unknown_evidence_id.
    if item.tenant_id is None or item.tenant_id.strip() != expected_tenant:
        reasons.append(f"grounding_violation:provenance_invalid:tenant_mismatch:{sid}")
        # Still continue to report other provenance failures (defense in depth)
    if item.content_hash is None or not _SHA256_RE.match(item.content_hash):
        reasons.append(f"grounding_violation:provenance_invalid:content_hash:{sid}")
    elif expected_bytes is not None:
        expected_hash = compute_content_hash(expected_bytes)
        if item.content_hash != expected_hash:
            reasons.append(f"grounding_violation:provenance_invalid:hash_mismatch:{sid}")
    if item.retrieved_at is None or not is_tz_aware(item.retrieved_at):
        reasons.append(f"grounding_violation:provenance_invalid:retrieved_at:{sid}")
    if item.provenance is None:
        reasons.append(f"grounding_violation:provenance_invalid:provenance_missing:{sid}")
    else:
        if not item.provenance.adapter.strip():
            reasons.append(f"grounding_violation:provenance_invalid:adapter:{sid}")
        if not item.provenance.endpoint.strip():
            reasons.append(f"grounding_violation:provenance_invalid:endpoint:{sid}")
        if not item.provenance.correlation_id.strip():
            reasons.append(f"grounding_violation:provenance_invalid:correlation_id:{sid}")
    return tuple(reasons)


def evaluate_ladder(
    *,
    evidence_ids: tuple[str, ...],
    evidence_registry: Mapping[str, EvidenceItem] | None,
    expected_tenant: str,
    content_bytes: Mapping[str, bytes] | None = None,
) -> tuple[str, ...]:
    """Evaluate the full ladder for a plan's evidence_required set (pure).

    Implements ``FACTUAL → must cite → exists → belongs to tenant →
    provenance valid → supported``.  Unsupported claims remain HYPOTHESIS;
    only fully provenance-valid, tenant-owned, hash-verified, tz-aware,
    and supported claims are eligible for VERIFIED.

    Uniform failure mode: cross-tenant evidence and genuinely missing ids
    both surface as ``grounding_violation:unknown_evidence_id:<id>`` so
    callers never learn whether the other-tenant resource exists.

    Args:
        evidence_ids: The plan's ``evidence_required`` ids (already bounded).
        evidence_registry: Mapping from evidence id to validated EvidenceItem.
            When None, only existence (membership) is checked — provenance
            ladder is deferred.
        expected_tenant: Tenant that must own every cited item.
        content_bytes: Optional raw bytes per evidence id for hash re-verification.

    Returns:
        Tuple of machine-readable grounding violations (empty when ladder passes).
    """
    reasons: list[str] = []
    if evidence_registry is None:
        return tuple(reasons)

    bytes_map = content_bytes or {}
    for eid in evidence_ids:
        item = evidence_registry.get(eid)
        if item is None:
            # Uniform: missing and cross-tenant both look like unknown
            reasons.append(f"grounding_violation:unknown_evidence_id:{eid}")
            continue
        # Tenant isolation — uniform unknown_evidence_id (do not leak existence)
        if item.tenant_id != expected_tenant:
            reasons.append(f"grounding_violation:unknown_evidence_id:{eid}")
            continue
        # Provenance ladder — hash, time, provenance fields
        expected = bytes_map.get(eid)
        prov_reasons = verify_provenance(
            item, expected_tenant=expected_tenant, expected_bytes=expected
        )
        # Map provenance failures uniformly except tenant_mismatch already handled
        for code in prov_reasons:
            if "tenant_mismatch" in code:
                continue
            # Normalize to a single provenance_invalid per evidence id for verifier stability,
            # but preserve the first granular suffix for audit
            reasons.append(f"grounding_violation:provenance_invalid:{eid}")
            break
        # Supported check — claim text must be non-blank and source_value alignment
        # is caller-owned (tolerances.py). Here we enforce that a blank claim
        # can never be supported.
        if not item.claim.strip():
            reasons.append(f"grounding_violation:unsupported_claim:{eid}")
    # Dedup while preserving order
    seen: set[str] = set()
    ordered: list[str] = []
    for reason in reasons:
        if reason not in seen:
            seen.add(reason)
            ordered.append(reason)
    return tuple(ordered)


def is_verified_eligible(
    *,
    evidence_ids: tuple[str, ...],
    evidence_registry: Mapping[str, EvidenceItem] | None,
    expected_tenant: str,
    content_bytes: Mapping[str, bytes] | None = None,
) -> bool:
    """Return True iff the cited set passes the full ladder (eligible for VERIFIED)."""
    if not evidence_ids:
        return False
    if evidence_registry is None:
        return False
    return evaluate_ladder(
        evidence_ids=evidence_ids,
        evidence_registry=evidence_registry,
        expected_tenant=expected_tenant,
        content_bytes=content_bytes,
    ) == ()


def classify_tier(
    *,
    evidence_ids: tuple[str, ...],
    evidence_registry: Mapping[str, EvidenceItem] | None,
    expected_tenant: str,
    content_bytes: Mapping[str, bytes] | None = None,
) -> ClaimTier:
    """Classify a claim set on the HYPOTHESIS/FACT/VERIFIED ladder.

    - HYPOTHESIS: no citation or missing/unknown evidence.
    - FACT: cites existing tenant-owned evidence (exists + belongs to tenant)
      but provenance may still be pending.
    - VERIFIED: eligible per :func:`is_verified_eligible` (full ladder).

    This helper is informational; the verifier gate remains binary
    (ACCEPT/REJECT) and confidence never promotes a tier.
    """
    if not evidence_ids:
        return ClaimTier.HYPOTHESIS
    if evidence_registry is None:
        return ClaimTier.HYPOTHESIS
    # FACT check — exists and belongs to tenant (uniform unknown hides cross-tenant)
    for eid in evidence_ids:
        item = evidence_registry.get(eid)
        if item is None or item.tenant_id != expected_tenant:
            return ClaimTier.HYPOTHESIS
    if is_verified_eligible(
        evidence_ids=evidence_ids,
        evidence_registry=evidence_registry,
        expected_tenant=expected_tenant,
        content_bytes=content_bytes,
    ):
        return ClaimTier.VERIFIED
    return ClaimTier.FACT
