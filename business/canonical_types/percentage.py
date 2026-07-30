"""Percentage value object for financial ratio and margin calculations.

Provides safe Decimal-based percentage arithmetic with factory methods
for common construction patterns (decimal, percent, fraction).
"""

# mypy: disable-error-code="misc,untyped-decorator"

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator


class Percentage(BaseModel):
    """A percentage value with internal decimal representation in [0, 1].

    Internal storage is always in decimal mode (0.12 = 12%). Factory
    methods accept percent values or fractions and normalize to decimal.

    Usage:
        margin = Percentage.from_decimal(Decimal("0.35"))   # 35%
        growth = Percentage.from_percent(Decimal("12.5"))   # 12.5%
        tax_rate = Percentage.from_fraction(
            Decimal("125000"), Decimal("1000000")
        )  # 12.5%

        print(margin)   # "35.00%"
        print(growth)   # "12.50%"
    """

    model_config = ConfigDict(frozen=True)

    value: Decimal

    @field_validator("value")
    @classmethod
    def _validate_value(cls, v: Decimal) -> Decimal:
        if not isinstance(v, Decimal):
            raise TypeError(f"Percentage value must be Decimal, got {type(v).__name__}")
        if v < 0 or v > 1:
            raise ValueError(f"Percentage must be in [0, 1], got {v}")
        quantized = v.quantize(Decimal("0.000001"))
        return quantized

    @classmethod
    def from_decimal(cls, decimal_value: Decimal) -> Percentage:
        """Create from a decimal fraction in [0, 1] (e.g., 0.15 for 15%)."""
        return cls(value=decimal_value)

    @classmethod
    def from_percent(cls, percent_value: Decimal) -> Percentage:
        """Create from a percentage value in [0, 100] (e.g., 15.0 for 15%)."""
        if not isinstance(percent_value, Decimal):
            raise TypeError(
                f"Percentage value must be Decimal, got {type(percent_value).__name__}"
            )
        if percent_value < 0 or percent_value > 100:
            raise ValueError(
                f"Percentage must be in [0, 100] when using from_percent, got {percent_value}"
            )
        return cls(value=percent_value / Decimal("100"))

    @classmethod
    def from_fraction(cls, numerator: Decimal, denominator: Decimal) -> Percentage:
        """Create from a fraction, computing numerator / denominator.

        Args:
            numerator: The top of the fraction (e.g., profit).
            denominator: The bottom of the fraction (e.g., revenue).

        Returns:
            Percentage representing the ratio.

        Raises:
            ZeroDivisionError: If denominator is zero.

        Usage:
            Percentage.from_fraction(Decimal("125000"), Decimal("1000000"))
            # → Percentage(0.125)  → "12.50%"
        """
        if denominator == 0:
            raise ZeroDivisionError(
                "Cannot compute percentage with zero denominator"
            )
        return cls(value=numerator / denominator)

    def format(self, decimals: int = 2) -> str:
        """Format as a human-readable percentage string.

        Args:
            decimals: Number of decimal places (default 2).

        Returns:
            A formatted string like "12.34%".
        """
        percent_value = self.value * Decimal("100")
        formatted = percent_value.quantize(Decimal(f"0.{'0' * decimals}"))
        return f"{formatted}%"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Percentage):
            return NotImplemented
        return self.value == other.value

    def __lt__(self, other: Percentage) -> bool:
        if not isinstance(other, Percentage):
            return NotImplemented
        return self.value < other.value

    def __le__(self, other: Percentage) -> bool:
        if not isinstance(other, Percentage):
            return NotImplemented
        return self.value <= other.value

    def __gt__(self, other: Percentage) -> bool:
        if not isinstance(other, Percentage):
            return NotImplemented
        return self.value > other.value

    def __ge__(self, other: Percentage) -> bool:
        if not isinstance(other, Percentage):
            return NotImplemented
        return self.value >= other.value

    def __str__(self) -> str:
        return self.format(2)

    def __repr__(self) -> str:
        return f"Percentage({self.value})"
