"""G1-G6 approval decision gate for P6-06 (proposal validation + decision).

Core invariant (contract A3):

    a valid proposal is evidence of what FinSight recommends; it is never
    evidence that FinSight is authorized to do it.

A decision is a separate frozen object that pins exactly one
(``proposal_hash``, ``proposal_version``); it mutates no proposal, performs
no lifecycle transition, and authorizes no execution. Minting lives in
``finance.approval.authorization`` (G7). Tier conformance reuses
``MeridianBusinessRules`` via ``finance.approval.tiers`` (never
reimplemented); the post-approval freeze delegates to
``require_proposal_frozen`` via :func:`assert_pin_frozen`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Collection
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from finance.approval.refusals import ApprovalRefused, RefusalCode
from finance.approval.tiers import KNOWN_ROLES, required_authority, role_may_approve
from finance.business_rules.meridian import RefundAuthority
from finance.domain.account_mappings import is_valid_cobol_code
from finance.domain.lifecycle import require_decider_authority_for_approval, require_proposal_frozen

if TYPE_CHECKING:
    from finance.domain.financial_situation import FinancialSituation

_HASH_PATTERN_LENGTH = 64


class DecisionOutcome(StrEnum):
    """G6 decision outcomes (contract A14: ``APPROVE`` or ``REJECT``)."""

    APPROVE = "APPROVE"
    """The pinned proposal version is approved; G7 may mint once."""

    REJECT = "REJECT"
    """The pinned proposal version is refused; G7 mints nothing."""


def canonical_amount(amount: Decimal) -> str:
    """Return the canonical string form of a Decimal amount for hashing.

    Args:
        amount: The monetary amount to encode.

    Returns:
        Normalised fixed-point string (``Decimal("10000.00")`` and
        ``Decimal("10000")`` encode identically).
    """
    return format(amount.normalize(), "f")


def compute_proposal_hash(
    *,
    situation_id: str,
    action: str,
    amount: Decimal,
    account_code: str,
    evidence_refs: tuple[str, ...],
    hypothesis_ref: str,
    proposal_version: int,
) -> str:
    """Recompute the G5 proposal hash over the A13 binding fields.

    Args:
        situation_id: The case the proposal belongs to.
        action: The resolution action name.
        amount: The bound Decimal amount.
        account_code: The bound COBOL account code.
        evidence_refs: Cited evidence refs in order.
        hypothesis_ref: The bound hypothesis ref.
        proposal_version: The proposal version (>= 1).

    Returns:
        Lowercase sha256 hex digest of the canonical field encoding.
    """
    canonical = "|".join(
        [
            situation_id,
            action,
            canonical_amount(amount),
            account_code,
            ",".join(evidence_refs),
            hypothesis_ref,
            str(proposal_version),
        ]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def approval_id_for(decision_id: str, proposal_hash: str, proposal_version: int) -> str:
    """Derive the deterministic approval id for a decision pin.

    Args:
        decision_id: Caller-supplied decision identity (the A16 replay key).
        proposal_hash: The pinned proposal hash.
        proposal_version: The pinned proposal version.

    Returns:
        ``appr_<16 hex>`` stable for identical inputs, so replays address
        the same decision instead of recording duplicates.
    """
    canonical = "|".join([decision_id, proposal_hash, str(proposal_version)])
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"appr_{digest[:16]}"


def idempotency_key_for(company_id: str, proposal_hash: str, proposal_version: int) -> str:
    """Derive the P6-07 idempotency key bound to one approved version (A16-A17).

    Args:
        company_id: The bound company (``meridian``).
        proposal_hash: The pinned proposal hash.
        proposal_version: The pinned proposal version.

    Returns:
        ``idem_<16 hex>`` deterministic in the triple, carried by both the
        decision and the authorization so P6-07 effects deduplicate.
    """
    canonical = "|".join([company_id, proposal_hash, str(proposal_version)])
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"idem_{digest[:16]}"


def _require_non_empty(field_name: str, value: str) -> str:
    """Return the stripped identifier or raise ValueError when blank."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Field '{field_name}' must be a non-empty string.")
    return value.strip()


def _require_hash(value: str) -> str:
    """Return the sha256 hex digest or raise ValueError."""
    digest = _require_non_empty("proposal_hash", value)
    if len(digest) != _HASH_PATTERN_LENGTH or any(
        ch not in "0123456789abcdef" for ch in digest.lower()
    ):
        raise ValueError("Field 'proposal_hash' must be a sha256 hex digest.")
    return digest.lower()


