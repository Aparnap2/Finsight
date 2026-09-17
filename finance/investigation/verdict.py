"""Investigation verdict types for P6-05 (findings, links, candidates).

This module defines the semantic object plane a future proposer may
consume: factual findings quoted verbatim from authoritative records,
non-causal correlation edges, candidate hypotheses with confidence
labels, and the terminal verdict set. Causal conclusions exist only to
be refused; approvals, execution handles, and lifecycle writes are
unrepresentable here. Facts are quoted, links are correlation,
hypotheses stay candidates, and causation is forbidden.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from enum import StrEnum
from hashlib import sha256
from typing import Any, Literal, NoReturn

from pydantic import BaseModel, ConfigDict, model_validator

from finance.correlation.converter import trust_class_for

NON_CAUSAL_BANNER = (
    "CORRELATED_WITH only: co-occurrence for investigation, "
    "never causation or proof (E26)."
)
"""Banner every correlation must carry verbatim (P6-04 E26)."""

CORRELATED_WITH = "CORRELATED_WITH"
"""The only permitted edge label (V2, V7)."""

FORBIDDEN_PROPOSAL_FIELDS: frozenset[str] = frozenset(
    {
        "approval_id",
        "approval",
        "decider",
        "decision",
        "decided_at",
        "execution_id",
        "s3_key",
        "proposal_hash",
        "proposal_version",
        "batch_key",
        "close_proof",
        "status_stamp",
        "authorized_by",
        "authorised_by",
        "signature",
    }
)
"""Approval, execution, and pin fields that must never ride a proposal."""

LIFECYCLE_OUTPUT_LABELS: frozenset[str] = frozenset(
    {"APPROVED", "EXECUTING", "VERIFYING", "CLOSED"}
)
"""Lifecycle outputs P6-05 construction must never emit (V27, V39)."""

_CAUSAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bcaused\s+by\b"),
    re.compile(r"\broot\s+cause\b"),
    re.compile(r"\bproves?\b"),
    re.compile(r"\bproving\b"),
    re.compile(r"\bexplained\s+by\b"),
    re.compile(r"\bcauses\b"),
    re.compile(r"\bcausing\b"),
)
"""Causal-upgrade wording refused with CAUSAL_UPGRADE (V7)."""


def _normalise_separators(text: str) -> str:
    """Map underscores and hyphens to spaces for wording scans."""
    return text.replace("_", " ").replace("-", " ")


def check_no_causal_text(text: str, *, where: str) -> None:
    """Refuse causal-upgrade wording with CAUSAL_UPGRADE.

    Args:
        text: The candidate wording to scan.
        where: The field or object being scanned (for the message).

    Raises:
        ValueError: With code CAUSAL_UPGRADE when causal wording appears.
    """
    folded = _normalise_separators(text).lower()
    for pattern in _CAUSAL_PATTERNS:
        if pattern.search(folded) is not None:
            raise ValueError(
                f"CAUSAL_UPGRADE: {where} declares causation or proof; "
                "P6-05 permits CORRELATED_WITH links and candidate "
                "hypotheses only."
            )


def new_fingerprint(*parts: str) -> str:
    """Fold canonical parts into one stable sha256 hex digest.

    Args:
        parts: Ordered canonical strings to fold.

    Returns:
        The 64-character hex digest (no run or session ids folded in).
    """
    return sha256("\x00".join(parts).encode("utf-8")).hexdigest()


def coerce_sequences(data: object) -> object:
    """Coerce JSON lists to tuples for strict round-trip stability.

    Strict mode accepts tuples but rejects JSON lists; this shared
    before-validator helper keeps every sequence field round-trippable
    without weakening scalar strictness.
    """
    if isinstance(data, Mapping):
        return {
            key: (tuple(value) if isinstance(value, list) else value)
            for key, value in data.items()
        }
    return data


_FINDING_MARKERS = frozenset(
    {"finding_id", "quoted_value", "evidence_ids", "verified_ids", "source_system"}
)
"""Keys distinctive to FACTUAL_FINDING payloads."""

_HYPOTHESIS_MARKERS = frozenset(
    {"hypothesis_id", "text", "confidence", "basis_refs", "flags"}
)
"""Keys distinctive to HYPOTHESIS payloads."""

_CORRELATION_MARKERS = frozenset({"edge_id", "edge_refs", "edge_label", "banner"})
"""Keys distinctive to CORRELATION payloads."""


def _require_kind(
    data: object, expected: str, *, foreign_markers: frozenset[str] = frozenset()
) -> object:
    """Refuse kind-swapped payloads with KIND_MISMATCH.

    A matching kind tag is not enough: payloads carrying another
    kind's distinctive fields are shape-swaps, refused with the same
    code so serialization can never blur the type boundary.

    Args:
        data: The raw pre-validation mapping.
        expected: The kind tag this schema requires.
        foreign_markers: Keys belonging to other kinds; presence
            refuses the payload even when the tag matches.

    Raises:
        ValueError: With code KIND_MISMATCH on a swapped or dropped tag.
    """
    if isinstance(data, Mapping):
        kind = data.get("kind")
        if kind is not None and kind != expected:
            raise ValueError(
                f"KIND_MISMATCH: expected kind {expected!r}, got {kind!r}."
            )
        clashing = sorted(set(data) & set(foreign_markers))
        if clashing:
            raise ValueError(
                f"KIND_MISMATCH: payload for {expected!r} carries "
                f"another kind's fields: {clashing}."
            )
    return data


def _source_prefix(evidence_id: str) -> str:
    """Return the source-system prefix of an evidence id."""
    return evidence_id.split(":", 1)[0].strip()


class Confidence(StrEnum):
    """Required confidence label for every hypothesis (V3)."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class FactualFinding(BaseModel):
    """One verbatim quoted fact grounded in authoritative evidence (V1).

    A finding quotes a value exactly as the cited record states it and
    cites at least one AUTHORITATIVE evidence id whose hash verified
    and whose reference resolves. Advisory or context items alone never
    ground a finding.
    """

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _coerce_sequences(cls, data: object) -> object:
        """Coerce JSON lists to tuples for strict round-trip stability."""
        return coerce_sequences(data)

    kind: Literal["FACTUAL_FINDING"] = "FACTUAL_FINDING"
    """Immutable kind tag (V10)."""

    finding_id: str
    """Stable finding id cited by edges, hypotheses, and proposals."""

    situation_id: str
    """The case this finding binds to (cross-case cites refused)."""

    evidence_ids: tuple[str, ...]
    """Cited evidence ids (at least one verified AUTHORITATIVE id)."""

    quoted_value: str
    """Verbatim amount, code, or disposition from the cited record."""

    source_system: str
    """The authoritative record system (never advisory or context)."""

    verified_ids: tuple[str, ...] = ()
    """Ids whose content hash verified and reference resolves (E3, E18)."""

    @model_validator(mode="before")
    @classmethod
    def _check_kind(cls, data: object) -> object:
        """Refuse kind-swapped payloads before field validation."""
        return _require_kind(
            data,
            "FACTUAL_FINDING",
            foreign_markers=_HYPOTHESIS_MARKERS | _CORRELATION_MARKERS,
        )

    @model_validator(mode="after")
    def _validate_grounding(self) -> FactualFinding:
        """Require verbatim quote plus verified authoritative grounding."""
        if not self.finding_id.strip():
            raise ValueError("FINDING_WITHOUT_GROUNDING: finding_id blank.")
        if not self.situation_id.strip():
            raise ValueError("FINDING_WITHOUT_GROUNDING: situation_id blank.")
        if not self.quoted_value.strip():
            raise ValueError(
                "FINDING_WITHOUT_GROUNDING: quoted_value must be verbatim, "
                "never blank or paraphrased."
            )
        if not self.source_system.strip():
            raise ValueError("FINDING_WITHOUT_GROUNDING: source_system blank.")
        if trust_class_for(self.source_system) != "AUTHORITATIVE":
            raise ValueError(
                "FINDING_WITHOUT_GROUNDING: source_system "
                f"{self.source_system!r} is not AUTHORITATIVE; advisory or "
                "context items ride as investigation context only."
            )
        if not self.evidence_ids:
            raise ValueError(
                "FINDING_WITHOUT_GROUNDING: at least one AUTHORITATIVE "
                "evidence id is required."
            )
        verified = set(self.verified_ids)
        grounded = any(
            eid in verified
            and trust_class_for(_source_prefix(eid)) == "AUTHORITATIVE"
            for eid in self.evidence_ids
        )
        if not grounded:
            raise ValueError(
                "FINDING_WITHOUT_GROUNDING: no cited evidence id is both "
                "AUTHORITATIVE and hash-verified with a resolving reference."
            )
        return self


