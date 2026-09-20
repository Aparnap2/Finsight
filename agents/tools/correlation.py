"""Correlation tool — advisory correlation over registry-issued refs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from agents.authority.claims import AgentCapability, correlate_evidence
from agents.authority.evidence import AuthorityError
from agents.runtime.context import RuntimeContext
from agents.tools.evidence_lookup import ToolFailure


@dataclass(frozen=True)
class CorrelationRequest:
    """Typed request for correlation — capability-bound, registry-resolved."""

    capability: AgentCapability
    situation_id: str
    company_id: str
    now: datetime
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        """Validate typed envelope at construction."""
        if self.capability is not AgentCapability.CORRELATE:
            raise AuthorityError("Correlation requires CORRELATE capability.")
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
class CorrelationResult:
    """Typed result — advisory correlation, never authoritative fact."""

    success: bool
    summary: str | None
    failure: ToolFailure | None

    def __post_init__(self) -> None:
        """Validate result shape."""
        if self.success:
            if self.summary is None or self.failure is not None:
                raise AuthorityError("Success must carry summary and no failure.")
            # Advisory only — must not contain authoritative markers.
            for marker in ("VERIFIED", "FACT", "status", "verdict"):
                if marker in self.summary:
                    raise AuthorityError(f"Correlation summary must not contain {marker!r}.")
        else:
            if self.summary is not None or self.failure is None:
                raise AuthorityError("Failure must carry failure and no summary.")


def correlate(
    request: CorrelationRequest,
    *,
    context: RuntimeContext,
) -> CorrelationResult:
    """Correlation via deterministic context — advisory only.

    Obtains ``registry``, ``boundary``, ``now`` and scope from the
    already-validated ``RuntimeContext``. No silent resolution of
    contradictory evidence; the tool returns an advisory correlation
    that preserves ambiguity.
    """
    registry = context.registry
    boundary = context.boundary
    # Request must be bound to the same deterministic context.
    if request.situation_id != context.situation_id:
        return CorrelationResult(
            success=False,
            summary=None,
            failure=ToolFailure(
                code="SCOPE_MISMATCH",
                detail=f"situation {request.situation_id!r} != context {context.situation_id!r}",
            ),
        )
    if request.company_id != context.company_id:
        return CorrelationResult(
            success=False,
            summary=None,
            failure=ToolFailure(
                code="SCOPE_MISMATCH",
                detail=f"company {request.company_id!r} != context {context.company_id!r}",
            ),
        )
    if request.now != context.now:
        return CorrelationResult(
            success=False,
            summary=None,
            failure=ToolFailure(
                code="SCOPE_MISMATCH",
                detail="request now != context now",
            ),
        )
    boundary.attempt(request.capability.value)
    refs = []
    for eid in request.evidence_ids:
        try:
            ref = registry.create_reference(eid)
        except AuthorityError as exc:
            if "Unknown" in str(exc):
                return CorrelationResult(
                    success=False,
                    summary=None,
                    failure=ToolFailure(code="MISSING_EVIDENCE", detail=str(exc)),
                )
            if "Inaccessible" in str(exc):
                return CorrelationResult(
                    success=False,
                    summary=None,
                    failure=ToolFailure(code="INACCESSIBLE_EVIDENCE", detail=str(exc)),
                )
            return CorrelationResult(
                success=False,
                summary=None,
                failure=ToolFailure(code="REGISTRY_ERROR", detail=str(exc)),
            )
        try:
            registry.validate_reference(ref, request.now)
        except AuthorityError as exc:
            msg = str(exc).lower()
            if "stale" in msg:
                return CorrelationResult(
                    success=False,
                    summary=None,
                    failure=ToolFailure(code="STALE_EVIDENCE", detail=str(exc)),
                )
            if "not issued" in msg or "mismatch" in msg:
                return CorrelationResult(
                    success=False,
                    summary=None,
                    failure=ToolFailure(code="ROGUE_EVIDENCE", detail=str(exc)),
                )
            return CorrelationResult(
                success=False,
                summary=None,
                failure=ToolFailure(code="REGISTRY_ERROR", detail=str(exc)),
            )
        refs.append(ref)

    # Advisory correlation — never authoritative fact.
    try:
        summary = correlate_evidence(refs, now=request.now)
    except AuthorityError as exc:
        return CorrelationResult(
            success=False,
            summary=None,
            failure=ToolFailure(code="CORRELATION_ERROR", detail=str(exc)),
        )
    return CorrelationResult(success=True, summary=summary, failure=None)
