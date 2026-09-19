"""P6-08 track A residual math — pure Decimal expectation gap (F20).

Residual is ``expected - legacy_total_after - pending`` in exact
Decimal arithmetic. No tolerance is folded in here: the inclusive
``abs(variance_after) <= tolerance`` boundary belongs to the minter
per F27. For FS-231: ``1000000 - 992500 - 7500 = 0``.
"""

from __future__ import annotations

from decimal import Decimal


def compute_residual(expected: Decimal, legacy_after: Decimal, pending: Decimal) -> Decimal:
    """Return the exact expectation gap ``expected - legacy_after - pending``.

    Args:
        expected: Re-read expected settlement total (Decimal 2-dp).
        legacy_after: Re-read books-side legacy total after posting.
        pending: Re-read recognised pending timing total.

    Returns:
        The exact Decimal residual; tolerance is the minter's job (F27).

    Raises:
        TypeError: When any input is not a Decimal (Decimal-only; floats
            never participate in money arithmetic).
    """
    for name, value in (
        ("expected", expected),
        ("legacy_after", legacy_after),
        ("pending", pending),
    ):
        if not isinstance(value, Decimal):
            raise TypeError(f"{name} must be Decimal, got {type(value).__name__}.")
    return expected - legacy_after - pending
