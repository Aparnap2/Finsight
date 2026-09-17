"""QuickBooks accounting-truth fact (the authoritative books leg).

``BooksFact`` carries the window books total plus the period-openness
flag. Two optional disambiguators ride along without weakening the
core contract: ``booked_fee`` (the booked fee-slice sum enabling the
section 3.4 fee-delta trigger) and ``duplicate_key`` (the shared
idempotency fingerprint enabling the section 3.5 duplicate trigger).
Amount equality alone never classifies a duplicate: the key must match.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from finance.domain._types import MoneyDecimal
from finance.facts._guards import (
    reject_non_decimal_money_value,
    require_inr_currency,
    require_tz_aware,
)
from finance.facts.provenance import FactProvenance


class BooksFact(BaseModel):
    """One window-level accounting truth (owns: QuickBooks)."""

    model_config = ConfigDict(frozen=True, strict=True)

    fact_id: str
    """Books entry reference for the window."""

    batch_id: str
    """Settlement window key shared with provider and legacy legs."""

    qb_total: MoneyDecimal
    """Books window total, INR Decimal-only."""

    period: str
    """Accounting period label (closed periods block reads)."""

    period_open: bool
    """True while the period still accepts reads for this window."""

    booked_fee: MoneyDecimal | None = None
    """Booked fee-slice sum enabling the fee-delta trigger, if known."""

    duplicate_key: str | None = None
    """Shared idempotency fingerprint; set only on true replays."""

    currency: str = "INR"
    """Always ``INR``; anything else is rejected, never converted."""

    posted_at: datetime
    """Timezone-aware posting timestamp."""

    provenance: FactProvenance
    """Ingest identity; anonymous legs never reconcile."""

    @field_validator("fact_id", "batch_id", "period")
    @classmethod
    def _validate_non_empty(cls, value: str) -> str:
        """Require non-empty identifiers and period labels."""
        if not value.strip():
            raise ValueError("fact_id, batch_id, and period must be non-empty.")
        return value.strip()

    @field_validator("qb_total", "booked_fee", mode="before")
    @classmethod
    def _reject_float_money(cls, value: Any) -> Any:
        """Reject float/bool money before type narrowing (None passes)."""
        if value is None:
            return value
        return reject_non_decimal_money_value(value, "books money")

    @field_validator("currency")
    @classmethod
    def _validate_currency(cls, value: str) -> str:
        """Enforce the INR-only boundary."""
        return require_inr_currency(value)

    @field_validator("posted_at")
    @classmethod
    def _validate_posted_at(cls, value: datetime) -> datetime:
        """Require a timezone-aware posting timestamp."""
        return require_tz_aware(value, "posted_at")
