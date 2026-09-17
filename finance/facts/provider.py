"""Provider-net fact plus the five-term decomposition function.

``ProviderNetFact`` carries the window-level Razorpay decomposition:
gross captured minus fee slice minus refunds minus signed adjustments
minus not-yet-settled pending. The ``net`` property and
:func:`decompose_provider_net` encode that equation once so the engine
and the tests share a single implementation (FS-231 nets to 972500).
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from finance.domain._types import MoneyDecimal
from finance.facts._guards import (
    reject_non_decimal_money_value,
    require_decimal,
    require_inr_currency,
    require_tz_aware,
)
from finance.facts.provenance import FactProvenance

_MONEY_FIELDS = ("gross", "fee", "refund", "adjustment", "pending")
"""The five Decimal-only legs of the provider decomposition."""


class ProviderNetFact(BaseModel):
    """One window-level provider decomposition (owns: Razorpay)."""

    model_config = ConfigDict(frozen=True, strict=True)

    fact_id: str
    """Provider settlement reference for the window."""

    batch_id: str
    """Settlement window key shared with expected and books legs."""

    gross: MoneyDecimal
    """Window gross captured, INR Decimal-only."""

    fee: MoneyDecimal
    """Window fee slice sum, INR Decimal-only."""

    refund: MoneyDecimal
    """Window refund sum, INR Decimal-only."""

    adjustment: MoneyDecimal
    """Signed adjustment magnitude folded out of the net, INR."""

    pending: MoneyDecimal
    """Not-yet-settled total tracked apart, INR Decimal-only."""

    currency: str = "INR"
    """Always ``INR``; anything else is rejected, never converted."""

    observed_at: datetime
    """Timezone-aware provider timestamp."""

    provenance: FactProvenance
    """Ingest identity; anonymous legs never reconcile."""

    @field_validator("fact_id", "batch_id")
    @classmethod
    def _validate_non_empty(cls, value: str) -> str:
        """Require non-empty fact and batch identifiers."""
        if not value.strip():
            raise ValueError("fact_id and batch_id must be non-empty.")
        return value.strip()

    @field_validator(*_MONEY_FIELDS, mode="before")
    @classmethod
    def _reject_float_legs(cls, value: Any) -> Any:
        """Reject float/bool legs before type narrowing."""
        return reject_non_decimal_money_value(value, "provider leg")

    @field_validator("currency")
    @classmethod
    def _validate_currency(cls, value: str) -> str:
        """Enforce the INR-only boundary."""
        return require_inr_currency(value)

    @field_validator("observed_at")
    @classmethod
    def _validate_observed_at(cls, value: datetime) -> datetime:
        """Require a timezone-aware provider timestamp."""
        return require_tz_aware(value, "observed_at")

    @property
    def net(self) -> Decimal:
        """Return the provider net for the window.

        The five-term equation ``gross - fee - refund - adjustment -
        pending`` in exact Decimal arithmetic. Pending is subtracted
        here (tracked apart from bookable net) so FS-231 decomposes
        1000000 / 7500 / 2500 / 10000 / 7500 to exactly 972500.
        """
        return (
            self.gross - self.fee - self.refund - self.adjustment - self.pending
        )


def decompose_provider_net(
    gross: Decimal,
    fee: Decimal,
    refund: Decimal,
    adjustment: Decimal,
    pending: Decimal,
    *,
    provenance: FactProvenance,
    fact_id: str = "provider-net-1",
    batch_id: str = "BATCH-1",
    currency: str = "INR",
    observed_at: datetime | None = None,
) -> ProviderNetFact:
    """Build a provider-net fact from five Decimal legs.

    Args:
        gross: Window gross captured (Decimal only).
        fee: Window fee slice sum (Decimal only).
        refund: Window refund sum (Decimal only).
        adjustment: Signed adjustment magnitude (Decimal only).
        pending: Not-yet-settled total (Decimal only).
        provenance: Ingest identity for the built fact.
        fact_id: Settlement reference for the window.
        batch_id: Settlement window key.
        currency: Always ``INR``.
        observed_at: Provider timestamp; defaults to retrieval time.

    Returns:
        The validated ``ProviderNetFact`` netting the five legs.

    Raises:
        TypeError: If any leg arrives as bool/float.
        ValueError: If any leg is not a finite Decimal.
    """
    legs = {
        "gross": gross,
        "fee": fee,
        "refund": refund,
        "adjustment": adjustment,
        "pending": pending,
    }
    for name, leg in legs.items():
        require_decimal(name, leg)
    return ProviderNetFact(
        fact_id=fact_id,
        batch_id=batch_id,
        gross=gross,
        fee=fee,
        refund=refund,
        adjustment=adjustment,
        pending=pending,
        currency=currency,
        observed_at=observed_at if observed_at is not None else provenance.retrieved_at,
        provenance=provenance,
    )
