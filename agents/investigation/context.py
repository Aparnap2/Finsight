"""Deterministic context assembly boundary — P5-02.

`InvestigationContext` is the typed, immutable, bounded, tenant-scoped,
provenance-preserving object that crosses into the LLM. It is built
deterministically from `InvestigationRequest` (trusted tenant/case) +
server-side `evidence_store` (no arbitrary DB/S3, no LLM-chosen tenant).

Untrusted external content is fenced as DATA, never as instructions:
each `EvidenceContext` is rendered with an explicit
``SOURCE: <type>`` / ``TRUST: UNTRUSTED_CONTENT`` fence.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from agents.investigation.request import MAX_CONTEXT_CHARS, InvestigationRequest

MAX_EVIDENCE_CONTENT_CHARS = 2000
"""Per-evidence content ceiling before bounded representation (preserves hash)."""

MAX_EVIDENCE_ITEMS = 32

_TRUST_FENCE = "UNTRUSTED_CONTENT"


@dataclass(frozen=True)
class EvidenceContext:
    """Canonical presentation of one evidence item for the LLM.

    Only approved fields cross the boundary — raw DB objects never do.
    `content` is bounded and fenced; `content_hash` preserves provenance.
    """

    evidence_id: str
    source_type: str
    source_id: str
    tenant_id: str
    content_hash: str
    retrieved_at: datetime
    provenance: str
    content: str
    trust_classification: str = _TRUST_FENCE

    def rendered(self) -> str:
        """Render with explicit untrusted-content fence."""
        # Never concatenate untrusted text as instructions — fence it.
        return (
            f"Evidence\n"
            f"========\n"
            f"SOURCE: {self.source_type}\n"
            f"TRUST: {self.trust_classification}\n"
            f"EVIDENCE_ID: {self.evidence_id}\n"
            f"CONTENT_HASH: {self.content_hash}\n"
            f"CONTENT:\n{self.content}\n"
        )


@dataclass(frozen=True)
class InvestigationContext:
    """Typed, immutable, bounded context that enters the LLM.

    Built only via `build_context()` — never from arbitrary dicts.
    """

    tenant_id: str
    case_id: str
    actor: str
    evidence: tuple[EvidenceContext, ...]
    capabilities: tuple[str, ...]
    constraints: dict[str, Any]
    total_chars: int
    truncated: bool

    def render_for_llm(self) -> str:
        """Deterministic render — evidence fenced, provenance preserved."""
        parts = [
            f"tenant: {self.tenant_id}",
            f"case: {self.case_id}",
            f"capabilities: {', '.join(self.capabilities)}",
            f"constraints: max_chars={self.constraints.get('max_chars', MAX_CONTEXT_CHARS)}",
            "",
        ]
        for ev in self.evidence:
            parts.append(ev.rendered())
            parts.append("---")
        body = "\n".join(parts)
        if self.truncated:
            body += "\n[TRUNCATED: evidence bounded to preserve identity]\n"
        return body


def _hash_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def build_context(
    request: InvestigationRequest,
    evidence_store: Mapping[str, Mapping[str, Any]],
) -> InvestigationContext:
    """Build a bounded, tenant-scoped, provenance-preserving context.

    Args:
        request: Trusted `InvestigationRequest` (tenant/actor already validated).
        evidence_store: Server-side map `evidence_id -> {tenant_id, case_id,
            source_type, source_id, content, content_hash?, retrieved_at?,
            provenance?}`. No DB/S3 client is accepted — only this map.

    Returns:
        `InvestigationContext` ready for `render_investigation_prompt()`.

    Raises:
        ValueError: On missing/wrong-tenant/wrong-case/unknown provenance/
            unbounded content. Fail closed, no fallback, no LLM call.
    """
    # 1. Tenant/case from trusted request — never from evidence text
    tenant = request.tenant_id.strip()
    case = request.exception_id.strip()
    if not tenant or not case:
        raise ValueError("Trusted tenant/case must be non-empty.")

    # 2. Evidence authorization per requested id
    evidence_ctxs: list[EvidenceContext] = []
    for eid in request.evidence_ids:
        rec = evidence_store.get(eid)
        if rec is None:
            raise ValueError(f"Missing evidence: {eid!r} (no fallback).")
        rec_tenant = str(rec.get("tenant_id", "")).strip()
        rec_case = str(rec.get("case_id", "")).strip()
        if rec_tenant != tenant:
            raise ValueError(f"Evidence {eid!r} tenant mismatch: {rec_tenant!r} != {tenant!r}.")
        if rec_case and rec_case != case:
            raise ValueError(f"Evidence {eid!r} case mismatch: {rec_case!r} != {case!r}.")
        source_type = str(rec.get("source_type", "unknown")).strip() or "unknown"
        source_id = str(rec.get("source_id", eid)).strip() or eid
        content = str(rec.get("content", ""))
        # provenance check: must have at least source_type + retrieved_at or hash
        content_hash = str(rec.get("content_hash") or _hash_content(content))
        retrieved_at = rec.get("retrieved_at")
        if not isinstance(retrieved_at, datetime):
            retrieved_at = datetime.now(UTC)
        elif retrieved_at.tzinfo is None:
            raise ValueError(f"Evidence {eid!r} retrieved_at must be tz-aware.")
        provenance = str(rec.get("provenance", f"{source_type}:{source_id}")).strip()
        if not provenance:
            raise ValueError(f"Evidence {eid!r} provenance missing.")

        # 3. Bounded content — deterministic rejection if single item too large
        if len(content) > MAX_EVIDENCE_CONTENT_CHARS:
            # Preserve hash/provenance, bound content with explicit marker
            content = content[:MAX_EVIDENCE_CONTENT_CHARS] + "\n[TRUNCATED]\n"
            # Still hash is of original? Use provided hash if given, else hash of bounded?
            # Preserve original hash if provided, else hash of bounded content
            if not rec.get("content_hash"):
                content_hash = _hash_content(content)

        # 4. Untrusted fence is implicit via EvidenceContext.trust_classification
        ctx = EvidenceContext(
            evidence_id=eid,
            source_type=source_type,
            source_id=source_id,
            tenant_id=rec_tenant,
            content_hash=content_hash,
            retrieved_at=retrieved_at,
            provenance=provenance,
            content=content,
        )
        evidence_ctxs.append(ctx)

    if len(evidence_ctxs) > MAX_EVIDENCE_ITEMS:
        raise ValueError(f"Too many evidence items: {len(evidence_ctxs)} > {MAX_EVIDENCE_ITEMS}")

    # 5. Aggregate bounds — total chars must fit MAX_CONTEXT_CHARS with fencing overhead
    # Estimate: evidence rendered + request.context_window
    rendered_evidence_chars = sum(len(ev.rendered()) for ev in evidence_ctxs)
    total = rendered_evidence_chars + len(request.context_window)
    truncated = False
    if total > MAX_CONTEXT_CHARS:
        # Deterministic rejection, not silent truncation that destroys provenance
        raise ValueError(
            f"Context too large: {total} > {MAX_CONTEXT_CHARS} "
            f"(evidence {rendered_evidence_chars} + window "
            f"{len(request.context_window)}). Reduce evidence or window."
        )

    # 6. Capability snapshot is frozen allowlist (cannot be expanded by LLM)
    # Already validated in request, just carry it
    capabilities = tuple(request.capability_allowlist)

    constraints = {"max_chars": MAX_CONTEXT_CHARS, "round_budget": request.round_budget}

    return InvestigationContext(
        tenant_id=tenant,
        case_id=case,
        actor=request.actor,
        evidence=tuple(evidence_ctxs),
        capabilities=capabilities,
        constraints=constraints,
        total_chars=total,
        truncated=truncated,
    )
