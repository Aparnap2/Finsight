"""P4.3 deterministic capability executor: evidence-only read path."""

from agents.capabilities.capabilities import (
    AdapterBundle,
    BaseCapability,
    ExpectedStateCapability,
    GmailSearchCapability,
    QBTransactionCapability,
    StripePaymentCapability,
    StripeRefundsCapability,
)
from agents.capabilities.executor import DEFAULT_TIMEOUT_SECONDS, CapabilityExecutor
from agents.capabilities.registry import CapabilityRegistry
from agents.capabilities.types import (
    MAX_EXECUTOR_CALLS,
    CapabilityLiteral,
    CapabilityOutcome,
    CapabilityRequest,
    ExecutorRejectedError,
    args_fingerprint,
    is_allowlisted,
)

__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "MAX_EXECUTOR_CALLS",
    "Capabilities",
    "AdapterBundle",
    "BaseCapability",
    "CapabilityExecutor",
    "CapabilityLiteral",
    "CapabilityOutcome",
    "CapabilityRegistry",
    "CapabilityRequest",
    "ExecutorRejectedError",
    "ExpectedStateCapability",
    "GmailSearchCapability",
    "QBTransactionCapability",
    "StripePaymentCapability",
    "StripeRefundsCapability",
    "args_fingerprint",
    "is_allowlisted",
]

Capabilities: tuple[str, ...] = (
    "get_stripe_payment",
    "get_stripe_refunds",
    "get_qb_transaction",
    "get_expected_state",
    "search_gmail",
)
"""Frozen capability names in allowlist order (documentation aid)."""
