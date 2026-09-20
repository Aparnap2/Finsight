"""Advisory agent outputs plus the single authority choke point.

Everything here is non-authoritative: observations, claims, hypotheses,
and proposals cite evidence but never decide. The only path to action
names runs through :class:`AuthorityBoundary`, whose allow-list carries
the five advisory verbs and whose deny-list carries the thirteen
forbidden verbs. Model outputs enter solely as plain mappings passed
into the ``validate_*`` functions; no LLM calls, no network, and no
wall-clock reads live in this module.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from agents.authority.evidence import AuthorityError, EvidenceReference

logger = logging.getLogger(__name__)

_SMUGGLED_CLAIM_KEYS = frozenset({"status", "verdict", "decision"})
"""Keys that would smuggle authoritative state through a claim."""

_SMUGGLED_PROPOSAL_KEYS = frozenset({"status", "amount", "verdict", "decision"})
"""Keys that would smuggle authoritative state through a proposal."""


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
    known_source_ids: frozenset[str] | set[str],
    accessible_source_ids: frozenset[str] | set[str],
) -> EvidenceReference:
    """Parse one evidence pointer mapping, enforcing registry and freshness."""
    if not isinstance(raw, Mapping):
        raise AuthorityError("Each evidence ref must be a mapping.")
    source_id = _require_non_blank(raw.get("source_id"), "source_id")
    if source_id not in known_source_ids:
        raise AuthorityError(f"Unknown evidence source {source_id!r}.")
    if source_id not in accessible_source_ids:
        raise AuthorityError(f"Inaccessible evidence source {source_id!r}.")
    if raw.get("digest_mismatch") is True:
        raise AuthorityError(f"Evidence {source_id!r} failed integrity check.")
    captured_at = _parse_time(raw.get("captured_at"), "captured_at")
    ttl_raw = raw.get("ttl_seconds")
    if isinstance(ttl_raw, bool) or not isinstance(ttl_raw, int):
        raise AuthorityError("ttl_seconds must be an int.")
    ref = EvidenceReference(
        source_id=source_id, captured_at=captured_at, ttl_seconds=ttl_raw
    )
    ref.require_fresh(now)
    return ref


def _parse_refs(
    raw: object,
    *,
    now: datetime,
    known_source_ids: frozenset[str] | set[str],
    accessible_source_ids: frozenset[str] | set[str],
) -> tuple[EvidenceReference, ...]:
    """Parse a non-empty evidence ref sequence, ignoring inert extra keys."""
    if not isinstance(raw, (list, tuple)) or len(raw) == 0:
        raise AuthorityError("evidence_refs must be a non-empty sequence.")
    return tuple(
        _parse_ref(
            item,
            now=now,
            known_source_ids=known_source_ids,
            accessible_source_ids=accessible_source_ids,
        )
        for item in raw
    )


def _check_refs_fresh(
    refs: tuple[EvidenceReference, ...], moment: datetime, owner: str
) -> None:
    """Raise AuthorityError when refs are empty or any ref is stale at moment."""
    if len(refs) == 0:
        raise AuthorityError(f"{owner} requires at least one evidence ref.")
    for ref in refs:
        ref.require_fresh(moment)


@dataclass(frozen=True)
class AgentObservation:
    """An advisory observation grounded in one or more evidence pointers."""

    text: str
    evidence_refs: tuple[EvidenceReference, ...]
    observed_at: datetime

    def __post_init__(self) -> None:
        """Validate text, timestamp, and ref freshness."""
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

    The constructor rejects empty ref sets, stale refs (evaluated at
    ``created_at``, a caller-supplied timestamp), and absolute
    certainty. No promotion helper to facts exists by design.
    """

    text: str
    confidence: float
    evidence_refs: tuple[EvidenceReference, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        """Validate text, confidence, timestamp, and ref freshness."""
        _require_non_blank(self.text, "text")
        if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)):
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
        """Validate text, uncertainty, timestamp, and ref freshness."""
        _require_non_blank(self.text, "text")
        _require_non_blank(self.uncertainty, "uncertainty")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise AuthorityError("created_at must be timezone-aware.")
        _check_refs_fresh(self.evidence_refs, self.created_at, "AgentHypothesis")


