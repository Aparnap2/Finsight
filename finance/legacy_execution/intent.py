"""Deterministic execution intent for P6-07 E2 (X14-X17 projection).

``derive_intent`` projects the permitted token field-for-field into an
``ExecutionIntent``: action, exact amount, account code, company, case,
scope batch, idempotency key, hash, and version. No arithmetic, no
rounding, no enrichment, no LLM input: any value not present in the
token is absent from the intent. Closed-vocabulary and paise-level
drift violations refuse with ``AUTHORIZATION_SCOPE_ESCAPE`` before any
artifact exists.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from finance.approval.authorization import AuthorizationToken
from finance.approval.refusals import ApprovalRefused, RefusalCode

#: Closed E2 action vocabulary (X15). Only the token-bound FS-231 action
#: is listed by the spec; anything else refuses at the intent gate.
ALLOWED_ACTIONS = frozenset({"REPROCESS_LEGACY_RECORD"})


class ExecutionIntent(BaseModel):
    """Single deterministic correction intent projected from a token."""

    model_config = ConfigDict(frozen=True, strict=True)

    action: str
    """Bound execution action (closed vocabulary, X15)."""

    amount_exact: Decimal
    """Bound exact amount, Decimal-only, copied unchanged (X14)."""

    account_code: str
    """Bound account code, copied exactly (X14)."""

    company_id: str
    """Bound company (``meridian``)."""

    situation_id: str
    """Bound case."""

    scope_batch: str | None = None
    """Pinned batch scope; absent means E3 derives it from the key (X17)."""

    idempotency_key: str
    """P6-07 key deterministic in (company, hash, version)."""

    execution_id: str
    """Always equals ``idempotency_key``; never regenerated."""

    proposal_hash: str
    """Pinned proposal hash."""

    proposal_version: int
    """Pinned proposal version."""


def derive_intent(
    token: AuthorizationToken,
    *,
    scope_batch_override: str | None = None,
    presented_amount: Decimal | None = None,
    presented_action: str | None = None,
    presented_account_code: str | None = None,
) -> ExecutionIntent:
    """Project the token into the single deterministic intent (X14).

    Args:
        token: The E1-permitted token; consumed, never modified.
        scope_batch_override: Optional asserted batch: must equal the
            token pin when given, else the scope escaped (X17).
        presented_amount: Optional asserted amount: must equal the token
            amount to the cent; one paise of drift refuses (X15).
        presented_action: Optional asserted action: must equal the token
            action exactly (X15).
        presented_account_code: Optional asserted code: must equal the
            token code exactly (X15).

    Returns:
        The frozen intent: token values out for token values in.

    Raises:
        ApprovalRefused: ``AUTHORIZATION_SCOPE_ESCAPE`` at gate ``E2``
            on closed-vocabulary or drift violations.
    """

    def _refuse(message: str) -> ApprovalRefused:
        """Build the E2 scope-escape refusal signal."""
        return ApprovalRefused(
            RefusalCode.AUTHORIZATION_SCOPE_ESCAPE, "E2", message
        )

    if token.action not in ALLOWED_ACTIONS:
        raise _refuse(f"Intent action {token.action!r} outside closed vocabulary.")
    if presented_action is not None and presented_action != token.action:
        raise _refuse("Presented action differs from the token-bound action.")
    if presented_amount is not None and presented_amount != token.amount_exact:
        raise _refuse("Presented amount drifts from the token-bound amount.")
    if (
        presented_account_code is not None
        and presented_account_code != token.account_code
    ):
        raise _refuse("Presented account code differs from the token-bound code.")
    if scope_batch_override is not None and scope_batch_override != token.scope_batch:
        raise _refuse("Presented batch scope differs from the token-bound batch.")
    return ExecutionIntent(
        action=token.action,
        amount_exact=token.amount_exact,
        account_code=token.account_code,
        company_id=token.company_id,
        situation_id=token.situation_id,
        scope_batch=token.scope_batch,
        idempotency_key=token.idempotency_key,
        execution_id=token.idempotency_key,
        proposal_hash=token.proposal_hash,
        proposal_version=token.proposal_version,
    )
