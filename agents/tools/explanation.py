"""Explanation tool — handoff → advisory explanation, scope-bound."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from agents.authority.claims import AgentCapability
from agents.authority.evidence import AuthorityError
from agents.runtime.context import RuntimeContext
from agents.runtime.handoff import RuntimeHandoff
from agents.tools.evidence_lookup import ToolFailure


@dataclass(frozen=True)
class ExplanationRequest:
    """Typed request for explanation — capability-bound, handoff-scoped."""

    capability: AgentCapability
    situation_id: str
    company_id: str
    now: datetime
    handoff: RuntimeHandoff

    def __post_init__(self) -> None:
        """Validate typed envelope at construction."""
        if self.capability is not AgentCapability.EXPLAIN:
            raise AuthorityError("Explanation requires EXPLAIN capability.")
        if not isinstance(self.situation_id, str) or not self.situation_id.strip():
            raise AuthorityError("situation_id must be a non-blank string.")
        if self.company_id != "meridian":
            raise AuthorityError("company_id must be meridian.")
        if self.now.tzinfo is None or self.now.utcoffset() is None:
            raise AuthorityError("now must be timezone-aware.")
        if not isinstance(self.handoff, RuntimeHandoff):
            raise AuthorityError("handoff must be a RuntimeHandoff.")


@dataclass(frozen=True)
class ExplanationResult:
    """Typed result — advisory explanation."""

    success: bool
    explanation: str | None
    failure: ToolFailure | None

    def __post_init__(self) -> None:
        """Validate result shape."""
        if self.success:
            if self.explanation is None or self.failure is not None:
                raise AuthorityError("Success must carry explanation and no failure.")
            if "VERIFIED" in self.explanation or "FACT" in self.explanation:
                raise AuthorityError("Explanation must not contain authoritative marker.")
        else:
            if self.explanation is not None or self.failure is None:
                raise AuthorityError("Failure must carry failure and no explanation.")


def explain(
    request: ExplanationRequest,
    *,
    context: RuntimeContext,
) -> ExplanationResult:
    """Explanation via handoff — scope-bound, advisory only.

    Obtains ``boundary`` and scope from the already-validated
    ``RuntimeContext``; a caller-supplied rogue boundary cannot be
    injected.
    """
    boundary = context.boundary
    # Request must be bound to the same deterministic context.
    if request.situation_id != context.situation_id:
        return ExplanationResult(
            success=False,
            explanation=None,
            failure=ToolFailure(
                code="SCOPE_MISMATCH",
                detail=(
                    f"request situation {request.situation_id!r} "
                    f"!= context {context.situation_id!r}"
                ),
            ),
        )
    if request.company_id != context.company_id:
        return ExplanationResult(
            success=False,
            explanation=None,
            failure=ToolFailure(
                code="SCOPE_MISMATCH",
                detail=f"request company {request.company_id!r} != context {context.company_id!r}",
            ),
        )
    if request.now != context.now:
        return ExplanationResult(
            success=False,
            explanation=None,
            failure=ToolFailure(
                code="SCOPE_MISMATCH",
                detail="request now != context now",
            ),
        )
    boundary.attempt(request.capability.value)
    # Situation scope must match handoff's situation — model cannot redefine.
    if request.situation_id != request.handoff.situation_id:
        return ExplanationResult(
            success=False,
            explanation=None,
            failure=ToolFailure(
                code="SCOPE_MISMATCH",
                detail=(
                    f"situation {request.situation_id!r} "
                    f"!= handoff {request.handoff.situation_id!r}"
                ),
            ),
        )
    if request.company_id != request.handoff.company_id:
        return ExplanationResult(
            success=False,
            explanation=None,
            failure=ToolFailure(
                code="SCOPE_MISMATCH",
                detail=f"company {request.company_id!r} != handoff {request.handoff.company_id!r}",
            ),
        )
    # No wall-clock, no external access — just render the handoff's
    # advisory proposal via the frozen P7-01 helper.
    from agents.authority.claims import explain_proposal

    try:
        text = explain_proposal(request.handoff.proposal)
    except Exception as exc:
        return ExplanationResult(
            success=False,
            explanation=None,
            failure=ToolFailure(code="EXPLANATION_ERROR", detail=str(exc)),
        )
    return ExplanationResult(success=True, explanation=text, failure=None)