class Correlation(BaseModel):
    """One non-causal link over edge refs with the E26 banner (V2).

    Correlations join findings or evidence by co-occurrence for
    investigation. They carry no quoted authoritative value, decide
    nothing, resize no variance, and backfill no missing fact.
    """

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _coerce_sequences(cls, data: object) -> object:
        """Coerce JSON lists to tuples for strict round-trip stability."""
        return coerce_sequences(data)

    kind: Literal["CORRELATION"] = "CORRELATION"
    """Immutable kind tag (V10)."""

    edge_id: str
    """Stable edge id cited by hypotheses."""

    situation_id: str
    """The case this correlation binds to."""

    edge_refs: tuple[str, ...]
    """At least two evidence or finding ids linked by co-occurrence."""

    edge_label: str = CORRELATED_WITH
    """Exactly CORRELATED_WITH; any causal label is refused."""

    banner: str = NON_CAUSAL_BANNER
    """The P6-04 no-causality banner, carried verbatim (E26)."""

    @model_validator(mode="before")
    @classmethod
    def _check_shape(cls, data: object) -> object:
        """Refuse kind swaps and quoted values riding as correlation."""
        if isinstance(data, Mapping) and "quoted_value" in data:
            raise ValueError(
                "CORRELATION_AS_FACT: a correlation carries edge refs, "
                "never a quoted authoritative value as its own assertion."
            )
        _require_kind(
            data,
            "CORRELATION",
            foreign_markers=_FINDING_MARKERS | _HYPOTHESIS_MARKERS,
        )
        return data

    @model_validator(mode="after")
    def _validate_link(self) -> Correlation:
        """Require edge refs, the exact label, and the banner."""
        if not self.edge_id.strip():
            raise ValueError("CORRELATION_WITHOUT_EDGES: edge_id blank.")
        if not self.situation_id.strip():
            raise ValueError("CORRELATION_WITHOUT_EDGES: situation_id blank.")
        if len(self.edge_refs) < 2:
            raise ValueError(
                "CORRELATION_WITHOUT_EDGES: at least two edge refs required."
            )
        if self.edge_label != CORRELATED_WITH:
            raise ValueError(
                "CAUSAL_UPGRADE: edge labels allow exactly CORRELATED_WITH; "
                f"got {self.edge_label!r}."
            )
        check_no_causal_text(self.edge_label, where="correlation edge_label")
        if self.banner != NON_CAUSAL_BANNER:
            raise ValueError(
                "CORRELATION_WITHOUT_BANNER: the E26 no-causality banner "
                "must be carried verbatim."
            )
        return self


