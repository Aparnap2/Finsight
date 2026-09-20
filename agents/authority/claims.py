"""Advisory agent outputs plus the single authority choke point.

Everything here is non-authoritative: observations, claims, hypotheses,
and proposals cite evidence but never decide. Capabilities
(``AgentCapability``) and advisory proposal intents are separate
namespaces — a proposal's ``proposal_type`` is never a capability verb.
The only path to a validated evidence citation runs through
``EvidenceRegistry``; raw caller metadata never becomes authority.
Model outputs enter solely as plain mappings passed into the
``validate_*`` functions; no LLM calls, no network, and no
wall-clock reads live in this module.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from agents.authority.evidence import AuthorityError, EvidenceReference, EvidenceRegistry

logger = logging.getLogger(__name__)

_SMUGGLED_CLAIM_KEYS = frozenset({"status", "verdict", "decision"})
"""Keys that would smuggle authoritative state through a claim."""

_SMUGGLED_PROPOSAL_KEYS = frozenset({"status", "amount", "verdict", "decision"})
"""Keys that would smuggle authoritative state through a proposal."""

_ADVISORY_PROPOSAL_TYPES: frozenset[str] = frozenset(
    {
        "request_investigation",
        "flag_ambiguity",
        "summarize_correlation",
        "explain_reasoning",
        "advisory_note",
    }
)
"""Advisory, domain-neutral proposal intents — never financial execution."""


class AgentCapability(StrEnum):
    """Deterministic-plane capabilities the agent runtime may exercise."""

    READ = "read"
    CORRELATE = "correlate"
    HYPOTHESIZE = "hypothesize"
    PROPOSE = "propose"
    EXPLAIN = "explain"


def _require_non_blank(value: object, field_name: str) -> str:
    """Return value when a non-blank string, else raise AuthorityError."""
    if not isinstance(value, str) or not value.strip():
        raise AuthorityError(f"{field_name} must be a non-blank string.")
    return value


def _parse_time(value: object, field_name: str) -> datetime:
    """Parse caller-supplied time (datetime or ISO string) as tz-aware."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise AuthorityError(f"{field_name} is not valid ISO-8601.") from exc
    else:
        raise AuthorityError(f"{field_name} must be an ISO string or datetime.")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AuthorityError(f"{field_name} must be timezone-aware.")
    return parsed


