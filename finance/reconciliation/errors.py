"""Error taxonomy for the P1 pure reconciliation core.

All errors are deterministic, dependency-free, and carry no I/O. They
distinguish five failure modes required by the frozen reconciliation
spec: float money input, cross-currency misuse, bad tolerance config,
duplicate ingestion, and broken domain invariants.

Only the Python standard library is used.
"""

from __future__ import annotations


class ReconciliationError(Exception):
    """Base class for all deterministic reconciliation errors."""


class FloatMoneyError(ReconciliationError, TypeError):
    """Raised when a monetary value arrives as ``float`` (or ``bool``).

    Every trust boundary in this package accepts ``Decimal`` (and, where
    lossless, ``int``/``str`` which are converted) but never ``float``,
    mirroring the ``MoneyDecimal`` boundary used elsewhere in FinSight.
    """


class CurrencyMismatch(ReconciliationError, TypeError):  # noqa: N818 -- frozen spec name
    """Raised when one operation mixes two different currencies.

    Attributes:
        left: The first currency code.
        right: The second currency code.
        operation: The operation being attempted (e.g. ``"reconcile"``).
    """

    def __init__(
        self,
        left: str,
        right: str,
        operation: str = "reconcile",
    ) -> None:
        """Record the mismatched pair and build the message."""
        self.left = left
        self.right = right
        self.operation = operation
        super().__init__(
            f"Cannot {operation} {left} and {right}: currencies do not match"
        )


class ToleranceError(ReconciliationError, ValueError):
    """Raised for invalid tolerance configuration or misuse.

    Examples: negative ``absolute``/``percent``, non-``Decimal`` bounds,
    or passing a non-tolerance object where a tolerance is required.
    """


class DuplicateError(ReconciliationError, ValueError):
    """Raised when strict uniqueness is violated.

    Used by uniqueness guards when the same ``idempotency_key`` is
    presented twice inside one scope that requires exactly-once handling.
    """


class InvariantViolation(ReconciliationError, ValueError):  # noqa: N818 -- frozen spec name
    """Raised when a domain invariant is broken.

    Examples: ``net != gross - fee - refund``, missing required fields,
    naive datetimes, unknown status values, or calling a classifier on
    legs that carry no break.
    """