class Hypothesis(BaseModel):
    """One candidate explanation with a required confidence label (V3).

    Hypotheses interpret findings or edges and stay candidates. They
    never ground a finding or a proposal amount (V8), and confidence
    labels never substitute for AUTHORITATIVE grounding.
    """

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _coerce_sequences(cls, data: object) -> object:
        """Coerce JSON lists to tuples for strict round-trip stability."""
        return coerce_sequences(data)

    kind: Literal["HYPOTHESIS"] = "HYPOTHESIS"
    """Immutable kind tag (V10)."""

    hypothesis_id: str
    """Stable hypothesis id cited by proposals."""

    situation_id: str
    """The case this hypothesis binds to."""

    text: str
    """Candidate explanation stated as candidate, never as fact."""

    confidence: Confidence
    """Required label: LOW, MEDIUM, or HIGH."""

    basis_refs: tuple[str, ...]
    """Finding or edge ids this hypothesis interprets (at least one)."""

    quarantined: bool = False
    """True when built by the LLM-shaped quarantine path (V30)."""

    flags: tuple[str, ...] = ()
    """Machine flags such as LLM_SHAPED_QUARANTINED."""

    @model_validator(mode="before")
    @classmethod
    def _check_kind(cls, data: object) -> object:
        """Refuse kind-swapped payloads before field validation."""
        return _require_kind(
            data,
            "HYPOTHESIS",
            foreign_markers=_FINDING_MARKERS | _CORRELATION_MARKERS,
        )

    @model_validator(mode="after")
    def _validate_candidate(self) -> Hypothesis:
        """Require candidate text, confidence, and basis refs."""
        if not self.hypothesis_id.strip():
            raise ValueError("HYPOTHESIS_WITHOUT_BASIS: hypothesis_id blank.")
        if not self.situation_id.strip():
            raise ValueError("HYPOTHESIS_WITHOUT_BASIS: situation_id blank.")
        if not self.text.strip():
            raise ValueError("HYPOTHESIS_WITHOUT_BASIS: text blank.")
        check_no_causal_text(self.text, where="hypothesis text")
        if not self.basis_refs:
            raise ValueError(
                "HYPOTHESIS_WITHOUT_BASIS: at least one basis ref required."
            )
        return self


