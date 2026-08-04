"""Tests for the monetary value objects — Money, CurrencyCode, Percentage, ExchangeRate.

The money layer is the canonical representation of financial amounts in the
platform: always ``decimal.Decimal``, never ``float``. Each test proves an
invariant of that layer: construction, precision limits, currency-aware
arithmetic, serialization, and boundary rejection.
"""

import json
from datetime import date
from decimal import Decimal

import pytest
from pydantic import BaseModel, ValidationError

from business.canonical_types import (
    CurrencyCode,
    CurrencyMismatchError,
    ExchangeRate,
    Money,
    Percentage,
)
from finance.domain._types import MoneyDecimal

# =============================================================================
# CurrencyCode
# =============================================================================


class TestCurrencyCode:
    """ISO 4217 currency code value object."""

    def test_valid_code_constructs(self) -> None:
        """USD is a valid ISO 4217 code."""
        code = CurrencyCode(code="USD")
        assert code.code == "USD"

    def test_lowercase_normalized_to_upper(self) -> None:
        """Lowercase input is normalized to uppercase."""
        assert CurrencyCode(code="eur").code == "EUR"

    def test_whitespace_stripped(self) -> None:
        """Surrounding whitespace is stripped before validation."""
        assert CurrencyCode(code=" usd ").code == "USD"

    def test_two_letter_code_rejected(self) -> None:
        """A two-letter code is rejected."""
        with pytest.raises(ValidationError, match="exactly 3 characters"):
            CurrencyCode(code="US")

    def test_four_letter_code_rejected(self) -> None:
        """A four-letter code is rejected."""
        with pytest.raises(ValidationError, match="exactly 3 characters"):
            CurrencyCode(code="USDE")

    def test_non_alpha_code_rejected(self) -> None:
        """A code containing digits is rejected."""
        with pytest.raises(ValidationError, match="only letters"):
            CurrencyCode(code="US1")

    def test_unknown_code_rejected(self) -> None:
        """A well-formed but unknown code is rejected."""
        with pytest.raises(ValidationError, match="Unknown currency code"):
            CurrencyCode(code="XYZ")

    def test_str_returns_code(self) -> None:
        """The string representation is the three-letter code."""
        assert str(CurrencyCode(code="GBP")) == "GBP"

    def test_equality_same_code(self) -> None:
        """Two codes with the same normalized value are equal."""
        assert CurrencyCode(code="usd") == CurrencyCode(code="USD")

    def test_frozen_prevents_mutation(self) -> None:
        """CurrencyCode is immutable."""
        code = CurrencyCode(code="USD")
        with pytest.raises(ValidationError):
            code.code = "EUR"  # type: ignore[misc]

    def test_missing_code_rejected(self) -> None:
        """A code is required."""
        with pytest.raises(ValidationError):
            CurrencyCode()  # type: ignore[call-arg]

    def test_empty_code_rejected(self) -> None:
        """An empty code is rejected."""
        with pytest.raises(ValidationError, match="exactly 3 characters"):
            CurrencyCode(code="")


# =============================================================================
# Money
# =============================================================================


