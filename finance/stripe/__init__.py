"""Stripe provider adapter (Commit 3A): raw Stripe events to canonical records.

Re-exports the deterministic, dependency-free normalizer surface. This
package imports nothing from ``apps/`` or ``agents/``.
"""

from finance.stripe.adapter import (
    PROVIDER,
    SUPPORTED_EVENT_TYPES,
    FeeKnowledge,
    FeeState,
    RefundRecord,
    StripeNormalized,
    StripePayment,
    apply_refund_event,
    fee_knowledge_of,
    payment_from_charge,
    stripe_to_normalized,
    stripe_to_record,
)

__all__ = [
    "PROVIDER",
    "SUPPORTED_EVENT_TYPES",
    "FeeKnowledge",
    "FeeState",
    "RefundRecord",
    "StripeNormalized",
    "StripePayment",
    "apply_refund_event",
    "fee_knowledge_of",
    "payment_from_charge",
    "stripe_to_normalized",
    "stripe_to_record",
]