def _require_version(value: int) -> int:
    """Return the 1-based version or raise."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("Field 'proposal_version' must be an int.")
    if value < 1:
        raise ValueError("Field 'proposal_version' must be >= 1.")
    return value


def _require_tz_aware(field_name: str, value: datetime) -> datetime:
    """Return the timestamp or raise ValueError when naive (A14)."""
    if not isinstance(value, datetime):
        raise TypeError(f"Field '{field_name}' must be a datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"Field '{field_name}' must be timezone-aware.")
    return value


class ProposalSnapshot(BaseModel):
    """Frozen proposal inputs consumed by the G5 validation gate (A13)."""

    model_config = ConfigDict(frozen=True, strict=True)

    situation_id: str
    """Case id the proposal belongs to."""

    company_id: str
    """Owning company; only ``meridian`` passes G3."""

    action: str
    """Resolution action name (e.g. ``REPROCESS_LEGACY_RECORD``)."""

    amount: Decimal
    """Bound amount in INR (``Decimal``-only; floats rejected at the boundary)."""

    account_code: str
    """Bound COBOL account code (must sit in ``AccountMappings``)."""

    evidence_refs: tuple[str, ...]
    """Cited evidence refs in order (non-empty per G5)."""

    hypothesis_ref: str
    """Bound hypothesis ref."""

    proposal_hash: str
    """Claimed sha256 hash over the A13 binding fields."""

    proposal_version: int
    """Proposal version (>= 1)."""

    proposer_id: str
    """Proposer identity for the A7 separation-of-duties check."""

    is_legacy: bool = False
    """True for legacy corrections (never AUTO, A10)."""

    period: str | None = None
    """Correction entry period (``YYYY-MM``); checked against closed periods."""

    @field_validator("situation_id", "action", "proposer_id")
    @classmethod
    def _check_text(cls, value: str) -> str:
        """Require non-blank text fields."""
        return _require_non_empty("text", value)


class ApprovalDecision(BaseModel):
    """Frozen G6 decision object pinning one proposal version (A14)."""

    model_config = ConfigDict(frozen=True, strict=True)

    decision_id: str
    """Caller-supplied decision identity (the A16 replay key)."""

    situation_id: str
    """Case the decision applies to."""

    company_id: str
    """Bound company (``meridian``)."""

    proposal_hash: str
    """Pinned proposal hash (exactly one version, A15)."""

    proposal_version: int
    """Pinned proposal version."""

    proposer_id: str
    """Original proposer (self-approval check evidence, A7)."""

    approver: str
    """Decider identity (must differ from ``proposer_id``)."""

    approver_role: str
    """Decider role claim (``manager`` or ``director`` to permit)."""

    outcome: DecisionOutcome
    """``APPROVE`` or ``REJECT`` (A14)."""

    decided_at: datetime
    """Caller-supplied tz-aware decision timestamp (naive refused, A14)."""

    approval_id: str = ""
    """Deterministic id derived from (decision, hash, version); filled always."""

    idempotency_key: str = ""
    """P6-07 key deterministic in (company, hash, version); filled always."""

    @model_validator(mode="before")
    @classmethod
    def _fill_derived(cls, data: Any) -> Any:
        """Inject deterministic ids when the caller leaves them blank."""
        if isinstance(data, dict):
            filled = dict(data)
            try:
                if not filled.get("approval_id"):
                    filled["approval_id"] = approval_id_for(
                        filled["decision_id"],
                        filled["proposal_hash"],
                        filled["proposal_version"],
                    )
                if not filled.get("idempotency_key"):
                    filled["idempotency_key"] = idempotency_key_for(
                        filled.get("company_id", "meridian"),
                        filled["proposal_hash"],
                        filled["proposal_version"],
                    )
            except KeyError:
                pass
            return filled
        return data

    @field_validator("decision_id", "situation_id", "proposer_id", "approver")
    @classmethod
    def _check_ids(cls, value: str) -> str:
        """Require non-blank identifiers."""
        return _require_non_empty("id", value)

    @field_validator("proposal_hash")
    @classmethod
    def _check_hash(cls, value: str) -> str:
        """Require a sha256 hex digest pin."""
        return _require_hash(value)

    @field_validator("proposal_version")
    @classmethod
    def _check_version(cls, value: int) -> int:
        """Require a 1-based version."""
        return _require_version(value)

    @field_validator("decided_at")
    @classmethod
    def _check_decided_at(cls, value: datetime) -> datetime:
        """Refuse naive timestamps (A14)."""
        return _require_tz_aware("decided_at", value)


def _refuse(code: RefusalCode, gate: str, message: str) -> ApprovalRefused:
    """Build the refusal signal for a failing gate."""
    return ApprovalRefused(code, gate, message)


def decide(
    proposal: ProposalSnapshot,
    *,
    decision_id: str,
    approver: str,
    approver_role: str,
    auth_proof: str | None,
    auth_proof_valid: bool = True,
    outcome: DecisionOutcome = DecisionOutcome.APPROVE,
    decided_at: datetime,
    actor_situation_id: str,
    closed_periods: Collection[str] = (),
    expected_amount: Decimal | None = None,
) -> ApprovalDecision:
    """Evaluate gates G1-G6 in fixed order; first refusal wins (A4).

    Args:
        proposal: The frozen proposal snapshot under decision.
        decision_id: Caller-supplied decision identity (A16 replay key).
        approver: Decider identity (must differ from the proposer, A7).
        approver_role: Decider role claim checked against the A6 matrix.
        auth_proof: Upstream authentication proof reference (A5); missing or
            invalid proofs refuse at G1.
        auth_proof_valid: False when the proof failed upstream verification.
        outcome: ``APPROVE`` or ``REJECT`` (a REJECT still returns a decision;
            it mints no authorization).
        decided_at: Caller-supplied tz-aware decision timestamp (no clock read).
        actor_situation_id: Case the actor is bound to (A8 scope check).
        closed_periods: Periods that must never mutate (A11).
        expected_amount: P6-05 bound amount; mismatch with the proposal amount
            refuses as drift (A13/V24).

    Returns:
        The frozen decision pinning (hash, version) with deterministic ids.

    Raises:
        ApprovalRefused: At the first refusing gate, with the A19 code.
    """
    # G1 — actor authentication (claims recorded, verified upstream, A5).
    if auth_proof is None or not auth_proof.strip() or not auth_proof_valid:
        raise _refuse(
            RefusalCode.UNAUTHENTICATED_ACTOR,
            "G1",
            "No valid authentication proof presented for the decider.",
        )
    # G2 — RBAC role vs action (A6), then separation of duties (A7).
    if approver_role not in KNOWN_ROLES:
        raise _refuse(
            RefusalCode.UNKNOWN_DECIDER_ROLE,
            "G2",
            f"Unknown decider role {approver_role!r}; failing closed.",
        )
    if approver_role not in ("manager", "director"):
        raise _refuse(
            RefusalCode.APPROVE_RIGHT_DENIED,
            "G2",
            f"Role {approver_role!r} holds no approve right.",
        )
    if approver.strip() == proposal.proposer_id.strip():
        raise _refuse(
            RefusalCode.SELF_APPROVAL_DENIED,
            "G2",
            "Proposer cannot approve their own proposal (separation of duties).",
        )
    # G3 — company plus case binding (A8).
    if proposal.company_id != "meridian" or actor_situation_id != proposal.situation_id:
        raise _refuse(
            RefusalCode.CROSS_CASE_REFUSED,
            "G3",
            "Actor is not bound to this company plus case.",
        )
    # G4 — business policy (meridian.py wins on conflict; R8 forces
    # legacy-before-tier, A11 closed-before-all since it has no override).
    if proposal.period is not None and proposal.period in closed_periods:
        raise _refuse(
            RefusalCode.CLOSED_PERIOD_BLOCKED,
            "G4",
            f"Period {proposal.period!r} is closed; no override exists.",
        )
    required = required_authority(proposal.amount, is_legacy=proposal.is_legacy)
    if proposal.is_legacy and required is RefundAuthority.DIRECTOR and approver_role != "director":
        raise _refuse(
            RefusalCode.LEGACY_DIRECTOR_REQUIRED,
            "G4",
            "Legacy correction above the manager band requires a director "
            "(tier breach also recorded as OVER_TIER_AMOUNT).",
        )
    if not role_may_approve(approver_role, required):
        raise _refuse(
            RefusalCode.OVER_TIER_AMOUNT,
            "G4",
            f"Amount {proposal.amount} requires {required.value}; "
            "escalate via a fresh decision by the required tier.",
        )
    _cross_check_decider_authority(proposal, approver_role)
    if not is_valid_cobol_code(proposal.account_code):
        raise _refuse(
            RefusalCode.INVALID_ACCOUNT_CODE,
            "G4",
            f"Account code {proposal.account_code!r} is outside AccountMappings.",
        )
    # G5 — proposal validation binding (A13).
    if len(proposal.evidence_refs) < 1:
        raise _refuse(
            RefusalCode.UNVALIDATED_PROPOSAL, "G5", "Proposal cites no evidence refs."
        )
    recomputed = compute_proposal_hash(
        situation_id=proposal.situation_id,
        action=proposal.action,
        amount=proposal.amount,
        account_code=proposal.account_code,
        evidence_refs=proposal.evidence_refs,
        hypothesis_ref=proposal.hypothesis_ref,
        proposal_version=proposal.proposal_version,
    )
    if recomputed != proposal.proposal_hash:
        raise _refuse(
            RefusalCode.UNVALIDATED_PROPOSAL,
            "G5",
            "Proposal hash recomputation failed; amount or evidence drifted.",
        )
    if expected_amount is not None and expected_amount != proposal.amount:
        raise _refuse(
            RefusalCode.PROPOSAL_DRIFT_REFUSED,
            "G5",
            f"Proposal amount {proposal.amount} differs from the bound {expected_amount}.",
        )
    if proposal.amount < Decimal("0"):
        raise _refuse(
            RefusalCode.UNVALIDATED_PROPOSAL, "G5", "Proposal amount must not be negative."
        )
    # G6 — decision object shape (A14); pinning voids on swap (A15).
    decision = ApprovalDecision(
        decision_id=_require_non_empty("decision_id", decision_id),
        situation_id=proposal.situation_id,
        company_id=proposal.company_id,
        proposal_hash=proposal.proposal_hash,
        proposal_version=proposal.proposal_version,
        proposer_id=proposal.proposer_id,
        approver=_require_non_empty("approver", approver),
        approver_role=approver_role,
        outcome=outcome if isinstance(outcome, DecisionOutcome) else DecisionOutcome(outcome),
        decided_at=_require_tz_aware("decided_at", decided_at),
    )
    return decision


def _cross_check_decider_authority(proposal: ProposalSnapshot, approver_role: str) -> None:
    """Backstop the tier check against the frozen D8 lifecycle predicate.

    Builds the minimal aggregate whose variance magnitude equals the proposal
    amount and runs ``require_decider_authority_for_approval`` so the frozen
    P6-02 gate independently confirms the recorded tier conformance.

    Args:
        proposal: The snapshot under decision.
        approver_role: The decider role claim (manager or director here).

    Raises:
        ApprovalRefused: With ``OVER_TIER_AMOUNT`` when the frozen predicate
            disagrees (defence in depth; unreachable when tiers agree).
    """
    from finance.domain.financial_situation import FinancialSituation, SituationStatus

    magnitude = abs(proposal.amount)
    situation = FinancialSituation(
        situation_id=proposal.situation_id,
        expected=magnitude,
        razorpay_net=Decimal("0"),
        quickbooks=magnitude,
        legacy=magnitude,
        status=SituationStatus.PROPOSED,
        proposal_hash=proposal.proposal_hash,
        proposal_version=proposal.proposal_version,
        decider_role=approver_role,
        evidence_ids=proposal.evidence_refs,
        hypothesis_count=1,
    )
    try:
        require_decider_authority_for_approval(situation)
    except ValueError as exc:
        raise _refuse(RefusalCode.OVER_TIER_AMOUNT, "G4", f"D8 cross-check: {exc}") from exc


def assert_pin_frozen(candidate: FinancialSituation, baseline: FinancialSituation) -> None:
    """Delegate the post-approval proposal freeze to the D2 predicate.

    Args:
        candidate: The candidate aggregate whose pin must match.
        baseline: The pre-transition aggregate at or after ``APPROVED``.

    Returns:
        None when the pin is unchanged.

    Raises:
        ApprovalRefused: With ``PROPOSAL_VERSION_SWAPPED`` when the
            candidate carries a different hash or version (A15).
    """
    try:
        require_proposal_frozen(candidate, baseline)
    except ValueError as exc:
        raise _refuse(RefusalCode.PROPOSAL_VERSION_SWAPPED, "G6", str(exc)) from exc