class TestMoneyConstruction:
    """Money construction invariants."""

    def test_decimal_amount_constructs(self) -> None:
        """A Decimal amount constructs a Money value."""
        money = Money(amount=Decimal("1250000.00"), currency=CurrencyCode(code="USD"))
        assert isinstance(money.amount, Decimal)

    def test_amount_quantized_to_four_decimal_places(self) -> None:
        """Amounts are normalized to at most 4 decimal places."""
        money = Money(amount=Decimal("123.45"), currency=CurrencyCode(code="USD"))
        assert money.amount == Decimal("123.4500")

    def test_int_amount_coerced_to_decimal(self) -> None:
        """Integer amounts are coerced to Decimal."""
        money = Money(amount=10, currency=CurrencyCode(code="USD"))
        assert isinstance(money.amount, Decimal)
        assert money.amount == Decimal("10.0000")

    def test_str_amount_coerced_to_decimal(self) -> None:
        """String amounts are coerced to Decimal (JSON-safe path)."""
        money = Money(amount="123.45", currency=CurrencyCode(code="USD"))
        assert isinstance(money.amount, Decimal)
        assert money.amount == Decimal("123.4500")

    def test_float_amount_coerces_to_decimal(self) -> None:
        """Float amounts are coerced to Decimal — money is never float."""
        money = Money(amount=123.45, currency=CurrencyCode(code="USD"))
        assert isinstance(money.amount, Decimal)
        assert money.amount == Decimal("123.4500")

    def test_amount_beyond_four_decimal_places_rejected(self) -> None:
        """A five-decimal-place amount violates the precision invariant."""
        with pytest.raises(ValidationError, match="precision exceeds 4"):
            Money(amount=Decimal("123.45678"), currency=CurrencyCode(code="USD"))

    def test_zero_amount_constructs(self) -> None:
        """A zero amount is a valid Money value."""
        money = Money(amount=Decimal("0.00"), currency=CurrencyCode(code="USD"))
        assert money.amount == Decimal("0.0000")

    def test_negative_amount_constructs(self) -> None:
        """Negative amounts are valid Money values."""
        money = Money(amount=Decimal("-5000.00"), currency=CurrencyCode(code="USD"))
        assert money.amount == Decimal("-5000.0000")

    def test_large_amount_constructs(self) -> None:
        """Very large amounts are preserved without precision loss."""
        money = Money(amount=Decimal("999999999999999.99"), currency=CurrencyCode(code="USD"))
        assert money.amount == Decimal("999999999999999.9900")

    def test_missing_amount_rejected(self) -> None:
        """Amount is a required field."""
        with pytest.raises(ValidationError):
            Money(currency=CurrencyCode(code="USD"))  # type: ignore[call-arg]

    def test_frozen_prevents_amount_mutation(self) -> None:
        """Money is immutable — amount cannot be reassigned."""
        money = Money(amount=Decimal("10.00"), currency=CurrencyCode(code="USD"))
        with pytest.raises(ValidationError):
            money.amount = Decimal("20.00")  # type: ignore[misc]


class TestMoneyArithmetic:
    """Currency-aware Money arithmetic invariants."""

    def _usd(self, amount: str) -> Money:
        """Build a USD Money value."""
        return Money(amount=Decimal(amount), currency=CurrencyCode(code="USD"))

    def test_add_same_currency(self) -> None:
        """Adding same-currency Money values sums the amounts."""
        total = self._usd("100.00") + self._usd("200.00")
        assert total.amount == Decimal("300.0000")
        assert total.currency == CurrencyCode(code="USD")

    def test_sub_same_currency(self) -> None:
        """Subtracting same-currency Money values yields the delta."""
        delta = self._usd("200.00") - self._usd("150.00")
        assert delta.amount == Decimal("50.0000")

    def test_add_mismatched_currency_raises(self) -> None:
        """Adding Money values with different currencies is rejected."""
        eur = Money(amount=Decimal("1"), currency=CurrencyCode(code="EUR"))
        with pytest.raises(CurrencyMismatchError, match="currencies do not match"):
            self._usd("1.00") + eur

    def test_sub_mismatched_currency_raises(self) -> None:
        """Subtracting Money values with different currencies is rejected."""
        eur = Money(amount=Decimal("1"), currency=CurrencyCode(code="EUR"))
        with pytest.raises(CurrencyMismatchError, match="currencies do not match"):
            self._usd("1.00") - eur

    def test_compare_mismatched_currency_raises(self) -> None:
        """Comparing Money values with different currencies is rejected."""
        eur = Money(amount=Decimal("1"), currency=CurrencyCode(code="EUR"))
        with pytest.raises(CurrencyMismatchError, match="currencies do not match"):
            _ = self._usd("1.00") < eur

    def test_mul_by_decimal(self) -> None:
        """Multiplying Money by a Decimal factor scales the amount."""
        product = self._usd("10.00") * Decimal("2.5")
        assert product.amount == Decimal("25.0000")

    def test_mul_by_int(self) -> None:
        """Multiplying Money by an int factor scales the amount."""
        product = self._usd("10.00") * 3
        assert product.amount == Decimal("30.0000")

    def test_mul_by_float_rejected(self) -> None:
        """Multiplying Money by a float is rejected — Decimal only."""
        with pytest.raises(TypeError, match="Cannot multiply Money by float"):
            self._usd("10.00") * 1.5  # type: ignore[operator]

    def test_rmul_by_int(self) -> None:
        """Reverse multiplication by an int works."""
        product = 2 * self._usd("10.00")
        assert product.amount == Decimal("20.0000")

    def test_negation(self) -> None:
        """Negating Money flips the sign of the amount."""
        assert (-self._usd("10.00")).amount == Decimal("-10.0000")

    def test_absolute_value(self) -> None:
        """abs(Money) returns a non-negative amount."""
        assert abs(self._usd("-10.00")).amount == Decimal("10.0000")

    def test_bool_truthiness(self) -> None:
        """A Money value is truthy when the amount is non-zero."""
        assert bool(self._usd("0.01")) is True
        assert bool(self._usd("0.00")) is False

    def test_ordering_comparisons(self) -> None:
        """Same-currency Money values order by amount."""
        low, high = self._usd("1.00"), self._usd("2.00")
        assert low < high
        assert low <= high
        assert high > low
        assert high >= low

    def test_equality(self) -> None:
        """Money values are equal when amount and currency match."""
        assert self._usd("1.00") == self._usd("1.00")
        assert self._usd("1.00") != self._usd("1.01")