class CausalConclusion(BaseModel):
    """Forbidden causal type: construction is always refused (V4).

    The type exists only so candidates carrying causal wording or the
    CAUSAL_CONCLUSION kind fail closed with CAUSAL_UPGRADE. No strength
    threshold or sufficient condition exists in this slice.
    """

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    kind: Literal["CAUSAL_CONCLUSION"] = "CAUSAL_CONCLUSION"
    """Kind tag that can never validate."""

    situation_id: str = ""
    """Accepted for shape compatibility, never emitted."""

    text: str = ""
    """Accepted for shape compatibility, never emitted."""

    @model_validator(mode="after")
    def _always_refuse(self) -> CausalConclusion:
        """Refuse every causal conclusion with CAUSAL_UPGRADE."""
        raise ValueError(
            "CAUSAL_UPGRADE: causal conclusions are forbidden in P6-05; "
            "no sufficient formulation exists in this slice."
        )


class AuthorizedAction(BaseModel):
    """Forbidden authorization type: construction is always refused.

    Authorizations (approvals, execution handles, pins) never ride the
    verdict plane. Any candidate carrying this kind fails closed.
    """

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    kind: Literal["AUTHORIZED_ACTION"] = "AUTHORIZED_ACTION"
    """Kind tag that can never validate."""

    situation_id: str = ""
    """Accepted for shape compatibility, never emitted."""

    text: str = ""
    """Accepted for shape compatibility, never emitted."""

    @model_validator(mode="after")
    def _always_refuse(self) -> AuthorizedAction:
        """Refuse every authorized action with PROPOSAL_AS_APPROVAL."""
        raise ValueError(
            "PROPOSAL_AS_APPROVAL: authorizations never ride the verdict "
            "plane; proposals suggest without authorizing."
        )


