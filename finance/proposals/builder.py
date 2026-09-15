"""Rule-based proposal builder (P3.3): drafts only, authorizes nothing.

``build_proposal`` recomputes ``amount`` in exact ``Decimal`` arithmetic
from canonical ``PaymentRecord`` legs — ``amount`` is never accepted as
an argument — and routes the frozen exception type to its action:

- refund-lag (``I-REFUND-LAG``) → ``CREATE_CORRECTING_ENTRY``,
  Dr ``4100-refunds`` / Cr ``1100-ar`` for the abs net diff;
- duplicate (``I-DUPLICATE``) → ``VOID_DUPLICATE``,
  Dr ``4000-sales`` / Cr ``1100-ar`` (sale-reversal lineage, audit only);
- fee-mismatch (``I-FEE-DRIFT``) → proposal-only, never booked: raises
  ``UnsupportedActionError`` so the adapter is never reached.

Evidence gates mirror the spec: empty evidence is rejected, and the
owning aggregate must already sit at ``EVIDENCE_VERIFIED`` with the
cited ids present in its sealed set. ``mutate_proposal`` never edits:
it returns a new ``Proposal`` at ``version + 1`` chained via
``supersedes`` with a recomputed hash.

Only the Python standard library plus ``finance.*`` are used. This
module imports nothing from ``apps/``, ``agents/``, or ``shared/``.
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import logging
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from finance.accounting.errors import UnsupportedActionError
from finance.exceptions.aggregate import ExceptionAggregate
from finance.exceptions.states import ExceptionState
from finance.proposals.proposal import Proposal, ProposalAction, compute_content_hash
from finance.reconciliation.models import ExceptionCode, PaymentRecord

logger = logging.getLogger(__name__)

#: Journal-line conventions shared with the sandbox chart of accounts.
DEBIT_REFUNDS = "4100-refunds"
CREDIT_AR = "1100-ar"
DEBIT_SALES = "4000-sales"

_REFUND_LAG_CODE = ExceptionCode.PARTIAL_REFUND_ACCOUNTING_LAG.value
_DUPLICATE_CODE = ExceptionCode.DUPLICATE_LEDGER_ENTRY.value
_FEE_MISMATCH_CODE = ExceptionCode.FEE_MISMATCH.value

_MUTABLE_FIELDS = frozenset(
    {"action", "amount", "debit_account", "credit_account", "evidence_ids", "rationale"}
)


class ProposalBuildError(ValueError):
    """Base class for deterministic proposal-build rejections."""


class UnverifiedEvidenceError(ProposalBuildError):
    """Raised when evidence is not sealed at ``EVIDENCE_VERIFIED``."""


class EmptyEvidenceError(ProposalBuildError):
    """Raised when a proposal cites zero evidence (I5 violation)."""


def _proposal_id_for(tenant_id: str, exception_id: str) -> str:
    """Derive a deterministic tenant-namespaced proposal id.

    Args:
        tenant_id: Owning tenant scope (namespaces the id).
        exception_id: Owning exception aggregate identity.

    Returns:
        ``prop_<16 hex>`` stable for identical inputs, distinct across
        tenants for the same exception id.
    """
    digest = hashlib.sha256(f"{tenant_id}|{exception_id}".encode()).hexdigest()
    return f"prop_{digest[:16]}"


def _require_verified_snapshot(snapshot: ExceptionAggregate) -> None:
    """Enforce the EVIDENCE_VERIFIED pre-proposal gate.

    Raises:
        TypeError: If the snapshot is not an ``ExceptionAggregate``.
        UnverifiedEvidenceError: If its state is not ``EVIDENCE_VERIFIED``.
    """
    if not isinstance(snapshot, ExceptionAggregate):
        raise TypeError(
            f"exception_snapshot must be an ExceptionAggregate, got {type(snapshot).__name__}."
        )
    if snapshot.state is not ExceptionState.EVIDENCE_VERIFIED:
        raise UnverifiedEvidenceError(
            f"Evidence not verified for {snapshot.exception_id}: "
            f"state is {snapshot.state.value}, EVIDENCE_VERIFIED required."
        )


def _require_evidence_ids(
    evidence_ids: Sequence[str], snapshot: ExceptionAggregate
) -> tuple[str, ...]:
    """Validate cited evidence against the sealed aggregate set.

    Raises:
        EmptyEvidenceError: If no evidence is cited.
        UnverifiedEvidenceError: If a cited id is blank or outside the
            aggregate's sealed ``evidence_ids`` set.
    """
    cited = tuple(evidence_ids) if not isinstance(evidence_ids, str) else (evidence_ids,)
    if len(cited) == 0:
        raise EmptyEvidenceError("Proposal requires at least one EVIDENCE_VERIFIED id.")
    for evidence_id in cited:
        if not isinstance(evidence_id, str) or not evidence_id.strip():
            raise UnverifiedEvidenceError("Every cited evidence id must be non-empty str.")
    sealed = set(snapshot.evidence_ids)
    for evidence_id in cited:
        if evidence_id not in sealed:
            raise UnverifiedEvidenceError(
                f"Evidence {evidence_id!r} is not in the verified set for {snapshot.exception_id}."
            )
    return cited


def _require_records(
    canonical_records: Sequence[PaymentRecord], snapshot: ExceptionAggregate
) -> tuple[PaymentRecord, ...]:
    """Validate canonical legs: types, tenant scope, single currency.

    Raises:
        ProposalBuildError: On empty, mistyped, cross-tenant, or
            cross-currency record sets.
    """
    records = tuple(canonical_records)
    if len(records) == 0:
        raise ProposalBuildError("At least one canonical PaymentRecord is required.")
    for record in records:
        if not isinstance(record, PaymentRecord):
            raise ProposalBuildError(
                f"canonical_records must hold PaymentRecord entries, got {type(record).__name__}."
            )
    for record in records:
        if record.tenant_id != snapshot.tenant_id:
            raise ProposalBuildError(
                f"Record tenant {record.tenant_id!r} does not match "
                f"snapshot tenant {snapshot.tenant_id!r}."
            )
    currencies = {record.currency for record in records}
    if len(currencies) != 1:
        raise ProposalBuildError(f"Canonical records span currencies {sorted(currencies)}.")
    return records


def build_proposal(
    exception_snapshot: ExceptionAggregate,
    canonical_records: Sequence[PaymentRecord],
    evidence_ids: Sequence[str],
) -> Proposal:
    """Draft a v1 proposal with a deterministically recomputed amount.

    Args:
        exception_snapshot: Aggregate sealed at ``EVIDENCE_VERIFIED``.
        canonical_records: Normalized legs; the amount is recomputed
            from these in ``Decimal`` (never accepted as an argument).
        evidence_ids: Cited evidence ids (non-empty, subset of the
            snapshot's sealed set).

    Returns:
        A frozen v1 ``Proposal`` with ``requires_hitl`` True.

    Raises:
        UnverifiedEvidenceError: If the snapshot is not verified or a
            cited id falls outside its sealed set.
        EmptyEvidenceError: If no evidence is cited.
        UnsupportedActionError: For fee-mismatch (proposal-only, never
            booked).
        ProposalBuildError: On bad records or non-positive amounts.
    """
    _require_verified_snapshot(exception_snapshot)
    cited = _require_evidence_ids(evidence_ids, exception_snapshot)
    records = _require_records(canonical_records, exception_snapshot)
    currency = records[0].currency
    exception_type = exception_snapshot.exception_type
    code = (
        exception_type.value if isinstance(exception_type, ExceptionCode) else str(exception_type)
    )

    if code == _FEE_MISMATCH_CODE:
        raise UnsupportedActionError(
            "Fee-mismatch is proposal-only: no sandbox write exists. "
            "Route to policy review instead."
        )
    if code == _REFUND_LAG_CODE:
        if len(records) >= 2:
            amount = abs(records[1].net - records[0].net)
        else:
            amount = abs(records[0].refund)
        if amount <= Decimal("0"):
            raise ProposalBuildError("Refund-lag diff recomputed to zero: nothing to correct.")
        action = ProposalAction.CREATE_CORRECTING_ENTRY
        debit_account, credit_account = DEBIT_REFUNDS, CREDIT_AR
        rationale = (
            f"Refund lag {exception_snapshot.exception_id}: correcting entry "
            f"{amount} {currency} (observed-expected net diff)."
        )
    elif code == _DUPLICATE_CODE:
        amount = abs(records[0].net)
        if amount <= Decimal("0"):
            raise ProposalBuildError("Duplicate net recomputed to zero: nothing to void.")
        action = ProposalAction.VOID_DUPLICATE
        debit_account, credit_account = DEBIT_SALES, CREDIT_AR
        rationale = (
            f"Duplicate {exception_snapshot.exception_id}: void duplicate entry "
            f"{amount} {currency}."
        )
    else:  # pragma: no cover - closed 3-code set enforced upstream
        raise ProposalBuildError(f"Unknown exception_type {code!r}.")

    proposal = Proposal(
        proposal_id=_proposal_id_for(exception_snapshot.tenant_id, exception_snapshot.exception_id),
        exception_id=exception_snapshot.exception_id,
        version=1,
        action=action,
        amount=amount,
        debit_account=debit_account,
        credit_account=credit_account,
        evidence_ids=cited,
        rationale=rationale,
        content_hash="",
        requires_hitl=True,
        supersedes=None,
    )
    logger.info(
        "proposal built id=%s exception=%s action=%s amount=%s",
        proposal.proposal_id,
        proposal.exception_id,
        proposal.action.value,
        str(proposal.amount),
    )
    return proposal


def mutate_proposal(proposal: Proposal, **changes: Any) -> Proposal:
    """Return a new proposal version; the input object is never edited.

    Args:
        proposal: The frozen proposal to supersede.
        **changes: Subset of ``action``, ``amount``, ``debit_account``,
            ``credit_account``, ``evidence_ids``, ``rationale``.

    Returns:
        A new ``Proposal`` at ``version + 1`` with ``supersedes`` set to
        the input's ``content_hash`` and a recomputed hash.

    Raises:
        TypeError: On unknown fields or mistyped values (``float``
            amounts rejected).
        ValueError: On empty values or version/hash tampering attempts.
    """
    if not isinstance(proposal, Proposal):
        raise TypeError(f"proposal must be a Proposal, got {type(proposal).__name__}.")
    unknown = set(changes) - _MUTABLE_FIELDS
    if unknown:
        raise TypeError(f"mutate_proposal rejects field(s) {sorted(unknown)}.")
    if "amount" in changes:
        amount_value: Any = changes["amount"]
        if isinstance(amount_value, (bool, float)):
            raise TypeError("Field 'amount' must be Decimal: float/bool money is rejected.")
        if not isinstance(amount_value, Decimal) or not amount_value.is_finite():
            raise ValueError("Field 'amount' must be a finite Decimal.")
        if amount_value <= Decimal("0"):
            raise ValueError("Field 'amount' must be positive.")
    if "action" in changes and not isinstance(changes["action"], (ProposalAction, str)):
        raise TypeError("Field 'action' must be a ProposalAction or action name.")
    for field_name in ("debit_account", "credit_account", "rationale"):
        if field_name in changes:
            value = changes[field_name]
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Field '{field_name}' must be a non-empty string.")
    if "evidence_ids" in changes:
        raw = changes["evidence_ids"]
        seq = tuple(raw) if isinstance(raw, (list, tuple)) else None
        if seq is None or len(seq) == 0:
            raise ValueError("Field 'evidence_ids' must be a non-empty tuple/list.")
        for evidence_id in seq:
            if not isinstance(evidence_id, str) or not evidence_id.strip():
                raise ValueError("Every entry of 'evidence_ids' must be non-empty str.")
        changes["evidence_ids"] = seq

    mutated = dataclasses.replace(
        proposal,
        version=proposal.version + 1,
        supersedes=proposal.content_hash,
        content_hash="",
        **changes,
    )
    logger.info(
        "proposal mutated id=%s v%s -> v%s",
        proposal.proposal_id,
        proposal.version,
        mutated.version,
    )
    return mutated


def verify_hash(proposal: Proposal) -> bool:
    """Return True when the stored hash matches the canonical fields.

    Args:
        proposal: The proposal to verify.

    Returns:
        True on an intact proposal, False on any hashed-field drift.
    """
    if not isinstance(proposal, Proposal):
        raise TypeError(f"proposal must be a Proposal, got {type(proposal).__name__}.")
    expected = compute_content_hash(
        proposal_id=proposal.proposal_id,
        exception_id=proposal.exception_id,
        version=proposal.version,
        action=proposal.action,
        amount=proposal.amount,
        debit_account=proposal.debit_account,
        credit_account=proposal.credit_account,
        evidence_ids=proposal.evidence_ids,
        rationale=proposal.rationale,
        requires_hitl=proposal.requires_hitl,
        supersedes=proposal.supersedes,
    )
    return hmac.compare_digest(expected, proposal.content_hash)
