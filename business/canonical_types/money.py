"""Monetary value object with currency-aware arithmetic.

The Money class is the canonical representation of a financial amount
in the platform. All monetary values use this type — never raw Decimal
and never float. Arithmetic operations enforce currency consistency
at compile-checkable boundaries.
"""

# mypy: disable-error-code="misc,untyped-decorator"

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from business.canonical_types.currency import CurrencyCode


class CurrencyMismatchError(TypeError):
    """Raised when arithmetic or comparison involves mismatched currencies.

    Attributes:
        left: The first currency code.
        right: The second currency code.
        operation: The operation being attempted (e.g., "add", "subtract").
    """

    def __init__(
        self,
        left: CurrencyCode,
        right: CurrencyCode,
        operation: str = "operation",
    ) -> None:
        self.left = left
        self.right = right
        self.operation = operation
        super().__init__(
            f"Cannot {operation} {left} and {right}: currencies do not match"
        )


class Money(BaseModel):
    """A monetary value with currency.

    Represents a financial amount in a specific currency. All arithmetic
    operations enforce currency consistency — mixing currencies raises
    CurrencyMismatchError. Float input is structurally rejected.

    The amount is stored as Decimal with at most 4 decimal places.

    Usage:
        revenue = Money(Decimal("1250000.00"), CurrencyCode("USD"))
        tax = Money(Decimal("125000.00"), CurrencyCode("USD"))
        net = revenue - tax  # Money(1125000.00, USD)

        # Currency conversion
        eur = Money(Decimal("1000000.00"), CurrencyCode("EUR"))
        usd = eur.convert(CurrencyCode("USD"), Decimal("1.08"))

        # Serialization
        Money.from_dict({"amount": "1250000.00", "currency": "USD"})
    """

    model_config = ConfigDict(frozen=True)

    amount: Decimal
    currency: CurrencyCode

    @field_validator("amount")
    @classmethod
    def _validate_amount(cls, v: Decimal) -> Decimal:
        """Ensure amount is Decimal with at most 4 decimal places."""
        if not isinstance(v, Decimal):
            raise TypeError(f"Money amount must be Decimal, got {type(v).__name__}")
        quantized = v.quantize(Decimal("0.0001"))
        if quantized != v:
            raise ValueError(
                f"Money amount precision exceeds 4 decimal places: {v}"
            )
        return quantized

    # ── Arithmetic Operations ─────────────────────────────────────────────

    def __add__(self, other: Money) -> Money:
        """Add two Money values. Currency must match."""
        if not isinstance(other, Money):
            return NotImplemented
        if self.currency != other.currency:
            raise CurrencyMismatchError(self.currency, other.currency, "add")
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def __sub__(self, other: Money) -> Money:
        """Subtract two Money values. Currency must match."""
        if not isinstance(other, Money):
            return NotImplemented
        if self.currency != other.currency:
            raise CurrencyMismatchError(self.currency, other.currency, "subtract")
        return Money(amount=self.amount - other.amount, currency=self.currency)

    def __mul__(self, factor: Decimal | int) -> Money:
        """Multiply by a scalar (Decimal or int).

        Raises:
            TypeError: If factor is not Decimal or int (e.g., float).
        """
        if isinstance(factor, float):
            raise TypeError(
                "Cannot multiply Money by float. Use Decimal for precision."
            )
        if not isinstance(factor, (Decimal, int)):
            return NotImplemented
        result = self.amount * Decimal(str(factor))
        return Money(amount=result, currency=self.currency)

    def __rmul__(self, factor: Decimal | int) -> Money:
        """Reverse multiplication: scalar * Money."""
        return self.__mul__(factor)

    def __neg__(self) -> Money:
        """Negate the monetary amount."""
        return Money(amount=-self.amount, currency=self.currency)

    def __abs__(self) -> Money:
        """Absolute value of the monetary amount."""
        return Money(amount=abs(self.amount), currency=self.currency)

    def __bool__(self) -> bool:
        """A Money is truthy if its amount is non-zero."""
        return self.amount != Decimal("0")

    # ── Comparison Operations ─────────────────────────────────────────────

    def __lt__(self, other: Money) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        if self.currency != other.currency:
            raise CurrencyMismatchError(self.currency, other.currency, "compare")
        return self.amount < other.amount

    def __le__(self, other: Money) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        if self.currency != other.currency:
            raise CurrencyMismatchError(self.currency, other.currency, "compare")
        return self.amount <= other.amount

    def __gt__(self, other: Money) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        if self.currency != other.currency:
            raise CurrencyMismatchError(self.currency, other.currency, "compare")
        return self.amount > other.amount

    def __ge__(self, other: Money) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        if self.currency != other.currency:
            raise CurrencyMismatchError(self.currency, other.currency, "compare")
        return self.amount >= other.amount

    # ── Currency Conversion ───────────────────────────────────────────────

    def convert(self, target_currency: CurrencyCode, rate: Decimal) -> Money:
        """Convert this monetary amount to another currency.

        Args:
            target_currency: The target currency to convert to.
            rate: The exchange rate (1 unit of current currency = rate
                  units of target currency).

        Returns:
            A new Money in the target currency.
        """
        converted = (self.amount * rate).quantize(Decimal("0.0001"))
        return Money(amount=converted, currency=target_currency)

    # ── Serialization ─────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, str]:
        """Serialize to a JSON-safe dictionary.

        Amount is serialized as a string to preserve Decimal precision.
        """
        return {
            "amount": str(self.amount),
            "currency": str(self.currency),
        }

    def to_json(self) -> str:
        """Serialize to a JSON string."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Money:
        """Construct Money from a dictionary.

        Expects keys: 'amount' (str or Decimal) and 'currency' (str).
        """
        amount_value = data.get("amount", "0")
        if isinstance(amount_value, str):
            amount = Decimal(amount_value)
        elif isinstance(amount_value, Decimal):
            amount = amount_value
        else:
            amount = Decimal(str(amount_value))
        currency = CurrencyCode(code=str(data.get("currency", "")))
        return cls(amount=amount, currency=currency)

    def __str__(self) -> str:
        return f"{self.amount} {self.currency}"

    def __repr__(self) -> str:
        return f"Money({self.amount}, {self.currency})"
