"""Guard seam adapter: token/intent to ExecutionGuard command (E1 just-before-PUT).

``token_to_command`` and ``intent_to_command`` map the permitted
identity onto the six fields ``ExecutionGuard.check`` inspects:
pinned identities (``situation_id`` → ``exception_id``, proposal hash →
``proposal_id``, authorization id → ``approval_id``), the idempotency
key, the Decimal-only amount, decision ``APPROVED``, and a non-terminal
state. ``run_guards`` is the call-site helper sitting just before the
PUT; it invokes the shared guard and returns the ``GuardDecision``
without editing any guard. Tokens are consumed (verified), never
minted, modified, or re-sealed here.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from finance.approval.authorization import AuthorizationToken
from finance.legacy_execution.intent import ExecutionIntent
from shared.safety.execution_guard import ExecutionGuard, GuardDecision

#: Decision spelling carried on every produced command (gate 5).
APPROVED_DECISION = "APPROVED"

#: Non-terminal lifecycle marker carried just before the PUT (gate 6).
PRE_PUT_STATE = "RESERVED"


def _require_pin(field_name: str, value: str) -> str:
    """Return a non-blank pinned identifier or raise ValueError."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Field '{field_name}' must be a non-empty string.")
    return value


def _require_amount(amount: Decimal) -> Decimal:
    """Return Decimal-only money or raise on float/bool/non-Decimal."""
    if isinstance(amount, (bool, float)):
        raise TypeError("Field 'amount' must be Decimal: float/bool money rejected.")
    if not isinstance(amount, Decimal) or not amount.is_finite():
        raise ValueError("Field 'amount' must be a finite Decimal.")
    return amount


@dataclass(frozen=True)
class GuardedExecutionCommand:
    """Pinned just-before-PUT command carrying all six gate fields.

    Extra ``decision``/``state`` attributes ride on the guard's
    duck-typed gates; the command itself carries no authority beyond
    pinning the consumed authorization.
    """

    exception_id: str
    proposal_id: str
    approval_id: str
    idempotency_key: str
    amount: Decimal
    decision: str = APPROVED_DECISION
    state: str = PRE_PUT_STATE

    def __post_init__(self) -> None:
        """Enforce pinned identifiers and Decimal-only money at the seam."""
        for field_name in (
            "exception_id",
            "proposal_id",
            "approval_id",
            "idempotency_key",
        ):
            _require_pin(field_name, getattr(self, field_name))
        _require_amount(self.amount)


def token_to_command(token: AuthorizationToken) -> GuardedExecutionCommand:
    """Map a permitted token onto the guard command (X7 pin mapping).

    Args:
        token: The E1-permitted token; read, never modified.

    Returns:
        Command with ``situation_id`` → ``exception_id``,
        ``proposal_hash`` → ``proposal_id``, ``authorization_id`` →
        ``approval_id``, ``idempotency_key`` carried over,
        ``amount_exact`` → ``amount``, decision ``APPROVED``, and a
        non-terminal state.
    """
    return GuardedExecutionCommand(
        exception_id=token.situation_id,
        proposal_id=token.proposal_hash,
        approval_id=token.authorization_id,
        idempotency_key=token.idempotency_key,
        amount=token.amount_exact,
        decision=APPROVED_DECISION,
        state=PRE_PUT_STATE,
    )


def intent_to_command(
    intent: ExecutionIntent, *, authorization_id: str
) -> GuardedExecutionCommand:
    """Map a derived intent onto the guard command.

    Args:
        intent: The E2-derived intent; read, never modified.
        authorization_id: Bound G7 token id pinning the approval.

    Returns:
        Command with the same six pinned gate fields as the token path.
    """
    return GuardedExecutionCommand(
        exception_id=intent.situation_id,
        proposal_id=intent.proposal_hash,
        approval_id=_require_pin("authorization_id", authorization_id),
        idempotency_key=intent.idempotency_key,
        amount=intent.amount_exact,
        decision=APPROVED_DECISION,
        state=PRE_PUT_STATE,
    )


def run_guards(
    command: Any, *, environment: str = "sandbox"
) -> GuardDecision:
    """Run the shared guard over one command and return its decision.

    Args:
        command: Pinned execution command (or any object carrying the
            same attribute names).
        environment: Guard environment binding; ``sandbox`` permits.

    Returns:
        The frozen ``GuardDecision``; no guard is edited.
    """
    return ExecutionGuard(environment=environment).check(command)
