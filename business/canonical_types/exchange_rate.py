"""Exchange rate value object for currency conversion.

An ExchangeRate represents the conversion factor between two currencies
on a given date, with automatic inverse computation and a convert method
for applying the rate to Money amounts.
"""

# mypy: disable-error-code="misc,untyped-decorator"

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from functools import cached_property
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from business.canonical_types.currency import CurrencyCode
from business.canonical_types.money import CurrencyMismatchError, Money


class ExchangeRate(BaseModel):
    """An exchange rate between two currencies on a given date.

    The rate is expressed as: 1 unit of from_currency = rate units of
    to_currency. For example, ExchangeRate(USD, EUR, 0.92, date(2026, 7, 15))
    means 1 USD = 0.92 EUR.

    The inverse rate is automatically computed as a cached property.

    Usage:
        eur_to_usd = ExchangeRate(
            from_currency=CurrencyCode("EUR"),
            to_currency=CurrencyCode("USD"),
            rate=Decimal("1.08"),
            date=date(2026, 7, 15),
        )
        revenue_eur = Money(Decimal("1000000.00"), CurrencyCode("EUR"))
        revenue_usd = eur_to_usd.convert(revenue_eur)

        inverse = eur_to_usd.inverse  # Cached ExchangeRate(USD, EUR, ...)
    """

    model_config = ConfigDict(frozen=True)

    from_currency: CurrencyCode
    to_currency: CurrencyCode
    rate: Decimal
    date: date

    @field_validator("rate")
    @classmethod
    def _validate_rate(cls, v: Decimal) -> Decimal:
        if not isinstance(v, Decimal):
            raise TypeError(f"Exchange rate must be Decimal, got {type(v).__name__}")
        if v <= 0:
            raise ValueError(f"Exchange rate must be positive, got {v}")
        quantized = v.quantize(Decimal("0.00000001"))
        if quantized != v:
            raise ValueError(
                f"Exchange rate precision exceeds 8 decimal places: {v}"
            )
        return quantized

    @field_validator("from_currency", "to_currency")
    @classmethod
    def _validate_currency(cls, v: CurrencyCode) -> CurrencyCode:
        if not isinstance(v, CurrencyCode):
            raise TypeError(
                f"Currency must be a CurrencyCode instance, got {type(v).__name__}"
            )
        return v

    def _check_currencies_differ(self) -> None:
        """Validate that from_currency differs from to_currency."""
        if self.from_currency == self.to_currency:
            raise ValueError(
                f"Cannot have exchange rate from {self.from_currency} "
                f"to itself"
            )

    def model_post_init(self, __context: Any) -> None:
        """Post-initialization validation."""
        self._check_currencies_differ()

    @cached_property
    def inverse(self) -> ExchangeRate:
        """The inverse exchange rate (to_currency → from_currency).

        Computed as 1 / rate with 8 decimal place precision and cached
        for subsequent access.
        """
        return ExchangeRate(
            from_currency=self.to_currency,
            to_currency=self.from_currency,
            rate=(Decimal("1") / self.rate).quantize(Decimal("0.00000001")),
            date=self.date,
        )

    def convert(self, amount: Money) -> Money:
        """Convert a Money amount from from_currency to to_currency.

        Args:
            amount: A Money value whose currency matches from_currency.

        Returns:
            A Money value in to_currency.

        Raises:
            CurrencyMismatchError: If amount.currency != self.from_currency.
        """
        if amount.currency != self.from_currency:
            raise CurrencyMismatchError(
                amount.currency,
                self.from_currency,
                "exchange rate conversion",
            )
        return amount.convert(self.to_currency, self.rate)

    def to_dict(self) -> dict[str, str]:
        """Serialize to a JSON-safe dictionary."""
        return {
            "from": str(self.from_currency),
            "to": str(self.to_currency),
            "rate": str(self.rate),
            "date": self.date.isoformat(),
            "inverse_rate": str(self.inverse.rate),
        }

    def to_json(self) -> str:
        """Serialize to a JSON string."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExchangeRate:
        """Construct ExchangeRate from a dictionary.

        Expected keys: 'from', 'to', 'rate', 'date'.
        """
        return cls(
            from_currency=CurrencyCode(code=str(data["from"])),
            to_currency=CurrencyCode(code=str(data["to"])),
            rate=Decimal(str(data["rate"])),
            date=date.fromisoformat(str(data["date"])),
        )

    def __str__(self) -> str:
        return (
            f"1 {self.from_currency} = {self.rate} {self.to_currency} "
            f"({self.date})"
        )

    def __repr__(self) -> str:
        return (
            f"ExchangeRate({self.from_currency}, {self.to_currency}, "
            f"{self.rate}, {self.date})"
        )