class InvestigationVerdict(BaseModel):
    """One terminal verdict set: chain plus proposal or UNRESOLVED (V31).

    UNRESOLVED is a termination label for the verdict, never a
    lifecycle state (V39). PROPOSED carries exactly one proposal; every
    other lifecycle output is refused at construction.
    """

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _coerce_sequences(cls, data: object) -> object:
        """Coerce JSON lists to tuples for strict round-trip stability."""
        return coerce_sequences(data)

    kind: Literal["INVESTIGATION_VERDICT"] = "INVESTIGATION_VERDICT"
    """Immutable kind tag (V10)."""

    situation_id: str
    """The case this verdict set binds to."""

    findings: tuple[FactualFinding, ...] = ()
    """Validated factual findings (may be empty only when UNRESOLVED)."""

    correlations: tuple[Correlation, ...] = ()
    """Validated non-causal correlations."""

    hypotheses: tuple[Hypothesis, ...] = ()
    """Validated candidate hypotheses."""

    proposal: Any = None
    """One RESOLUTION_PROPOSAL when PROPOSED, None when UNRESOLVED."""

    terminal_label: Literal["PROPOSED", "UNRESOLVED"]
    """Terminal label only; lifecycle states are unrepresentable here."""

    reasons: tuple[str, ...] = ()
    """Cited reasons (required when UNRESOLVED)."""

    fingerprint: str
    """sha256 over the canonical inputs, excluding any envelope ids."""

    @model_validator(mode="before")
    @classmethod
    def _refuse_lifecycle_writes(cls, data: object) -> object:
        """Refuse lifecycle writes before field validation (V27)."""
        _require_kind(data, "INVESTIGATION_VERDICT")
        if isinstance(data, Mapping):
            for key in (
                "status",
                "lifecycle",
                "transition",
                "execution_id",
                "approval_id",
            ):
                if key in data:
                    raise ValueError(
                        "LIFECYCLE_WRITE_REFUSED: verdict construction is "
                        f"limited to PROPOSED-bound outputs; key {key!r} "
                        "is refused."
                    )
            for value in data.values():
                if isinstance(value, str) and value in LIFECYCLE_OUTPUT_LABELS:
                    raise ValueError(
                        "LIFECYCLE_WRITE_REFUSED: verdict sets never yield "
                        f"{value}; construction is PROPOSED-bound only."
                    )
        return data

    @model_validator(mode="after")
    def _validate_terminal(self) -> InvestigationVerdict:
        """Bind the terminal label to the proposal-or-UNRESOLVED shape."""
        if not self.situation_id.strip():
            raise ValueError("PROPOSAL_INVENTED: situation_id blank.")
        if len(self.fingerprint) != 64:
            raise ValueError(
                "FINGERPRINT_INVALID: fingerprint must be a sha256 hex."
            )
        if self.proposal is None:
            if self.terminal_label != "UNRESOLVED":
                raise ValueError(
                    "PROPOSAL_INVENTED: PROPOSED requires exactly one "
                    "proposal; inventing none is refused."
                )
            if not self.reasons:
                raise ValueError(
                    "UNRESOLVED_WITHOUT_REASONS: UNRESOLVED verdicts cite "
                    "reasons and stay escalation-ready."
                )
            return self
        kind = getattr(self.proposal, "kind", None)
        if kind != "RESOLUTION_PROPOSAL":
            raise ValueError(
                f"KIND_MISMATCH: verdict proposal must carry kind "
                f"'RESOLUTION_PROPOSAL', got {kind!r}."
            )
        for field in FORBIDDEN_PROPOSAL_FIELDS:
            if getattr(self.proposal, field, None):
                raise ValueError(
                    "PROPOSAL_AS_APPROVAL: the verdict proposal carries "
                    f"authorization field {field!r}; refused, stripped of "
                    "nothing silently."
                )
        if self.terminal_label != "PROPOSED":
            raise ValueError(
                "PROPOSAL_INVENTED: a verdict carrying a proposal "
                "terminates PROPOSED, never UNRESOLVED."
            )
        return self