class TestMoneyConversion:
    """Currency conversion invariants."""

    def test_convert_changes_currency(self) -> None:
        """Converting a Money value yields the target currency."""
        usd = Money(amount=Decimal("100.00"), currency=CurrencyCode(code="USD"))
        eur = usd.convert(CurrencyCode(code="EUR"), Decimal("0.92"))
        assert eur.currency == CurrencyCode(code="EUR")

    def test_convert_applies_rate(self) -> None:
        """The conversion multiplies the amount by the rate."""
        usd = Money(amount=Decimal("100.00"), currency=CurrencyCode(code="USD"))
        eur = usd.convert(CurrencyCode(code="EUR"), Decimal("0.92"))
        assert eur.amount == Decimal("92.0000")

    def test_convert_quantizes_to_four_decimal_places(self) -> None:
        """Converted amounts are quantized to 4 decimal places."""
        usd = Money(amount=Decimal("1.00"), currency=CurrencyCode(code="USD"))
        eur = usd.convert(CurrencyCode(code="EUR"), Decimal("0.92"))
        assert eur.amount == Decimal("0.9200")

    def test_convert_same_currency_keeps_amount(self) -> None:
        """Converting to the same currency is the identity on the amount."""
        usd = Money(amount=Decimal("100.00"), currency=CurrencyCode(code="USD"))
        same = usd.convert(CurrencyCode(code="USD"), Decimal("1.00"))
        assert same.amount == Decimal("100.0000")


class TestMoneySerialization:
    """Money serialization / deserialization round-trips."""

    def _usd(self, amount: str) -> Money:
        """Build a USD Money value."""
        return Money(amount=Decimal(amount), currency=CurrencyCode(code="USD"))

    def test_to_dict_serializes_amount_as_string(self) -> None:
        """Amounts serialize as strings to preserve Decimal precision."""
        data = self._usd("1250000.00").to_dict()
        assert data == {"amount": "1250000.0000", "currency": "USD"}
        assert isinstance(data["amount"], str)

    def test_to_json_round_trip(self) -> None:
        """to_json produces JSON that from_dict can reconstruct."""
        money = self._usd("1250000.00")
        parsed = json.loads(money.to_json())
        assert parsed["amount"] == "1250000.0000"
        assert parsed["currency"] == "USD"

    def test_from_dict_with_string_amount(self) -> None:
        """from_dict accepts a string amount."""
        money = Money.from_dict({"amount": "1250000.00", "currency": "USD"})
        assert money.amount == Decimal("1250000.0000")
        assert money.currency == CurrencyCode(code="USD")

    def test_from_dict_with_decimal_amount(self) -> None:
        """from_dict accepts a Decimal amount."""
        money = Money.from_dict({"amount": Decimal("42.00"), "currency": "USD"})
        assert money.amount == Decimal("42.0000")

    def test_from_dict_missing_amount_defaults_zero(self) -> None:
        """from_dict defaults a missing amount to zero."""
        money = Money.from_dict({"currency": "USD"})
        assert money.amount == Decimal("0.0000")

    def test_from_dict_round_trip(self) -> None:
        """to_dict followed by from_dict preserves the value."""
        original = self._usd("987654.32")
        rebuilt = Money.from_dict(original.to_dict())
        assert rebuilt == original

    def test_str_representation(self) -> None:
        """The string representation includes amount and currency."""
        assert str(self._usd("10.00")) == "10.0000 USD"


