"""EvidenceLookup tool — typed request → typed result via EvidenceRegistry."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from agents.authority.claims import AgentCapability
from agents.authority.evidence import AuthorityError, EvidenceReference
from agents.runtime.context import RuntimeContext


@dataclass(frozen=True)
class ToolFailure:
    """Typed failure for investigation tools."""

    code: str
    detail: str


@dataclass(frozen=True)
class EvidenceLookupRequest:
    """Typed request for evidence lookup — capability-bound, registry-resolved."""

    capability: AgentCapability
    situation_id: str
    company_id: str
    now: datetime
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        """Validate typed envelope at construction."""
        if self.capability is not AgentCapability.READ:
            raise AuthorityError("EvidenceLookup requires READ capability.")
        if not isinstance(self.situation_id, str) or not self.situation_id.strip():
            raise AuthorityError("situation_id must be a non-blank string.")
        if self.company_id != "meridian":
            raise AuthorityError("company_id must be meridian.")
        if self.now.tzinfo is None or self.now.utcoffset() is None:
            raise AuthorityError("now must be timezone-aware.")
        if not isinstance(self.evidence_ids, tuple):
            raise AuthorityError("evidence_ids must be a tuple.")
        for eid in self.evidence_ids:
            if not isinstance(eid, str) or not eid.strip():
                raise AuthorityError("evidence_ids item must be non-blank string.")
        if len(self.evidence_ids) == 0:
            raise AuthorityError("evidence_ids must be non-empty.")


@dataclass(frozen=True)
class EvidenceLookupResult:
    """Typed result — success carries HMAC-bound refs, failure carries code."""

    success: bool
    evidence_refs: tuple[EvidenceReference, ...] | None
    failure: ToolFailure | None
    provenance: str | None

    def __post_init__(self) -> None:
        """Validate result shape."""
        if self.success:
            if self.evidence_refs is None or self.failure is not None:
                raise AuthorityError("Success must carry evidence_refs and no failure.")
        else:
            if self.evidence_refs is not None or self.failure is None:
                raise AuthorityError("Failure must carry failure and no evidence_refs.")


def evidence_lookup(
    request: EvidenceLookupRequest,
    *,
    context: RuntimeContext,
) -> EvidenceLookupResult:
    """Evidence lookup via deterministic context — no external access.

    Obtains ``registry``, ``boundary``, ``now``, ``situation_id`` and
    ``company_id`` from the already-validated ``RuntimeContext``. The
    registry/boundary are exactly those bound to the context — a
    caller-supplied rogue registry/boundary cannot be injected. Checks
    capability, situation scope, and registry authority (HMAC +
    freshness). Returns typed success or typed failure; security
    violations raise.
    """
    # Context is factory-bound; registry/boundary/now/situation/company
    # are the deterministic authority already bound to the context.
    registry = context.registry
    boundary = context.boundary
    # Request must be bound to the same deterministic context.
    if request.situation_id != context.situation_id:
        return EvidenceLookupResult(
            success=False,
            evidence_refs=None,
            failure=ToolFailure(
                code="SCOPE_MISMATCH",
                detail=f"situation {request.situation_id!r} != context {context.situation_id!r}",
            ),
            provenance=None,
        )
    if request.company_id != context.company_id:
        return EvidenceLookupResult(
            success=False,
            evidence_refs=None,
            failure=ToolFailure(
                code="SCOPE_MISMATCH",
                detail=f"company {request.company_id!r} != context {context.company_id!r}",
            ),
            provenance=None,
        )
    if request.now != context.now:
        return EvidenceLookupResult(
            success=False,
            evidence_refs=None,
            failure=ToolFailure(
                code="SCOPE_MISMATCH",
                detail="request now != context now — wall-clock or stale context",
            ),
            provenance=None,
        )
    # Capability gate — P7-01 boundary.
    boundary.attempt(request.capability.value)
    # Registry authority — each id must be known, accessible, HMAC-valid, fresh.
    refs: list[EvidenceReference] = []
    for eid in request.evidence_ids:
        # No direct external access — only registry.
        try:
            ref = registry.create_reference(eid)
        except AuthorityError as exc:
            # Map registry exceptions to typed failure.
            if "Unknown" in str(exc):
                return EvidenceLookupResult(
                    success=False,
                    evidence_refs=None,
                    failure=ToolFailure(code="MISSING_EVIDENCE", detail=str(exc)),
                    provenance=None,
                )
            if "Inaccessible" in str(exc):
                return EvidenceLookupResult(
                    success=False,
                    evidence_refs=None,
                    failure=ToolFailure(code="INACCESSIBLE_EVIDENCE", detail=str(exc)),
                    provenance=None,
                )
            return EvidenceLookupResult(
                success=False,
                evidence_refs=None,
                failure=ToolFailure(code="REGISTRY_ERROR", detail=str(exc)),
                provenance=None,
            )
        # HMAC + freshness check.
        try:
            registry.validate_reference(ref, request.now)
        except AuthorityError as exc:
            msg = str(exc).lower()
            if "stale" in msg:
                return EvidenceLookupResult(
                    success=False,
                    evidence_refs=None,
                    failure=ToolFailure(code="STALE_EVIDENCE", detail=str(exc)),
                    provenance=None,
                )
            if "not issued" in msg or "mismatch" in msg:
                return EvidenceLookupResult(
                    success=False,
                    evidence_refs=None,
                    failure=ToolFailure(code="ROGUE_EVIDENCE", detail=str(exc)),
                    provenance=None,
                )
            return EvidenceLookupResult(
                success=False,
                evidence_refs=None,
                failure=ToolFailure(code="REGISTRY_ERROR", detail=str(exc)),
                provenance=None,
            )
        refs.append(ref)

    # No hidden writes, no mutation, no authoritative verdict.
    # Success carries HMAC-bound refs with provenance from registry.
    provenance = refs[0].provenance if refs else None
    return EvidenceLookupResult(
        success=True,
        evidence_refs=tuple(refs),
        failure=None,
        provenance=provenance,
    )
