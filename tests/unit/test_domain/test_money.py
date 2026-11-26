"""Tests for the ``MoneyDecimal`` alias (``finance.domain._types``).

The alias is the finance-domain money boundary: it accepts ``Decimal`` and
numeric strings, and rejects ``float`` at the Pydantic boundary. The
``business.canonical_types`` value objects (Money, CurrencyCode, Percentage,
ExchangeRate) were removed with the ``business/`` package.
"""

from decimal import Decimal

import pytest
from pydantic import BaseModel, ValidationError

from finance.domain._types import MoneyDecimal

# =============================================================================
# MoneyDecimal boundary (finance.domain._types)
# =============================================================================


class _MoneyHolder(BaseModel):
    """Minimal model exercising the domain MoneyDecimal alias."""

    value: MoneyDecimal


class TestMoneyDecimalAlias:
    """The domain MoneyDecimal alias enforces the no-float money rule."""

    def test_decimal_accepted(self) -> None:
        """MoneyDecimal accepts a Decimal value."""
        holder = _MoneyHolder(value=Decimal("123.45"))
        assert isinstance(holder.value, Decimal)

    def test_str_accepted(self) -> None:
        """MoneyDecimal accepts a string representation."""
        holder = _MoneyHolder(value="123.45")
        assert isinstance(holder.value, Decimal)

    def test_float_rejected(self) -> None:
        """MoneyDecimal rejects float values at the Pydantic boundary."""
        with pytest.raises(ValidationError, match="Float values are not allowed"):
            _MoneyHolder(value=123.45)

    def test_none_rejected(self) -> None:
        """MoneyDecimal rejects None (money fields are non-nullable here)."""
        with pytest.raises(ValidationError):
            _MoneyHolder(value=None)