# =============================================================================
# Percentage
# =============================================================================


class TestPercentage:
    """Percentage value object — decimal-mode storage in [0, 1]."""

    def test_valid_decimal_constructs(self) -> None:
        """A decimal fraction in [0, 1] constructs a Percentage."""
        pct = Percentage(value=Decimal("0.12"))
        assert pct.value == Decimal("0.120000")

    def test_value_above_one_rejected(self) -> None:
        """A fraction above 1 violates the [0, 1] invariant."""
        with pytest.raises(ValidationError, match="must be in \\[0, 1\\]"):
            Percentage(value=Decimal("1.5"))

    def test_negative_value_rejected(self) -> None:
        """A negative fraction violates the [0, 1] invariant."""
        with pytest.raises(ValidationError, match="must be in \\[0, 1\\]"):
            Percentage(value=Decimal("-0.1"))

    def test_from_decimal_factory(self) -> None:
        """from_decimal builds a Percentage from a decimal fraction."""
        assert Percentage.from_decimal(Decimal("0.35")).value == Decimal("0.350000")

    def test_from_percent_factory(self) -> None:
        """from_percent converts percent points to a decimal fraction."""
        assert Percentage.from_percent(Decimal("12.5")).value == Decimal("0.125000")

    def test_from_percent_above_100_rejected(self) -> None:
        """from_percent rejects values outside [0, 100]."""
        with pytest.raises(ValueError, match="must be in \\[0, 100\\]"):
            Percentage.from_percent(Decimal("150"))

    def test_from_percent_float_rejected(self) -> None:
        """from_percent rejects float input."""
        with pytest.raises(TypeError, match="must be Decimal"):
            Percentage.from_percent(12.5)  # type: ignore[arg-type]

    def test_from_fraction(self) -> None:
        """from_fraction computes numerator / denominator."""
        pct = Percentage.from_fraction(Decimal("125000"), Decimal("1000000"))
        assert pct.value == Decimal("0.125000")

    def test_from_fraction_zero_denominator_raises(self) -> None:
        """from_fraction rejects a zero denominator."""
        with pytest.raises(ZeroDivisionError, match="zero denominator"):
            Percentage.from_fraction(Decimal("1"), Decimal("0"))

    def test_format_output(self) -> None:
        """format renders a human-readable percentage string."""
        assert Percentage.from_percent(Decimal("12.34")).format() == "12.34%"

    def test_format_custom_decimals(self) -> None:
        """format honors the decimals argument."""
        assert Percentage.from_decimal(Decimal("0.5")).format(0) == "50%"

    def test_comparisons(self) -> None:
        """Percentages order by their stored value."""
        low = Percentage.from_decimal(Decimal("0.10"))
        high = Percentage.from_decimal(Decimal("0.20"))
        assert low < high
        assert high > low
        assert low <= low

    def test_str_renders_percentage(self) -> None:
        """The string representation is a formatted percentage."""
        assert str(Percentage.from_decimal(Decimal("0.35"))) == "35.00%"


# =============================================================================
# ExchangeRate
# =============================================================================


