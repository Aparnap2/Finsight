"""Shared type aliases for finance domain models.

All monetary values use ``decimal.Decimal`` — never ``float``.
"""

from decimal import Decimal
from typing import Annotated

from pydantic import BeforeValidator


def _reject_float_money(v: object) -> object:
    """Reject float values for monetary fields — only Decimal, int, str, or None."""
    if isinstance(v, float):
        raise ValueError(
            "Float values are not allowed for monetary fields. "
            "Use decimal.Decimal, int, or str instead."
        )
    return v


MoneyDecimal = Annotated[Decimal, BeforeValidator(_reject_float_money)]
"""Type alias for monetary values that rejects ``float`` at the Pydantic boundary."""
