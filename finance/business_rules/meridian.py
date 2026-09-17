"""Meridian company configuration and business rules (P6-01 contract).

Frozen code-level configuration per ``docs/domain/company.md``: the
single-company ``CompanyConfiguration`` (INR, minor tolerance 100,
auto-approval limit 500000, legacy corrections always need approval)
and the ``MeridianBusinessRules`` refund tiers plus the closed-period
hard block. Threshold changes are code changes plus review, never UI
toggles. Money is ``Decimal``-only; floats are rejected.
"""

from collections.abc import Collection
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator

from finance.domain._types import MoneyDecimal


class RefundAuthority(StrEnum):
    """Who may approve a refund of a given amount."""

    AUTO = "auto"
    """Below 5000 with complete evidence: no human needed."""

    MANAGER = "manager"
    """5000 to 50000 inclusive: Finance Manager decides."""

    DIRECTOR = "director"
    """Above 50000: Director decides."""


class CompanyConfiguration(BaseModel):
    """Frozen single-company configuration for Meridian.

    Replaces the former tenant configuration: exactly one row exists
    (``meridian`` / INR). Changes require a code change plus migration
    plus review.
    """

    model_config = ConfigDict(frozen=True, strict=True)

    company_id: str = "meridian"
    """Sole company id; nothing else exists."""

    base_currency: str = "INR"
    """Immutable base currency."""

    tolerance_minor: MoneyDecimal = Decimal("100")
    """Minor variance threshold; residuals within this verify clean."""

    auto_approval_limit: MoneyDecimal = Decimal("500000")
    """Upper bound for automatic approval paths."""

    legacy_correction_requires_approval: bool = True
    """Legacy corrections always need human approval (always true)."""

    @field_validator("company_id")
    @classmethod
    def _validate_company_id(cls, value: str) -> str:
        """Enforce the single-company boundary (meridian only)."""
        if value != "meridian":
            raise ValueError(
                "company_id must be 'meridian' (single-company boundary), "
                f"got {value!r}."
            )
        return value

    @field_validator("base_currency")
    @classmethod
    def _validate_base_currency(cls, value: str) -> str:
        """Base currency is immutable INR at Meridian creation."""
        if value != "INR":
            raise ValueError(
                f"base_currency is immutable INR, got {value!r}."
            )
        return value


class MeridianBusinessRules:
    """Deterministic Meridian policy: refund tiers, legacy, closed periods."""

    REFUND_AUTO: Decimal = Decimal("5000")
    """Amounts below this auto-approve when evidence is complete."""

    REFUND_MANAGER: Decimal = Decimal("50000")
    """Amounts up to this need a Finance Manager; above need a Director."""

    def evaluate_refund(self, amount: Decimal) -> RefundAuthority:
        """Return the approving authority for a refund amount.

        Args:
            amount: The refund amount in INR (``Decimal`` only).

        Returns:
            ``AUTO`` below 5000, ``MANAGER`` from 5000 to 50000
            inclusive, ``DIRECTOR`` above 50000.

        Raises:
            TypeError: If ``amount`` is not a ``Decimal`` (floats and
                bools are rejected; money is never float).
            ValueError: If ``amount`` is negative.
        """
        if isinstance(amount, bool | float) or not isinstance(amount, Decimal):
            raise TypeError(
                "Refund amount must be decimal.Decimal, got "
                f"{type(amount).__name__}: float/bool money is rejected."
            )
        if amount < Decimal("0"):
            raise ValueError(f"Refund amount must not be negative, got {amount}.")
        if amount < self.REFUND_AUTO:
            return RefundAuthority.AUTO
        if amount <= self.REFUND_MANAGER:
            return RefundAuthority.MANAGER
        return RefundAuthority.DIRECTOR

    def legacy_always_requires_approval(self) -> bool:
        """Return True: legacy corrections always need human approval.

        No amount threshold bypasses this; a valid account code and a
        balanced batch are additionally required before execution.
        """
        return True

    def closed_period_never_modify(
        self, period: str, closed_periods: Collection[str]
    ) -> bool:
        """Return True when ``period`` is closed and must never mutate.

        Args:
            period: The accounting period of the entry (``YYYY-MM``).
            closed_periods: The set of closed periods.

        Returns:
            True when modification is hard-blocked (period closed),
            False when the period is still open.
        """
        return period in closed_periods