def refuse_promotion(*, from_kind: str, to_kind: str, item_id: str = "") -> NoReturn:
    """Always refuse kind promotion with PROMOTION_REFUSED (V17).

    Args:
        from_kind: The immutable kind the object carries.
        to_kind: The kind a caller attempted to re-tag it as.
        item_id: The object id, for the message only.

    Raises:
        ValueError: Always, with code PROMOTION_REFUSED.
    """
    raise ValueError(
        "PROMOTION_REFUSED: cannot re-tag "
        f"{from_kind} {item_id!r} as {to_kind}; kinds are immutable and "
        "no upgrade path exists in this slice."
    )


def refuse_hypothesis_as_fact(hypothesis_id: str) -> NoReturn:
    """Refuse grounding a finding or an amount in a hypothesis (V8).

    Args:
        hypothesis_id: The hypothesis misused as grounding.

    Raises:
        ValueError: Always, with code HYPOTHESIS_AS_FACT.
    """
    raise ValueError(
        f"HYPOTHESIS_AS_FACT: hypothesis {hypothesis_id!r} is a candidate, "
        "never grounding for a finding or a proposal amount."
    )


def verdict_canonical_bytes(verdict: InvestigationVerdict) -> bytes:
    """Render deterministic canonical bytes for a verdict set.

    Keys sort canonically and no envelope ids exist on the model, so
    identical inputs always yield byte-identical output (V29).

    Args:
        verdict: The validated verdict set.

    Returns:
        The canonical JSON bytes.
    """
    payload = verdict.model_dump(mode="json")
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def verdict_handoff(verdict: InvestigationVerdict) -> dict[str, Any]:
    """Project the exact future-proposer handoff fields (V32).

    Only finding ids with quoted values and evidence ids, edge refs
    with CORRELATED_WITH labels, hypothesis text with confidence, and
    the proposal object cross the boundary. Nothing else is handed.

    Args:
        verdict: The validated verdict set.

    Returns:
        The handoff mapping with exactly the V32 fields.
    """
    proposal = verdict.proposal
    handoff_proposal: dict[str, Any] | None = None
    if proposal is not None:
        handoff_proposal = {
            "action": proposal.action,
            "amount": str(proposal.amount),
            "account_code": proposal.account_code,
            "evidence_refs": list(proposal.evidence_refs),
            "hypothesis_ref": proposal.hypothesis_ref,
            "policy_pointer": proposal.policy_pointer,
        }
    return {
        "findings": [
            {
                "finding_id": finding.finding_id,
                "quoted_value": finding.quoted_value,
                "evidence_ids": list(finding.evidence_ids),
            }
            for finding in verdict.findings
        ],
        "correlations": [
            {
                "edge_id": edge.edge_id,
                "edge_refs": list(edge.edge_refs),
                "edge_label": edge.edge_label,
            }
            for edge in verdict.correlations
        ],
        "hypotheses": [
            {
                "hypothesis_id": hypothesis.hypothesis_id,
                "text": hypothesis.text,
                "confidence": hypothesis.confidence.value,
            }
            for hypothesis in verdict.hypotheses
        ],
        "proposal": handoff_proposal,
    }


def assert_no_preauthorized(handoff: Mapping[str, Any]) -> None:
    """Refuse handoffs carrying approval or execution handles (V33).

    Args:
        handoff: The handoff mapping to inspect.

    Raises:
        ValueError: With code PREAUTHORIZED_HANDOFF on any handle.
    """
    queue: list[Any] = [handoff]
    while queue:
        current = queue.pop()
        if isinstance(current, Mapping):
            for key, value in current.items():
                if key in FORBIDDEN_PROPOSAL_FIELDS:
                    raise ValueError(
                        "PREAUTHORIZED_HANDOFF: handoff carries "
                        f"pre-authorized field {key!r}; refused."
                    )
                queue.append(value)
        elif isinstance(current, (list, tuple)):
            queue.extend(current)