def _parse_confidence(value: object) -> float:
    """Parse confidence as a float in [0, 1); absolute certainty is refused."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AuthorityError("confidence must be a number.")
    confidence = float(value)
    if not 0.0 <= confidence < 1.0:
        raise AuthorityError("confidence must lie in [0, 1); 1.0 is unsupported.")
    return confidence


def _parse_ref(
    raw: object,
    *,
    now: datetime,
    registry: EvidenceRegistry,
) -> EvidenceReference:
    """Parse one evidence pointer dict via the deterministic registry.

    The dict must contain ``evidence_id``; any caller-asserted
    ``source_id / captured_at / digest / provenance / ttl_seconds``
    that disagrees with the registry's authoritative record is treated
    as fabrication and refused. A validated, HMAC-bound reference is
    then issued by the registry and checked for freshness.
    """
    if not isinstance(raw, Mapping):
        raise AuthorityError("Each evidence ref must be a mapping.")
    evidence_id = _require_non_blank(raw.get("evidence_id"), "evidence_id")
    rec = registry.get_record(evidence_id)
    if not registry.is_accessible(evidence_id):
        raise AuthorityError(f"Inaccessible evidence {evidence_id!r}.")
    # Any caller-supplied metadata must match the authoritative record.
    for field_name in ("source_id", "digest", "provenance", "ttl_seconds"):
        if field_name in raw and raw[field_name] != getattr(rec, field_name):
            raise AuthorityError(
                f"Evidence {evidence_id!r} metadata mismatch on {field_name!r}."
            )
    if "captured_at" in raw:
        supplied = _parse_time(raw["captured_at"], "captured_at")
        if supplied != rec.captured_at:
            raise AuthorityError(
                f"Evidence {evidence_id!r} captured_at mismatch — possible fabrication."
            )
    if raw.get("digest_mismatch") is True:
        raise AuthorityError(f"Evidence {evidence_id!r} failed integrity check.")
    ref = registry.create_reference(evidence_id)
    registry.validate_reference(ref, now)
    return ref


def _parse_refs(
    raw: object,
    *,
    now: datetime,
    registry: EvidenceRegistry,
) -> tuple[EvidenceReference, ...]:
    """Parse a non-empty evidence ref sequence via the registry."""
    if not isinstance(raw, (list, tuple)) or len(raw) == 0:
        raise AuthorityError("evidence_refs must be a non-empty sequence.")
    return tuple(
        _parse_ref(item, now=now, registry=registry) for item in raw
    )


def _check_refs_fresh(
    refs: tuple[EvidenceReference, ...], moment: datetime, owner: str
) -> None:
    """Raise AuthorityError when refs are empty, unissued, or stale at moment."""
    if len(refs) == 0:
        raise AuthorityError(f"{owner} requires at least one evidence ref.")
    for ref in refs:
        if not getattr(ref, "_token", ""):
            raise AuthorityError(
                f"{owner} cites an unissued EvidenceReference — not from deterministic accessor."
            )
        ref.require_fresh(moment)


@dataclass(frozen=True)
class AgentObservation:
    """An advisory observation grounded in one or more evidence pointers."""

    text: str
    evidence_refs: tuple[EvidenceReference, ...]
    observed_at: datetime

    def __post_init__(self) -> None:
        """Validate text, timestamp, and ref issuance + freshness."""
        _require_non_blank(self.text, "text")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise AuthorityError("observed_at must be timezone-aware.")
        _check_refs_fresh(self.evidence_refs, self.observed_at, "AgentObservation")

    @property
    def tier(self) -> str:
        """Return the advisory tier label for observations."""
        return "observation"


@dataclass(frozen=True)
class AgentClaim:
    """An advisory claim: evidence refs plus sub-certain confidence.

    The constructor rejects empty ref sets, unissued refs, stale refs
    (evaluated at ``created_at``, a caller-supplied timestamp), and
    absolute certainty. No promotion helper to facts exists by design.
    """

    text: str
    confidence: float
    evidence_refs: tuple[EvidenceReference, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        """Validate text, confidence, timestamp, and ref issuance + freshness."""
        _require_non_blank(self.text, "text")
        if isinstance(self.confidence, bool) or not isinstance(
            self.confidence, (int, float)
        ):
            raise AuthorityError("confidence must be a number.")
        if not 0.0 <= float(self.confidence) < 1.0:
            raise AuthorityError("confidence must lie in [0, 1); 1.0 is unsupported.")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise AuthorityError("created_at must be timezone-aware.")
        _check_refs_fresh(self.evidence_refs, self.created_at, "AgentClaim")

    @property
    def tier(self) -> str:
        """Return the advisory tier label for claims."""
        return "claim"


@dataclass(frozen=True)
class AgentHypothesis:
    """An advisory hypothesis: a candidate explanation carrying uncertainty."""

    text: str
    evidence_refs: tuple[EvidenceReference, ...]
    uncertainty: str
    created_at: datetime

    def __post_init__(self) -> None:
        """Validate text, uncertainty, timestamp, and ref issuance + freshness."""
        _require_non_blank(self.text, "text")
        _require_non_blank(self.uncertainty, "uncertainty")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise AuthorityError("created_at must be timezone-aware.")
        _check_refs_fresh(self.evidence_refs, self.created_at, "AgentHypothesis")


@dataclass(frozen=True)
class AgentProposal:
    """An advisory proposal: typed advisory intent plus refs and uncertainty.

    ``proposal_type`` is an advisory intent (e.g. ``request_investigation``),
    never a capability verb and never a financial execution intent. No
    ``to_authoritative``-style escape exists.
    """

    proposal_type: str
    evidence_refs: tuple[EvidenceReference, ...]
    uncertainty: str
    rationale: str
    created_at: datetime
    target: str | None = None

    def __post_init__(self) -> None:
        """Validate advisory intent, text fields, timestamp, and freshness."""
        _require_non_blank(self.proposal_type, "proposal_type")
        if self.proposal_type not in _ADVISORY_PROPOSAL_TYPES:
            raise AuthorityError(
                f"Proposal type {self.proposal_type!r} is not an advisory intent."
            )
        # Capability verbs must never appear as business intent.
        if self.proposal_type in {c.value for c in AgentCapability}:
            raise AuthorityError(
                f"Proposal type {self.proposal_type!r} is a capability verb, not a business intent."
            )
        _require_non_blank(self.uncertainty, "uncertainty")
        _require_non_blank(self.rationale, "rationale")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise AuthorityError("created_at must be timezone-aware.")
        if self.target is not None:
            _require_non_blank(self.target, "target")
        _check_refs_fresh(self.evidence_refs, self.created_at, "AgentProposal")

    def to_dict(self) -> dict[str, Any]:
        """Return the advisory payload (never carries authoritative status)."""
        payload: dict[str, Any] = {
            "proposal_type": self.proposal_type,
            "evidence_ids": [ref.evidence_id for ref in self.evidence_refs],
            "uncertainty": self.uncertainty,
            "rationale": self.rationale,
            "created_at": self.created_at.isoformat(),
            "tier": "proposal",
        }
        if self.target is not None:
            payload["target"] = self.target
        return payload


@dataclass
class AuthorityBoundary:
    """Single choke point separating advisory capabilities from forbidden ones."""

    ALLOWED_CAPABILITIES: frozenset[AgentCapability] = frozenset(
        {
            AgentCapability.READ,
            AgentCapability.CORRELATE,
            AgentCapability.HYPOTHESIZE,
            AgentCapability.PROPOSE,
            AgentCapability.EXPLAIN,
        }
    )
    """Advisory capabilities that succeed (read-only, non-authoritative)."""

    # Back-compat alias — tests historically reference ALLOWED_ACTIONS.
    ALLOWED_ACTIONS: frozenset[str] = frozenset(
        {c.value for c in ALLOWED_CAPABILITIES}
    )

    DENIED_ACTIONS: frozenset[str] = frozenset(
        {
            "mutate_financial_state",
            "execute_financial_correction",
            "approve",
            "reject_authorize",
            "establish_verdict",
            "declare_verification_successful",
            "close_case",
            "modify_authoritative_evidence",
            "fabricate_missing_evidence",
            "convert_unsupported_claim_into_fact",
            "use_stale_evidence_as_current",
            "bypass_deterministic_policy",
            "bypass_p6_verification",
        }
    )
    """The thirteen forbidden verbs; each attempt raises with no side effect."""

    _allowed_log: list[str] = field(default_factory=list)
    """Record of granted advisory attempts (denials record nothing)."""

    def attempt(self, action: str) -> None:
        """Grant advisory capability verbs; raise AuthorityError for anything else."""
        # Proposal intents must not be granted as capabilities.
        if action in self.DENIED_ACTIONS or action not in {
            c.value for c in self.ALLOWED_CAPABILITIES
        }:
            raise AuthorityError(f"Action {action!r} is outside agent authority.")
        self._allowed_log.append(action)
        logger.debug("Authority granted (advisory): %s", action)

    def attempt_capability(self, capability: AgentCapability) -> None:
        """Grant a typed capability; wrapper around ``attempt``."""
        self.attempt(capability.value)

    def audit_log(self) -> tuple[str, ...]:
        """Return the granted-attempt log (denials leave it untouched)."""
        return tuple(self._allowed_log)


@dataclass(frozen=True)
class AmbiguityOutcome:
    """Result of an ambiguity check over candidate evidence values."""

    is_ambiguous: bool
    detail: str


def correlate_evidence(
    refs: Sequence[EvidenceReference], *, now: datetime
) -> str:
    """Summarise correlated pointers as an advisory, uncertain statement."""
    if len(refs) == 0:
        raise AuthorityError("correlate_evidence requires at least one ref.")
    for ref in refs:
        if not getattr(ref, "_token", ""):
            raise AuthorityError("correlate_evidence cites an unissued reference.")
        ref.require_fresh(now)
    joined = ", ".join(ref.evidence_id for ref in refs)
    return f"Advisory correlation (uncertain hypothesis, not a decision): {joined}."


def detect_ambiguity(values: Mapping[str, Sequence[str] | str]) -> AmbiguityOutcome:
    """Flag conflicting candidate values as ambiguous without resolving them."""
    for key, candidates in values.items():
        distinct = {candidates} if isinstance(candidates, str) else set(candidates)
        if len(distinct) > 1:
            return AmbiguityOutcome(
                is_ambiguous=True, detail=f"Ambiguous values for {key}: advisory only."
            )
    return AmbiguityOutcome(is_ambiguous=False, detail="No conflicting values found.")


def reason_over_evidence(claim: AgentClaim) -> str:
    """Render advisory reasoning over a claim, preserving uncertainty."""
    return (
        f"Advisory reasoning over uncertain hypothesis: {claim.text} "
        f"(confidence {claim.confidence}; not a fact, not verified)."
    )


def find_missing_info(
    *, present_ids: Sequence[str], required_ids: Sequence[str]
) -> tuple[str, ...]:
    """Report required source ids absent from the present set (never invent)."""
    present = set(present_ids)
    return tuple(item for item in required_ids if item not in present)


def explain_proposal(proposal: AgentProposal) -> str:
    """Render a human-facing advisory explanation without authority language."""
    return (
        f"This proposal ({proposal.proposal_type}) is advisory, not a decision. "
        f"Uncertain: {proposal.uncertainty} Rationale: {proposal.rationale}"
    )


def require_tool_result(
    *, tool_name: str, result: object, available: Mapping[str, bool]
) -> object:
    """Return the tool result, or raise when the tool is unavailable."""
    _require_non_blank(tool_name, "tool_name")
    if available.get(tool_name) is not True or result is None:
        raise AuthorityError(f"Tool {tool_name!r} is unavailable; will not guess.")
    return result


def require_model_output(*, output: object, model_available: bool) -> object:
    """Return the model output, or raise when the model is unavailable."""
    if not model_available or output is None:
        raise AuthorityError("Model output unavailable; will not fabricate.")
    return output


def validate_claim_dict(
    data: Mapping[str, Any],
    *,
    now: datetime,
    registry: EvidenceRegistry,
) -> AgentClaim:
    """Validate a plain-data claim payload into an advisory AgentClaim.

    Evidence refs are resolved through the deterministic ``registry`` —
    caller-supplied metadata never becomes authority. Any mismatch
    between caller-supplied fields and the registry's record is refused.
    """
    if not isinstance(data, Mapping):
        raise AuthorityError("Claim payload must be a mapping.")
    for smuggled in _SMUGGLED_CLAIM_KEYS:
        if smuggled in data:
            raise AuthorityError(f"Claim payload carries authoritative key {smuggled!r}.")
    # Adversarial fixtures below are examples of conflicting evidence that
    # must remain conflicting and not be collapsed into a flat claim.
    if data.get("claims_both") is True:
        raise AuthorityError("Claim payload is self-contradictory.")
    if "ambiguous_values" in data:
        raise AuthorityError("Ambiguous evidence cannot support a flat claim.")
    tool_values = data.get("tool_values")
    if isinstance(tool_values, Mapping) and len(set(tool_values.values())) > 1:
        raise AuthorityError("Contradictory tool data cannot support a claim.")
    for key in ("text", "confidence", "created_at", "evidence_refs"):
        if key not in data:
            raise AuthorityError(f"Claim payload is missing {key!r}.")
    text = _require_non_blank(data["text"], "text")
    confidence = _parse_confidence(data["confidence"])
    created_at = _parse_time(data["created_at"], "created_at")
    refs = _parse_refs(data["evidence_refs"], now=now, registry=registry)
    # Enforce freshness at creation time via registry as well.
    for ref in refs:
        registry.validate_reference(ref, created_at)
    return AgentClaim(
        text=text, confidence=confidence, evidence_refs=refs, created_at=created_at
    )


def validate_proposal_dict(
    data: Mapping[str, Any],
    *,
    now: datetime,
    registry: EvidenceRegistry,
    boundary: AuthorityBoundary | None = None,
) -> AgentProposal:
    """Validate a plain-data proposal payload into an advisory AgentProposal.

    ``proposal_type`` must be an advisory intent, never a capability verb
    or financial execution verb. Evidence refs are resolved through the
    deterministic ``registry``; smuggled authoritative keys are refused.
    """
    if not isinstance(data, Mapping):
        raise AuthorityError("Proposal payload must be a mapping.")
    for smuggled in _SMUGGLED_PROPOSAL_KEYS:
        if smuggled in data:
            raise AuthorityError(
                f"Proposal payload smuggles authoritative key {smuggled!r}."
            )
    for key in ("proposal_type", "uncertainty", "rationale", "created_at", "evidence_refs"):
        if key not in data:
            # Back-compat: older tests used ``action`` as proposal_type.
            if key == "proposal_type" and "action" in data:
                continue
            raise AuthorityError(f"Proposal payload is missing {key!r}.")
    raw_type = data.get("proposal_type", data.get("action"))
    proposal_type = _require_non_blank(raw_type, "proposal_type")
    if proposal_type not in _ADVISORY_PROPOSAL_TYPES:
        raise AuthorityError(f"Proposal type {proposal_type!r} is not an advisory intent.")
    if proposal_type in {c.value for c in AgentCapability}:
        raise AuthorityError(
            f"Proposal type {proposal_type!r} is a capability verb, not a business intent."
        )
    if boundary is not None:
        # Proposing is a capability; check the boundary allows PROPOSE.
        boundary.attempt(AgentCapability.PROPOSE.value)
    uncertainty = _require_non_blank(data["uncertainty"], "uncertainty")
    rationale = _require_non_blank(data["rationale"], "rationale")
    created_at = _parse_time(data["created_at"], "created_at")
    target = data.get("target")
    if target is not None:
        _require_non_blank(target, "target")
    refs = _parse_refs(data["evidence_refs"], now=now, registry=registry)
    for ref in refs:
        registry.validate_reference(ref, created_at)
    return AgentProposal(
        proposal_type=proposal_type,
        evidence_refs=refs,
        uncertainty=uncertainty,
        rationale=rationale,
        created_at=created_at,
        target=target if isinstance(target, str) else None,
    )


__all__ = [
    "AgentCapability",
    "AgentClaim",
    "AgentHypothesis",
    "AgentObservation",
    "AgentProposal",
    "AmbiguityOutcome",
    "AuthorityBoundary",
    "correlate_evidence",
    "detect_ambiguity",
    "explain_proposal",
    "find_missing_info",
    "reason_over_evidence",
    "require_model_output",
    "require_tool_result",
    "validate_claim_dict",
    "validate_proposal_dict",
]
