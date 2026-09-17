"""Resolution proposals bound to deterministic domain arithmetic (P6-05).

Proposals suggest without authorizing: amounts come only from frozen
domain arithmetic (or a named deterministic transformation recomputed
in Decimal), evidence refs stay non-empty per the D3 gate, and
approval, execution, and pin fields are refused at construction. The
assembly path delegates the D3 predicate to the frozen lifecycle owner
and consumes the P6-04 package shape as given, never reimplemented.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from decimal import Decimal
from hashlib import sha256
from types import SimpleNamespace
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from finance.correlation.package import EvidencePackage
from finance.domain.lifecycle import require_evidence_for_proposal
from finance.investigation.verdict import (
    FORBIDDEN_PROPOSAL_FIELDS,
    LIFECYCLE_OUTPUT_LABELS,
    Confidence,
    Correlation,
    FactualFinding,
    Hypothesis,
    InvestigationVerdict,
    check_no_causal_text,
    coerce_sequences,
    new_fingerprint,
)

_LLM_CAUSAL_KEYS: frozenset[str] = frozenset(
    {"root_cause", "root cause", "caused_by", "proved", "conclusion"}
)
"""LLM-shaped keys that force the quarantine path (V30)."""

_SANITISE_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"root[\s_\-]*causes?", re.IGNORECASE), "candidate factor"),
    (re.compile(r"caused[\s_\-]*by", re.IGNORECASE), "correlated with"),
    (re.compile(r"\bcauses?\b", re.IGNORECASE), "co-occurs with"),
    (re.compile(r"\bcausing\b", re.IGNORECASE), "co-occurring with"),
    (re.compile(r"prove[nd]?s?", re.IGNORECASE), "indicated"),
    (re.compile(r"proving", re.IGNORECASE), "indicating"),
    (re.compile(r"explained[\s_\-]*by", re.IGNORECASE), "associated with"),
)
"""Neutralising rewrites keeping quarantined text a candidate (V30)."""


def _require_decimal_money(value: object, *, where: str) -> Decimal:
    """Reject floats and over-precision money with explicit codes.

    Args:
        value: The candidate amount.
        where: The field name, for the message.

    Raises:
        ValueError: AMOUNT_MUST_BE_DECIMAL on floats or non-Decimal,
            AMOUNT_PRECISION beyond 2 decimal places.
    """
    if isinstance(value, bool | float):
        raise ValueError(
            f"AMOUNT_MUST_BE_DECIMAL: {where} must be Decimal, never float."
        )
    if not isinstance(value, Decimal):
        raise ValueError(f"AMOUNT_MUST_BE_DECIMAL: {where} must be Decimal.")
    if value.as_tuple().exponent < -2:
        raise ValueError(
            f"AMOUNT_PRECISION: {where} allows at most 2 decimal places."
        )
    return value


def _require_nonblank(value: str, *, where: str, code: str) -> str:
    """Refuse blank strings with the caller's contract code.

    Args:
        value: The candidate string.
        where: The field name, for the message.
        code: The refusal code to raise with.

    Raises:
        ValueError: With the given code when blank.
    """
    if not value.strip():
        raise ValueError(f"{code}: {where} must be non-blank.")
    return value


class AmountTransform(BaseModel):
    """One named deterministic amount transformation (V24).

    A proposal amount differing from the cited discrepancy passes only
    with a transform naming its legs plus arithmetic recomputable in
    Decimal (for example a fee split or a multi-leg sum).
    """

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _coerce_sequences(cls, data: object) -> object:
        """Coerce JSON lists to tuples for strict round-trip stability."""
        return coerce_sequences(data)

    rule_id: str
    """The named deterministic rule, for example FEE_SPLIT_231."""

    legs: tuple[str, ...]
    """Named legs plus arithmetic inputs, at least one."""

    arithmetic: str
    """The deterministic arithmetic, for example 10000 + 2000 = 12000."""

    result: Decimal
    """The recomputed Decimal result the proposal amount must equal."""

    @field_validator("result", mode="before")
    @classmethod
    def _check_decimal_result(cls, value: object) -> object:
        """Reject float results before strict narrowing (coded error)."""
        return _require_decimal_money(value, where="transform result")

    @model_validator(mode="before")
    @classmethod
    def _check_shape(cls, data: object) -> object:
        """Refuse lifecycle or approval fields riding a transform."""
        if isinstance(data, Mapping):
            for key in FORBIDDEN_PROPOSAL_FIELDS | {"status", "lifecycle"}:
                if key in data:
                    raise ValueError(
                        "PROPOSAL_AS_APPROVAL: amount transforms carry "
                        f"deterministic arithmetic only; key {key!r} refused."
                    )
        return data

    @model_validator(mode="after")
    def _validate_transform(self) -> AmountTransform:
        """Require a named rule, legs, arithmetic, and Decimal result."""
        _require_nonblank(self.rule_id, where="rule_id", code="AMOUNT_MISMATCH")
        _require_nonblank(
            self.arithmetic, where="arithmetic", code="AMOUNT_MISMATCH"
        )
        if not self.legs or any(not leg.strip() for leg in self.legs):
            raise ValueError(
                "AMOUNT_MISMATCH: transform legs must name at least one leg."
            )
        _require_decimal_money(self.result, where="transform result")
        return self


class ResolutionProposal(BaseModel):
    """One suggested correction that never authorizes itself (V5, V9).

    The proposal cites AUTHORITATIVE finding ids, the hypothesis it
    follows, and a quoted policy pointer. Approval ids, deciders,
    decisions, stamps, execution handles, hash pins, and lifecycle
    writes are refused at construction: unrepresentable by design.
    """

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _coerce_sequences(cls, data: object) -> object:
        """Coerce JSON lists to tuples for strict round-trip stability."""
        return coerce_sequences(data)

    kind: Literal["RESOLUTION_PROPOSAL"] = "RESOLUTION_PROPOSAL"
    """Immutable kind tag (V10)."""

    proposal_id: str
    """Stable proposal id pinned by later approval slices."""

    situation_id: str
    """The case this proposal binds to."""

    action: str
    """The suggested action, for example REPROCESS_LEGACY_RECORD."""

    amount: Decimal
    """Decimal INR amount from domain arithmetic (2 dp at most)."""

    account_code: str = ""
    """Account code when the action needs one."""

    evidence_refs: tuple[str, ...]
    """At least one AUTHORITATIVE finding id (D3 gate)."""

    hypothesis_ref: str
    """The hypothesis id this proposal follows."""

    policy_pointer: str
    """The policy text appealed to, quoted, never executed."""

    amount_transform: AmountTransform | None = None
    """Named deterministic transform when amount differs from variance."""

    amount_source: str = "DOMAIN_ARITHMETIC"
    """Only DOMAIN_ARITHMETIC is authoritative; estimates refused."""

    rationale: str = ""
    """Optional rationale; causal wording refused."""

    conflict_ref: str = ""
    """Conflict marker id cited when authoritative evidence collides."""

    @field_validator("amount", mode="before")
    @classmethod
    def _check_decimal_amount(cls, value: object) -> object:
        """Reject float amounts before strict narrowing (coded error)."""
        return _require_decimal_money(value, where="proposal amount")

    @model_validator(mode="before")
    @classmethod
    def _refuse_approval_and_lifecycle(cls, data: object) -> object:
        """Refuse approval handles and lifecycle writes with exact codes."""
        if isinstance(data, Mapping):
            kind = data.get("kind")
            if kind is not None and kind != "RESOLUTION_PROPOSAL":
                raise ValueError(
                    f"KIND_MISMATCH: expected 'RESOLUTION_PROPOSAL', "
                    f"got {kind!r}."
                )
            for key in FORBIDDEN_PROPOSAL_FIELDS:
                if key in data:
                    raise ValueError(
                        "PROPOSAL_AS_APPROVAL: proposals suggest without "
                        f"authorizing; field {key!r} is refused, stripped "
                        "of nothing silently."
                    )
            for key in ("status", "lifecycle", "transition"):
                if key in data:
                    raise ValueError(
                        "LIFECYCLE_WRITE_REFUSED: proposals never carry "
                        f"lifecycle writes; key {key!r} refused."
                    )
            for value in data.values():
                if isinstance(value, str) and value in LIFECYCLE_OUTPUT_LABELS:
                    raise ValueError(
                        "LIFECYCLE_WRITE_REFUSED: proposals never yield "
                        f"{value}."
                    )
        return data

    @model_validator(mode="after")
    def _validate_proposal(self) -> ResolutionProposal:
        """Require evidence, hypothesis, policy, and domain amounts."""
        _require_nonblank(
            self.proposal_id, where="proposal_id", code="PROPOSAL_UNGROUNDED"
        )
        _require_nonblank(
            self.situation_id, where="situation_id", code="PROPOSAL_UNGROUNDED"
        )
        _require_nonblank(
            self.action, where="action", code="PROPOSAL_UNGROUNDED"
        )
        _require_decimal_money(self.amount, where="proposal amount")
        if not self.evidence_refs:
            raise ValueError(
                "PROPOSAL_WITHOUT_EVIDENCE: at least one AUTHORITATIVE "
                "finding id is required; a hypothesis alone never "
                "satisfies the gate."
            )
        _require_nonblank(
            self.hypothesis_ref,
            where="hypothesis_ref",
            code="PROPOSAL_UNGROUNDED",
        )
        _require_nonblank(
            self.policy_pointer,
            where="policy_pointer",
            code="PROPOSAL_UNGROUNDED",
        )
        if self.amount_source != "DOMAIN_ARITHMETIC":
            raise ValueError(
                "PROBABILISTIC_AMOUNT: amounts are authoritative only from "
                "deterministic domain arithmetic over frozen facts; "
                f"source {self.amount_source!r} refused."
            )
        if self.rationale:
            check_no_causal_text(self.rationale, where="proposal rationale")
        return self


def sanitise_llm_text(text: str) -> str:
    """Neutralise causal wording so quarantined text stays a candidate.

    Args:
        text: The raw LLM-shaped wording.

    Returns:
        The neutralised candidate wording.
    """
    cleaned = text
    for pattern, replacement in _SANITISE_RULES:
        cleaned = pattern.sub(replacement, cleaned)
    return cleaned


def quarantine_llm_shaped(
    payload: Mapping[str, Any],
    *,
    situation_id: str,
    basis_refs: tuple[str, ...],
    hypothesis_id: str = "HYP-QUARANTINED",
) -> Hypothesis:
    """Quarantine LLM-shaped input as a LOW-confidence hypothesis (V30).

    Input shaped like {"root_cause": ...} (or equivalent causal shape)
    is quarantined as HYPOTHESIS at best, confidence LOW, flagged
    LLM_SHAPED_QUARANTINED. It is never promoted to a finding or a
    causal conclusion; promotion attempts raise PROMOTION_REFUSED.

    Args:
        payload: The outside LLM-shaped mapping.
        situation_id: The case the quarantine binds to.
        basis_refs: Finding or edge ids the quarantine interprets.
        hypothesis_id: Stable id for the quarantined hypothesis.

    Returns:
        The quarantined LOW-confidence hypothesis.
    """
    _ = _LLM_CAUSAL_KEYS
    raw = " ".join(f"{key}={value}" for key, value in payload.items())
    text = f"QUARANTINED (LLM_SHAPED_QUARANTINED): {sanitise_llm_text(raw)}"
    return Hypothesis(
        hypothesis_id=hypothesis_id,
        situation_id=situation_id,
        text=text,
        confidence=Confidence.LOW,
        basis_refs=basis_refs,
        quarantined=True,
        flags=("LLM_SHAPED_QUARANTINED",),
    )


def satisfies_d3_gate(
    evidence_refs: tuple[str, ...], hypothesis_count: int
) -> None:
    """Enforce the frozen D3 proposal gate by delegation, not copying.

    Calls the P6-02 predicate directly so the proposal path satisfies
    require_evidence_for_proposal exactly as the domain owner wrote it:
    at least one evidence id recorded and hypothesis_count >= 1.

    Args:
        evidence_refs: The proposal evidence refs.
        hypothesis_count: The validated hypothesis count.

    Raises:
        ValueError: From the frozen gate when unsatisfied.
    """
    require_evidence_for_proposal(
        SimpleNamespace(  # type: ignore[arg-type]
            evidence_ids=tuple(evidence_refs),
            hypothesis_count=hypothesis_count,
        )
    )


def bind_proposal_amount(
    proposal: ResolutionProposal, discrepancy: Decimal
) -> ResolutionProposal:
    """Bind a proposal amount to the cited domain discrepancy (V24).

    The amount must equal the discrepancy unless a named deterministic
    transformation is cited whose Decimal result the amount equals.
    Probabilistic amounts are already refused at construction and can
    never override domain arithmetic: the domain total wins.

    Args:
        proposal: The validated proposal to bind.
        discrepancy: The frozen P6-03 variance, cited never recomputed.

    Returns:
        The proposal unchanged when bound.

    Raises:
        ValueError: AMOUNT_MUST_BE_DECIMAL on non-Decimal discrepancies,
            AMOUNT_MISMATCH on unbound amounts.
    """
    _require_decimal_money(discrepancy, where="discrepancy")
    if proposal.amount == discrepancy:
        return proposal
    transform = proposal.amount_transform
    if (
        transform is not None
        and transform.result == proposal.amount
        and transform.rule_id.strip()
        and transform.legs
        and transform.arithmetic.strip()
    ):
        return proposal
    raise ValueError(
        "AMOUNT_MISMATCH: proposal amount "
        f"{proposal.amount} differs from cited discrepancy {discrepancy} "
        "with no named deterministic transformation; another amount "
        "passes only with explicit legs plus Decimal arithmetic."
    )


def proposal_canonical_bytes(proposal: ResolutionProposal) -> bytes:
    """Render deterministic canonical bytes for a proposal.

    Args:
        proposal: The validated proposal.

    Returns:
        The canonical JSON bytes.
    """
    payload = proposal.model_dump(mode="json")
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def proposal_hash(proposal: ResolutionProposal) -> str:
    """Fold a proposal into its stable sha256 hash.

    Args:
        proposal: The validated proposal.

    Returns:
        The 64-character hex digest later approval slices may pin.
    """
    return sha256(proposal_canonical_bytes(proposal)).hexdigest()


def _refuse_cross_case(
    evidence_binding: Mapping[str, str],
    situation_id: str,
    evidence_id: str,
) -> None:
    """Refuse evidence bound to another situation (V28).

    Args:
        evidence_binding: Evidence id to owning situation mapping.
        situation_id: The case being assembled.
        evidence_id: The cited evidence id.

    Raises:
        ValueError: With code CROSS_CASE_REFUSED on a wrong-situation id.
    """
    owner = evidence_binding.get(evidence_id)
    if owner is not None and owner != situation_id:
        raise ValueError(
            f"CROSS_CASE_REFUSED: evidence {evidence_id!r} is bound to "
            f"{owner!r}, not {situation_id!r}."
        )


def assemble_verdict(
    *,
    situation_id: str,
    discrepancy: Decimal,
    findings: tuple[FactualFinding, ...] = (),
    correlations: tuple[Correlation, ...] = (),
    hypotheses: tuple[Hypothesis, ...] = (),
    proposal: ResolutionProposal | None = None,
    package: EvidencePackage | None = None,
    conflict_present: bool = False,
    evidence_binding: Mapping[str, str] | None = None,
    reasons: tuple[str, ...] = (),
    envelope: Mapping[str, Any] | None = None,
) -> InvestigationVerdict:
    """Assemble one fingerprint-stable verdict set (R1, R12).

    Findings, correlations, and hypotheses arrive validated; this path
    enforces the cross-object gates deterministically: wrong-situation
    cites refused, INCOMPLETE packages hold proposals, preserved
    stalemates refuse silent winners, the D3 gate delegates to the
    frozen predicate, amounts bind to domain arithmetic, and empty
    resolutions terminate UNRESOLVED with cited reasons. Run or session
    ids in the envelope are accepted for caller convenience and
    excluded from the fingerprint.

    Args:
        situation_id: The case being assembled.
        discrepancy: The frozen P6-03 variance, cited never recomputed.
        findings: Validated factual findings.
        correlations: Validated non-causal correlations.
        hypotheses: Validated candidate hypotheses.
        proposal: The draft proposal, or None for UNRESOLVED.
        package: The consumed P6-04 package shape (read-only).
        conflict_present: True when CONFLICTING_EVIDENCE is preserved.
        evidence_binding: Evidence id to owning situation mapping.
        reasons: Cited reasons (required in spirit when UNRESOLVED).
        envelope: Run or session ids, excluded from the hash.

    Returns:
        The terminal verdict set with a stable fingerprint.

    Raises:
        ValueError: CROSS_CASE_REFUSED, EVIDENCE_INCOMPLETE,
            RECORD_SHOPPING, PROPOSAL_INVENTED, PROPOSAL_UNGROUNDED,
            AMOUNT_MISMATCH, or the frozen D3 messages.
    """
    _ = envelope
    _require_decimal_money(discrepancy, where="discrepancy")
    binding = dict(evidence_binding) if evidence_binding else {}
    for finding in findings:
        for evidence_id in finding.evidence_ids:
            _refuse_cross_case(binding, situation_id, evidence_id)
    if package is not None and not package.complete:
        missing = ", ".join(
            f"{leg.source_system}:{leg.key}:{leg.reason}"
            for leg in package.missing
        )
        if proposal is not None:
            raise ValueError(
                "EVIDENCE_INCOMPLETE: package "
                f"{package.package_id!r} is INCOMPLETE with missing "
                f"{missing}; the proposal is held and the leg is never "
                "guessed."
            )
    if conflict_present and proposal is not None and not proposal.conflict_ref.strip():
        raise ValueError(
            "RECORD_SHOPPING: conflicting AUTHORITATIVE evidence is "
            "preserved; no proposal may pick a winner silently. Cite "
            "the conflict marker explicitly or end UNRESOLVED."
        )
    if proposal is not None:
        for evidence_id in proposal.evidence_refs:
            _refuse_cross_case(binding, situation_id, evidence_id)
        if not hypotheses:
            raise ValueError(
                "PROPOSAL_INVENTED: no hypothesis supports a proposal; "
                "terminate UNRESOLVED with reasons instead of inventing one."
            )
        satisfies_d3_gate(proposal.evidence_refs, len(hypotheses))
        known = {hypothesis.hypothesis_id for hypothesis in hypotheses}
        if proposal.hypothesis_ref not in known:
            raise ValueError(
                "PROPOSAL_UNGROUNDED: hypothesis_ref "
                f"{proposal.hypothesis_ref!r} cites no validated hypothesis."
            )
        covered = {
            evidence_id for finding in findings for evidence_id in finding.evidence_ids
        }
        for ref in proposal.evidence_refs:
            if ref not in covered:
                raise ValueError(
                    "PROPOSAL_UNGROUNDED: evidence ref "
                    f"{ref!r} is cited by no AUTHORITATIVE finding."
                )
        bind_proposal_amount(proposal, discrepancy)
    final_reasons = tuple(reasons)
    if proposal is None and not final_reasons:
        if package is not None and not package.complete:
            missing = ", ".join(
                f"{leg.source_system}:{leg.key}:{leg.reason}"
                for leg in package.missing
            )
            final_reasons = (
                f"package {package.package_id} INCOMPLETE; held for {missing}",
            )
        elif conflict_present:
            final_reasons = (
                "conflicting AUTHORITATIVE evidence preserved; no silent "
                "winner picked",
            )
        else:
            final_reasons = (
                "no hypothesis supports a proposal; ends UNRESOLVED "
                "escalation-ready",
            )
    fingerprint = new_fingerprint(
        situation_id,
        format(discrepancy, "f"),
        "|".join(finding.model_dump_json() for finding in findings),
        "|".join(edge.model_dump_json() for edge in correlations),
        "|".join(hypothesis.model_dump_json() for hypothesis in hypotheses),
        proposal.model_dump_json() if proposal is not None else "NO-PROPOSAL",
        package.fingerprint if package is not None else "NO-PACKAGE",
        "CONFLICT" if conflict_present else "NO-CONFLICT",
        "\x1f".join(final_reasons),
    )
    return InvestigationVerdict(
        situation_id=situation_id,
        findings=findings,
        correlations=correlations,
        hypotheses=hypotheses,
        proposal=proposal,
        terminal_label="PROPOSED" if proposal is not None else "UNRESOLVED",
        reasons=final_reasons if proposal is None else (),
        fingerprint=fingerprint,
    )
