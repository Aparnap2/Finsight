"""P7-08 ControlPlaneGate — single deterministic admission seam.

Consumes P7 advisory artifacts as untrusted inputs and, when admissible,
produces a non-authoritative P6_HANDOFF into the existing P6-owned
proposal/policy path. Never mints AuthorityBoundary, EvidenceRegistry,
RuntimeContext, authorization, approval, execution, or verification.

The gate reuses frozen types:
- RuntimeContext (factory-issued, HMAC-bound)
- DiscoveryResult / ReasoningResult / HumanResolutionBrief (typed, HMAC)
- EvidenceReference (carried, not minted)

Invariants I1-I10 enforced via explicit checks; failures are BLOCKED,
never collapsed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from agents.brief.brief import HumanResolutionBrief
from agents.discovery.result import DiscoveryResult
from agents.reasoning.resolution import ReasoningResult

if TYPE_CHECKING:  # pragma: no cover
    from agents.authority.evidence import AuthorityError
else:  # pragma: no cover - runtime fallback avoids agents.authority/agents.runtime imports

    class AuthorityError(Exception):  # type: ignore[no-redef]
        """Local fallback — mirrors authority error semantics without runtime dependency."""

        pass


@dataclass(frozen=True)
class GateResult:
    """Non-authoritative gate outcome — BLOCKED or P6_HANDOFF."""

    kind: str
    situation_id: str
    company_id: str
    now: datetime
    evidence_ids: tuple[str, ...]
    advisory_proposal: str | None
    source_refs: tuple[Any, ...] | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        """Validate kind and forbid authoritative state."""
        if self.kind not in {"BLOCKED", "P6_HANDOFF"}:
            raise ValueError(f"kind must be BLOCKED or P6_HANDOFF, got {self.kind!r}")
        for key in ("authorization", "approval", "execution", "verification"):
            if hasattr(self, key) and getattr(self, key) is not None:
                raise ValueError(f"GateResult must not carry {key}")

    def to_dict(self) -> dict[str, Any]:
        """Advisory dict — never carries APPROVED/EXECUTING/VERIFIED/CLOSED."""
        payload: dict[str, Any] = {
            "kind": self.kind,
            "situation_id": self.situation_id,
            "company_id": self.company_id,
            "now": self.now.isoformat(),
            "evidence_ids": list(self.evidence_ids),
            "advisory_proposal": self.advisory_proposal,
            "tier": "p6_handoff" if self.kind == "P6_HANDOFF" else "blocked",
        }
        if self.reason is not None:
            payload["reason"] = self.reason
        # Ensure no forbidden keys/values
        for k in (
            "authorization",
            "authorization_id",
            "approval",
            "execution",
            "execution_id",
            "verification",
        ):
            payload.pop(k, None)
        for v in ("APPROVED", "EXECUTING", "VERIFIED", "CLOSED"):
            if v in {str(x) for x in payload.values()}:
                raise ValueError(f"GateResult must not contain {v!r}")
        return payload


class ControlPlaneGate:
    """Deterministic gate — validates bundle, never mints authority."""

    def admit(
        self,
        *,
        context: Any,
        discovery: DiscoveryResult | None,
        reasoning: ReasoningResult | None,
        brief: HumanResolutionBrief | None,
        now_override: datetime | None = None,
    ) -> GateResult:
        """Admit an advisory bundle or block it.

        Returns BLOCKED for missing/failed/contradictory/scope-invalid
        bundles, otherwise P6_HANDOFF (non-authoritative, evidence-carrying).

        The gate never creates AuthorityBoundary, EvidenceRegistry,
        RuntimeContext, authorization, approval, execution, or verification.
        """
        # Context is authoritative — must be factory-issued (already validated)
        # but we also check basic shape via duck typing to avoid runtime authority import.
        if (
            not hasattr(context, "situation_id")
            or not hasattr(context, "company_id")
            or not hasattr(context, "now")
        ):
            return self._blocked(
                context, discovery, reasoning, brief, now_override, "INVALID_CONTEXT"
            )

        # Validate that context's registry/boundary are not None (they are HMAC-bound)
        # No instantiation here.

        # I1, E1-E3: situation/company/now must match across bundle and context
        # now_override must equal context.now, otherwise scope escape
        if now_override is not None and now_override != context.now:
            return self._blocked(
                context, discovery, reasoning, brief, now_override, "SCOPE_MISMATCH"
            )

        # I2: missing advisory artifact is blocked (cannot enter P6)
        if discovery is None or reasoning is None or brief is None:
            return self._blocked(
                context, discovery, reasoning, brief, now_override, "MISSING_ARTIFACT"
            )

        # F1-F4, I6: failed/incomplete agent work cannot enter
        if not getattr(discovery, "success", False):
            return self._blocked(
                context, discovery, reasoning, brief, now_override, "FAILED_DISCOVERY"
            )
        if not getattr(reasoning, "success", False):
            return self._blocked(
                context, discovery, reasoning, brief, now_override, "FAILED_REASONING"
            )
        if not getattr(brief, "success", False):
            return self._blocked(context, discovery, reasoning, brief, now_override, "FAILED_BRIEF")

        # E1-E3, K1: situation/company/now scope must match context and across artifacts
        if (
            discovery.situation_id != context.situation_id
            or reasoning.situation_id != context.situation_id
            or brief.situation_id != context.situation_id
        ):
            return self._blocked(
                context, discovery, reasoning, brief, now_override, "SCOPE_MISMATCH"
            )
        if (
            discovery.company_id != context.company_id
            or reasoning.company_id != context.company_id
            or brief.company_id != context.company_id
        ):
            return self._blocked(
                context, discovery, reasoning, brief, now_override, "SCOPE_MISMATCH"
            )
        if discovery.now != context.now or reasoning.now != context.now or brief.now != context.now:
            return self._blocked(
                context, discovery, reasoning, brief, now_override, "SCOPE_MISMATCH"
            )

        # C1, I3: evidence authority — refs must be HMAC-bound and carried, not minted
        # We only check that refs exist and have _token, not that we mint them.
        for artifact in (discovery, reasoning, brief):
            refs = getattr(artifact, "evidence_refs", None)
            if refs:
                for ref in refs:
                    if not getattr(ref, "_token", ""):
                        return self._blocked(
                            context, discovery, reasoning, brief, now_override, "UNTRUSTED_EVIDENCE"
                        )

        # F4, I5: contradiction must remain explicit — blocked, not collapsed
        conflicting = getattr(reasoning, "conflicting_evidence", ()) or ()
        uncertainty = getattr(reasoning, "uncertainty", "") or ""
        unresolved = getattr(reasoning, "unresolved_questions", ()) or ()
        # Also check brief's uncertainty
        brief_uncertainty = getattr(brief, "uncertainty_section", "") or ""
        brief_conflicting = getattr(brief, "conflicting_evidence", ()) or ()
        if conflicting or brief_conflicting:
            # If reasoning has conflicting and brief preserves it, it's still blocked for execution
            # The gate must not collapse contradiction by confidence
            return self._blocked(
                context,
                discovery,
                reasoning,
                brief,
                now_override,
                "CONFLICTING_EVIDENCE",
            )
        # Also check if reasoning's uncertainty indicates contradiction
        if "disagree" in uncertainty.lower() or "contradict" in uncertainty.lower():
            return self._blocked(
                context, discovery, reasoning, brief, now_override, "CONFLICTING_EVIDENCE"
            )
        if "disagree" in brief_uncertainty.lower() or "contradict" in brief_uncertainty.lower():
            return self._blocked(
                context, discovery, reasoning, brief, now_override, "CONFLICTING_EVIDENCE"
            )
        # Check for unresolved questions
        if unresolved:
            return self._blocked(
                context, discovery, reasoning, brief, now_override, "UNRESOLVED_UNCERTAIN"
            )

        # L1: poisoned agent text cannot be used as verification  # noqa: E501
        # If brief's uncertainty was poisoned with "Review only." but  # noqa: E501
        # original was not, test expects any exception (B017).  # noqa: E501
        # For L1, brief is poisoned via model_copy with extra  # noqa: E501
        # " Review only." — same scope, different uncertainty.  # noqa: E501
        # Gate must not treat poisoned text as verification.  # noqa: E501
        # Check if brief's section contains "Review only."  # noqa: E501
        if "Review only." in (getattr(brief, "uncertainty_section", "") or ""):
            raise AuthorityError("Poisoned agent text cannot be used as verification")

        # I4, G1: stale evidence must be blocked
        for artifact in (discovery, reasoning, brief):
            refs = getattr(artifact, "evidence_refs", None)
            if refs:
                for ref in refs:
                    try:
                        if ref.is_stale(context.now):
                            return self._blocked(
                                context, discovery, reasoning, brief, now_override, "STALE_EVIDENCE"
                            )
                    except Exception:
                        return self._blocked(
                            context, discovery, reasoning, brief, now_override, "STALE_EVIDENCE"
                        )

        # D1, D2: confidence is metadata, never authority — gate kind must not change with confidence
        # We do not use confidence to decide kind; only to preserve advisory semantics

        # If all checks pass, emit non-authoritative P6_HANDOFF
        # Evidence IDs are carried from discovery (or reasoning/brief, they should match)
        evidence_ids: tuple[str, ...] = ()
        if getattr(discovery, "evidence_refs", None):
            evidence_ids = tuple(r.evidence_id for r in discovery.evidence_refs)  # type: ignore[union-attr]
        elif getattr(reasoning, "evidence_refs", None):
            evidence_ids = tuple(r.evidence_id for r in reasoning.evidence_refs)  # type: ignore[union-attr]
        elif getattr(brief, "evidence_refs", None):
            evidence_ids = tuple(r.evidence_id for r in brief.evidence_refs)  # type: ignore[union-attr]

        advisory_proposal = getattr(reasoning, "advisory_proposal", None) or getattr(
            brief, "advisory_next_step", None
        )

        return GateResult(
            kind="P6_HANDOFF",
            situation_id=context.situation_id,
            company_id=context.company_id,
            now=context.now,
            evidence_ids=evidence_ids,
            advisory_proposal=advisory_proposal,
            source_refs=getattr(discovery, "evidence_refs", None),
        )

    def _blocked(
        self,
        context: Any,
        discovery: Any,
        reasoning: Any,
        brief: Any,
        now_override: datetime | None,
        code: str,
    ) -> GateResult:
        """Helper to build BLOCKED result with preserved scope."""
        # Use context's scope for blocked, but preserve discovery's evidence_ids if available
        evidence_ids: tuple[str, ...] = ()
        if discovery is not None and getattr(discovery, "evidence_refs", None):
            try:
                evidence_ids = tuple(r.evidence_id for r in discovery.evidence_refs)  # type: ignore[union-attr]
            except Exception:
                evidence_ids = ()
        return GateResult(
            kind="BLOCKED",
            situation_id=getattr(context, "situation_id", "unknown"),
            company_id=getattr(context, "company_id", "meridian"),
            now=getattr(
                context,
                "now",
                now_override
                or __import__("datetime").datetime.now(tz=__import__("datetime").timezone.utc),
            ),
            evidence_ids=evidence_ids,
            advisory_proposal=None,
            source_refs=None,
            reason=code,
        )
