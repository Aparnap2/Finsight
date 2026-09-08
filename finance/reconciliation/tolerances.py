"""Tenant-injected reconciliation tolerances.

Tolerances are never hardcoded: the caller injects a
``ReconciliationTolerance`` per tenant at call time. The zero-default
(``absolute == 0`` and ``percent == 0``) means exact matching unless a
tenant explicitly allows slack. ``percent`` is a fraction of the leg's
net (e.g. ``Decimal("0.005")`` is 0.5%), mirroring the tiered
absolute-plus-percent pattern of the variance-engine materiality rules.

Only the Python standard library is used.
"""

from dataclasses import dataclass
from decimal import Decimal

from finance.reconciliation.errors import FloatMoneyError, ToleranceError


@dataclass(frozen=True)
class ReconciliationTolerance:
    """Allowed amount slack for one reconciliation comparison.

    Attributes:
        absolute: Maximum allowed ``abs(difference)`` as a money amount.
        percent: Fraction of the leg net added to the allowance
            (``Decimal("0.005")`` is 0.5%). Must be non-negative.
    """

    absolute: Decimal = Decimal("0")
    percent: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        """Enforce Decimal-only, finite, non-negative bounds."""
        for field_name in ("absolute", "percent"):
            value: object = getattr(self, field_name)
            if isinstance(value, (bool, float)):
                raise FloatMoneyError(
                    f"Tolerance '{field_name}' must be Decimal, "
                    f"got {type(value).__name__}: float/bool money is rejected."
                )
            if not isinstance(value, Decimal) or not value.is_finite():
                raise ToleranceError(
                    f"Tolerance '{field_name}' must be a finite Decimal, "
                    f"got {type(value).__name__}."
                )
            if value < Decimal("0"):
                raise ToleranceError(
                    f"Tolerance '{field_name}' must be non-negative, got {value}."
                )

    def apply(self, base: Decimal) -> Decimal:
        """Compute the allowed ``abs(difference)`` for a leg net ``base``.

        The allowance is ``absolute + abs(percent * base)`` in exact
        ``Decimal`` arithmetic, so a zero net still honors ``absolute``
        while a large net scales with ``percent``.

        Args:
            base: The reference leg net (sign-insensitive).

        Returns:
            The maximum acceptable absolute difference.

        Raises:
            ToleranceError: If ``base`` is not a finite ``Decimal``.
            FloatMoneyError: If ``base`` is ``float`` or ``bool``.
        """
        base_value: object = base
        if isinstance(base_value, (bool, float)):
            raise FloatMoneyError(
                f"Tolerance base must be Decimal, got {type(base_value).__name__}."
            )
        if not isinstance(base_value, Decimal) or not base_value.is_finite():
            raise ToleranceError(
                "Tolerance base must be a finite Decimal, "
                f"got {type(base_value).__name__}."
            )
        return self.absolute + abs(self.percent * base_value)

    def allows(self, difference: Decimal, base: Decimal) -> bool:
        """Return True when ``abs(difference)`` fits within the allowance.

        Boundary-inclusive: a difference exactly equal to the allowance
        is allowed (``TOLERANCE_MATCHED``), anything above is a break.

        Args:
            difference: Signed ``observed - expected`` net difference.
            base: The reference leg net (sign-insensitive).
        """
        difference_value: object = difference
        if isinstance(difference_value, (bool, float)):
            raise FloatMoneyError(
                "Tolerance difference must be Decimal, "
                f"got {type(difference_value).__name__}."
            )
        if not isinstance(difference_value, Decimal) or not difference_value.is_finite():
            raise ToleranceError(
                "Tolerance difference must be a finite Decimal, "
                f"got {type(difference_value).__name__}."
            )
        return abs(difference_value) <= self.apply(base)