class TestExchangeRate:
    """Exchange rate value object with inverse and conversion support."""

    def _rate(self) -> ExchangeRate:
        """Build a EUR→USD exchange rate."""
        return ExchangeRate(
            from_currency=CurrencyCode(code="EUR"),
            to_currency=CurrencyCode(code="USD"),
            rate=Decimal("1.08"),
            date=date(2026, 7, 15),
        )

    def test_valid_rate_constructs(self) -> None:
        """A positive Decimal rate constructs an ExchangeRate."""
        rate = self._rate()
        assert rate.rate == Decimal("1.08000000")

    def test_zero_rate_rejected(self) -> None:
        """A zero rate violates the positivity invariant."""
        with pytest.raises(ValidationError, match="must be positive"):
            ExchangeRate(
                from_currency=CurrencyCode(code="EUR"),
                to_currency=CurrencyCode(code="USD"),
                rate=Decimal("0"),
                date=date(2026, 7, 15),
            )

    def test_negative_rate_rejected(self) -> None:
        """A negative rate violates the positivity invariant."""
        with pytest.raises(ValidationError, match="must be positive"):
            ExchangeRate(
                from_currency=CurrencyCode(code="EUR"),
                to_currency=CurrencyCode(code="USD"),
                rate=Decimal("-1.08"),
                date=date(2026, 7, 15),
            )

    def test_float_rate_coerced_to_decimal(self) -> None:
        """Float rates are coerced to Decimal — rates are monetary, never float."""
        rate = ExchangeRate(
            from_currency=CurrencyCode(code="EUR"),
            to_currency=CurrencyCode(code="USD"),
            rate=1.08,
            date=date(2026, 7, 15),
        )
        assert isinstance(rate.rate, Decimal)
        assert rate.rate == Decimal("1.08000000")

    def test_rate_beyond_eight_decimal_places_rejected(self) -> None:
        """Rates are limited to 8 decimal places."""
        with pytest.raises(ValidationError, match="precision exceeds 8"):
            ExchangeRate(
                from_currency=CurrencyCode(code="EUR"),
                to_currency=CurrencyCode(code="USD"),
                rate=Decimal("1.123456789"),
                date=date(2026, 7, 15),
            )

    def test_same_currency_rejected(self) -> None:
        """An exchange rate cannot be from a currency to itself."""
        with pytest.raises(ValidationError, match="to itself"):
            ExchangeRate(
                from_currency=CurrencyCode(code="USD"),
                to_currency=CurrencyCode(code="USD"),
                rate=Decimal("1.00"),
                date=date(2026, 7, 15),
            )

    def test_inverse_rate(self) -> None:
        """The inverse rate swaps currencies and inverts the rate."""
        inverse = self._rate().inverse
        assert inverse.from_currency == CurrencyCode(code="USD")
        assert inverse.to_currency == CurrencyCode(code="EUR")
        assert inverse.rate == (Decimal("1") / Decimal("1.08")).quantize(Decimal("0.00000001"))

    def test_convert_matching_currency(self) -> None:
        """convert applies the rate to a matching-currency amount."""
        eur = Money(amount=Decimal("100.00"), currency=CurrencyCode(code="EUR"))
        usd = self._rate().convert(eur)
        assert usd.currency == CurrencyCode(code="USD")
        assert usd.amount == Decimal("108.0000")

    def test_convert_mismatched_currency_raises(self) -> None:
        """convert rejects amounts whose currency differs from from_currency."""
        gbp = Money(amount=Decimal("100.00"), currency=CurrencyCode(code="GBP"))
        with pytest.raises(CurrencyMismatchError):
            self._rate().convert(gbp)

    def test_to_dict_and_from_dict_round_trip(self) -> None:
        """Serialization preserves rate, currencies, and date."""
        original = self._rate()
        rebuilt = ExchangeRate.from_dict(original.to_dict())
        assert rebuilt == original

    def test_str_representation(self) -> None:
        """The string representation shows the conversion factor."""
        assert "1 EUR = 1.08000000 USD" in str(self._rate())


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
