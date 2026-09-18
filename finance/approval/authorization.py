"""G7 execution-authorization mint and verify predicates (P6-06, mint only).

``mint_authorization`` binds exactly one approved proposal version to one
execution identity (action, exact amount, account code, scope) plus the
P6-07 idempotency key and a caller-supplied expiry window. Minting is
deterministic: identical inputs yield byte-identical tokens, so replays
never create a second authorization (A16). No lifecycle transition runs
here and no execution is performed; effect deduplication belongs to P6-07.

``verify_authorization`` is a pure predicate: it checks binding digest
integrity, case binding, hash/version pin, expiry, and scope without
mutating anything. Check order is fixed: integrity, case, pin, expiry,
scope; the first failure wins.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator

from finance.approval.decision import (
    ApprovalDecision,
    DecisionOutcome,
    ProposalSnapshot,
    canonical_amount,
)
from finance.approval.refusals import ApprovalRefused, RefusalCode


def _digest(canonical: str) -> str:
    """Return the sha256 hex digest of a canonical encoding."""
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _require_tz_aware(field_name: str, value: datetime) -> datetime:
    """Return the timestamp or raise ValueError when naive."""
    if not isinstance(value, datetime):
        raise TypeError(f"Field '{field_name}' must be a datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"Field '{field_name}' must be timezone-aware.")
    return value


def binding_digest_for(
    *,
    authorization_id: str,
    company_id: str,
    situation_id: str,
    proposal_hash: str,
    proposal_version: int,
    action: str,
    amount_exact: Decimal,
    account_code: str,
    idempotency_key: str,
    issued_at: datetime,
    expires_at: datetime,
    scope_batch: str | None,
) -> str:
    """Compute the tamper-evident binding digest over every bound field.

    Args:
        authorization_id: The deterministic authorization id.
        company_id: The bound company.
        situation_id: The bound case.
        proposal_hash: The pinned proposal hash.
        proposal_version: The pinned proposal version.
        action: The bound execution action.
        amount_exact: The bound exact amount.
        account_code: The bound account code.
        idempotency_key: The P6-07 idempotency key.
        issued_at: Caller-supplied tz-aware issue time.
        expires_at: Caller-supplied tz-aware expiry.
        scope_batch: Optional bound batch/window scope.

    Returns:
        Lowercase sha256 hex digest; any bound-field tamper breaks it.
    """
    canonical = "|".join(
        [
            authorization_id,
            company_id,
            situation_id,
            proposal_hash,
            str(proposal_version),
            action,
            canonical_amount(amount_exact),
            account_code,
            idempotency_key,
            issued_at.isoformat(),
            expires_at.isoformat(),
            scope_batch or "",
        ]
    )
    return _digest(canonical)


class AuthorizationToken(BaseModel):
    """Frozen single-version execution authorization bound by G7 (A17)."""

    model_config = ConfigDict(frozen=True, strict=True)

    authorization_id: str
    """Deterministic id (one approved version yields at most one id)."""

    proposal_hash: str
    """Pinned proposal hash this token authorizes."""

    proposal_version: int
    """Pinned proposal version this token authorizes."""

    company_id: str
    """Bound company (``meridian``)."""

    situation_id: str
    """Bound case."""

    action: str
    """Bound execution action."""

    amount_exact: Decimal
    """Bound exact amount (Decimal-only)."""

    account_code: str
    """Bound account code."""

    idempotency_key: str
    """P6-07 key deterministic in (company, hash, version)."""

    issued_at: datetime
    """Caller-supplied tz-aware issue time."""

    expires_at: datetime
    """Caller-supplied tz-aware expiry."""

    amount_ceiling: Decimal
    """Scope limit: maximum executable amount (equals ``amount_exact``)."""

    scope_batch: str | None = None
    """Optional bound batch/window scope."""

    binding_digest: str = ""
    """Tamper-evident digest over every bound field (A17 integrity)."""

    @field_validator("issued_at", "expires_at")
    @classmethod
    def _check_tz(cls, value: datetime) -> datetime:
        """Require timezone-aware token timestamps."""
        return _require_tz_aware("token time", value)


def mint_authorization(
    decision: ApprovalDecision,
    *,
    action: str,
    amount_exact: Decimal,
    account_code: str,
    issued_at: datetime,
    expires_at: datetime,
    scope_batch: str | None = None,
    proposal: ProposalSnapshot | None = None,
) -> AuthorizationToken:
    """Mint the G7 authorization for one APPROVED decision (A17).

    Args:
        decision: The G1-G6 APPROVED decision pinning (hash, version).
        action: Execution action bound into the token.
        amount_exact: Exact executable amount bound into the token.
        account_code: Account code bound into the token.
        issued_at: Caller-supplied tz-aware issue time (no clock read).
        expires_at: Caller-supplied tz-aware expiry (must be after issue).
        scope_batch: Optional batch/window scope bound into the token.
        proposal: Optional snapshot cross-checked against the decision pin
            and the execution identity (hash, version, case, amount,
            account must all agree).

    Returns:
        The frozen token; identical inputs yield byte-identical tokens.

    Raises:
        ApprovalRefused: ``DECISION_REJECTED`` when the outcome is not
            APPROVE (policy-NO mints nothing); ``PROPOSAL_VERSION_SWAPPED``,
            ``CROSS_CASE_REFUSED``, or ``PROPOSAL_DRIFT_REFUSED`` when the
            optional proposal cross-check disagrees.
        ValueError: When the expiry window is not forward.
    """
    if decision.outcome is not DecisionOutcome.APPROVE:
        raise ApprovalRefused(
            RefusalCode.DECISION_REJECTED,
            "G7",
            "Policy refused: a REJECT decision mints no authorization.",
        )
    _require_tz_aware("issued_at", issued_at)
    _require_tz_aware("expires_at", expires_at)
    if expires_at <= issued_at:
        raise ValueError("Field 'expires_at' must be after 'issued_at'.")
    if proposal is not None:
        if (
            proposal.proposal_hash != decision.proposal_hash
            or proposal.proposal_version != decision.proposal_version
        ):
            raise ApprovalRefused(
                RefusalCode.PROPOSAL_VERSION_SWAPPED,
                "G7",
                "Decision pin does not match the proposal version presented.",
            )
        if (
            proposal.situation_id != decision.situation_id
            or proposal.company_id != decision.company_id
        ):
            raise ApprovalRefused(
                RefusalCode.CROSS_CASE_REFUSED,
                "G7",
                "Decision scope does not match the proposal case.",
            )
        if proposal.amount != amount_exact or proposal.account_code != account_code:
            raise ApprovalRefused(
                RefusalCode.PROPOSAL_DRIFT_REFUSED,
                "G7",
                "Execution identity differs from the approved proposal binding.",
            )
    if not isinstance(action, str) or not action.strip():
        raise ValueError("Field 'action' must be a non-empty string.")
    if isinstance(amount_exact, bool) or not isinstance(amount_exact, Decimal):
        raise TypeError("Field 'amount_exact' must be decimal.Decimal.")
    authorization_id = f"authz_{_digest('|'.join([decision.approval_id, action.strip()]))[:16]}"
    token = AuthorizationToken(
        authorization_id=authorization_id,
        proposal_hash=decision.proposal_hash,
        proposal_version=decision.proposal_version,
        company_id=decision.company_id,
        situation_id=decision.situation_id,
        action=action.strip(),
        amount_exact=amount_exact,
        account_code=account_code,
        idempotency_key=decision.idempotency_key,
        issued_at=issued_at,
        expires_at=expires_at,
        amount_ceiling=amount_exact,
        scope_batch=scope_batch,
        binding_digest="",
    )
    digest = binding_digest_for(
        authorization_id=token.authorization_id,
        company_id=token.company_id,
        situation_id=token.situation_id,
        proposal_hash=token.proposal_hash,
        proposal_version=token.proposal_version,
        action=token.action,
        amount_exact=token.amount_exact,
        account_code=token.account_code,
        idempotency_key=token.idempotency_key,
        issued_at=token.issued_at,
        expires_at=token.expires_at,
        scope_batch=token.scope_batch,
    )
    return token.model_copy(update={"binding_digest": digest})


def verify_authorization(
    token: AuthorizationToken,
    *,
    company_id: str,
    situation_id: str,
    proposal_hash: str,
    proposal_version: int,
    action: str,
    amount_exact: Decimal,
    account_code: str,
    scope_batch: str | None,
    at: datetime,
) -> None:
    """Verify a token against the presented execution context (A18).

    Fixed check order: integrity, case, pin, expiry, scope. Pure predicate:
    permits return None, refusals raise, nothing mutates.

    Args:
        token: The authorization token presented for use.
        company_id: Presented company scope.
        situation_id: Presented case scope.
        proposal_hash: Presented pinned hash.
        proposal_version: Presented pinned version.
        action: Presented execution action.
        amount_exact: Presented exact amount.
        account_code: Presented account code.
        scope_batch: Presented batch/window scope.
        at: Caller-supplied tz-aware use time (no clock read).

    Returns:
        None when every binding holds.

    Raises:
        ApprovalRefused: ``TOKEN_FORGED`` (digest break), ``CROSS_CASE_REFUSED``
            (case/company escape), ``PROPOSAL_VERSION_SWAPPED`` (version swap),
            ``PIN_SKEW_HASH`` (same-version hash skew), ``AUTHORIZATION_EXPIRED``
            (past expiry), or ``AUTHORIZATION_SCOPE_ESCAPE`` (scope escape).
        ValueError: When ``at`` is naive.
    """
    expected_digest = binding_digest_for(
        authorization_id=token.authorization_id,
        company_id=token.company_id,
        situation_id=token.situation_id,
        proposal_hash=token.proposal_hash,
        proposal_version=token.proposal_version,
        action=token.action,
        amount_exact=token.amount_exact,
        account_code=token.account_code,
        idempotency_key=token.idempotency_key,
        issued_at=token.issued_at,
        expires_at=token.expires_at,
        scope_batch=token.scope_batch,
    )
    if expected_digest != token.binding_digest:
        raise ApprovalRefused(
            RefusalCode.TOKEN_FORGED, "G7", "Token binding digest fails verification."
        )
    if company_id != token.company_id or situation_id != token.situation_id:
        raise ApprovalRefused(
            RefusalCode.CROSS_CASE_REFUSED,
            "G7",
            "Token presented outside its bound company plus case.",
        )
    if proposal_version != token.proposal_version:
        raise ApprovalRefused(
            RefusalCode.PROPOSAL_VERSION_SWAPPED,
            "G7",
            "Token version does not match the presented proposal version.",
        )
    if proposal_hash != token.proposal_hash:
        raise ApprovalRefused(
            RefusalCode.PIN_SKEW_HASH,
            "G7",
            "Token hash does not match the presented proposal hash.",
        )
    _require_tz_aware("at", at)
    if at > token.expires_at:
        raise ApprovalRefused(
            RefusalCode.AUTHORIZATION_EXPIRED,
            "G7",
            "Token presented after expires_at; renew via a fresh decision.",
        )
    if (
        action != token.action
        or amount_exact != token.amount_exact
        or amount_exact > token.amount_ceiling
        or account_code != token.account_code
        or scope_batch != token.scope_batch
    ):
        raise ApprovalRefused(
            RefusalCode.AUTHORIZATION_SCOPE_ESCAPE,
            "G7",
            "Token presented outside its bound scope limits.",
        )


def assert_single_decision(
    existing: ApprovalDecision, candidate: ApprovalDecision
) -> ApprovalDecision:
    """Enforce one-pin-one-decision idempotency for identical replays (A16).

    Args:
        existing: The recorded decision for the pin.
        candidate: The newly delivered decision for the same pin.

    Returns:
        ``existing`` when the candidate is an identical replay (same
        decision id and outcome): no second object is created.

    Raises:
        ApprovalRefused: ``DUPLICATE_DECISION`` when a differing decision
            arrives on the same (situation, hash, version) pin.
        ValueError: When the pins differ (not a replay candidate at all).
    """
    if (
        existing.situation_id != candidate.situation_id
        or existing.proposal_hash != candidate.proposal_hash
        or existing.proposal_version != candidate.proposal_version
    ):
        raise ValueError("Not a replay candidate: proposal pins differ.")
    if existing.decision_id == candidate.decision_id and existing.outcome == candidate.outcome:
        return existing
    raise ApprovalRefused(
        RefusalCode.DUPLICATE_DECISION,
        "G6",
        "A differing decision already exists for this proposal pin.",
    )