@dataclass(frozen=True)
class AgentProposal:
    """An advisory proposal: typed advisory action plus refs and uncertainty.

    Carries no authoritative status field; any ``to_authoritative``-style
    escape is intentionally absent.
    """

    action: str
    evidence_refs: tuple[EvidenceReference, ...]
    uncertainty: str
    rationale: str
    created_at: datetime

    def __post_init__(self) -> None:
        """Validate advisory action, text fields, timestamp, and freshness."""
        _require_non_blank(self.action, "action")
        if self.action not in AuthorityBoundary.ALLOWED_ACTIONS:
            raise AuthorityError(f"Proposal action {self.action!r} is out of capability.")
        _require_non_blank(self.uncertainty, "uncertainty")
        _require_non_blank(self.rationale, "rationale")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise AuthorityError("created_at must be timezone-aware.")
        _check_refs_fresh(self.evidence_refs, self.created_at, "AgentProposal")

    def to_dict(self) -> dict[str, Any]:
        """Return the advisory payload (never carries authoritative status)."""
        return {
            "action": self.action,
            "evidence_source_ids": [ref.source_id for ref in self.evidence_refs],
            "uncertainty": self.uncertainty,
            "rationale": self.rationale,
            "created_at": self.created_at.isoformat(),
            "tier": "proposal",
        }


@dataclass
class AuthorityBoundary:
    """Single choke point separating advisory verbs from forbidden ones."""

    ALLOWED_ACTIONS: frozenset[str] = frozenset(
        {"read", "correlate", "hypothesize", "propose", "explain"}
    )
    """Advisory verbs that succeed (read-only, non-authoritative)."""

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
        """Grant advisory verbs; raise AuthorityError for anything else."""
        if action in self.DENIED_ACTIONS or action not in self.ALLOWED_ACTIONS:
            raise AuthorityError(f"Action {action!r} is outside agent authority.")
        self._allowed_log.append(action)
        logger.debug("Authority granted (advisory): %s", action)

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
        ref.require_fresh(now)
    joined = ", ".join(ref.source_id for ref in refs)
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
        f"This proposal ({proposal.action}) is advisory, not a decision. "
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
    known_source_ids: frozenset[str] | set[str],
    accessible_source_ids: frozenset[str] | set[str],
) -> AgentClaim:
    """Validate a plain-data claim payload into an advisory AgentClaim."""
    if not isinstance(data, Mapping):
        raise AuthorityError("Claim payload must be a mapping.")
    for smuggled in _SMUGGLED_CLAIM_KEYS:
        if smuggled in data:
            raise AuthorityError(f"Claim payload carries authoritative key {smuggled!r}.")
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
    refs = _parse_refs(
        data["evidence_refs"],
        now=now,
        known_source_ids=known_source_ids,
        accessible_source_ids=accessible_source_ids,
    )
    return AgentClaim(
        text=text, confidence=confidence, evidence_refs=refs, created_at=created_at
    )


def validate_proposal_dict(
    data: Mapping[str, Any],
    *,
    now: datetime,
    known_source_ids: frozenset[str] | set[str],
    accessible_source_ids: frozenset[str] | set[str],
    boundary: AuthorityBoundary | None = None,
) -> AgentProposal:
    """Validate a plain-data proposal payload into an advisory AgentProposal."""
    if not isinstance(data, Mapping):
        raise AuthorityError("Proposal payload must be a mapping.")
    for smuggled in _SMUGGLED_PROPOSAL_KEYS:
        if smuggled in data:
            raise AuthorityError(
                f"Proposal payload smuggles authoritative key {smuggled!r}."
            )
    for key in ("action", "uncertainty", "rationale", "created_at", "evidence_refs"):
        if key not in data:
            raise AuthorityError(f"Proposal payload is missing {key!r}.")
    action = _require_non_blank(data["action"], "action")
    if action not in AuthorityBoundary.ALLOWED_ACTIONS:
        raise AuthorityError(f"Proposal action {action!r} is out of capability.")
    if boundary is not None:
        boundary.attempt(action)
    uncertainty = _require_non_blank(data["uncertainty"], "uncertainty")
    rationale = _require_non_blank(data["rationale"], "rationale")
    created_at = _parse_time(data["created_at"], "created_at")
    refs = _parse_refs(
        data["evidence_refs"],
        now=now,
        known_source_ids=known_source_ids,
        accessible_source_ids=accessible_source_ids,
    )
    return AgentProposal(
        action=action,
        evidence_refs=refs,
        uncertainty=uncertainty,
        rationale=rationale,
        created_at=created_at,
    )


__all__ = [
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
