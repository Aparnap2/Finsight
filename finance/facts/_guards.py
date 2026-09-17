"""Shared boundary guards for P6-03 canonical facts.

Every fact funnels money, currency, and timestamp validation through
these helpers so float amounts, non-INR currencies, and naive
datetimes are rejected identically at each boundary per section 1.7.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any


def reject_non_decimal_money(value: Any, field_name: str) -> Any:
    """Reject bool/float money before Pydantic narrows the value.

    Args:
        value: The raw candidate for a monetary field.
        field_name: Field name used in error messages.

    Returns:
        The untouched value when it is not bool/float.

    Raises:
        TypeError: If the value is a bool or float. Callers inside
            Pydantic validators must translate this to ValueError so
            it surfaces as ValidationError.
    """
    if isinstance(value, bool | float):
        raise TypeError(
            f"Field '{field_name}' must be decimal.Decimal, got "
            f"{type(value).__name__}: float/bool money is rejected."
        )
    return value


def reject_non_decimal_money_value(value: Any, field_name: str) -> Any:
    """Validator-safe wrapper translating TypeError to ValueError.

    Pydantic wraps ``ValueError`` from validators into
    ``ValidationError`` but lets ``TypeError`` escape raw, so model
    field validators must call this instead of
    :func:`reject_non_decimal_money` directly. Plain-function call
    sites keep the ``TypeError`` contract.
    """
    try:
        return reject_non_decimal_money(value, field_name)
    except TypeError as err:
        raise ValueError(str(err)) from err


def require_decimal(field_name: str, value: Any) -> Decimal:
    """Narrow a money field to a finite Decimal instance.

    Args:
        field_name: Field name used in error messages.
        value: The raw candidate for a monetary field.

    Returns:
        The value narrowed to Decimal.

    Raises:
        TypeError: If the value is bool/float.
        ValueError: If the value is not a finite Decimal.
    """
    reject_non_decimal_money(value, field_name)
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(
            f"Field '{field_name}' must be a finite Decimal, "
            f"got {type(value).__name__}."
        )
    return value


def require_inr_currency(value: str) -> str:
    """Enforce the INR-only boundary without conversion or coercion.

    Args:
        value: The candidate currency code.

    Returns:
        The ``INR`` code unchanged.

    Raises:
        ValueError: If the code is anything but ``INR``.
    """
    if value != "INR":
        raise ValueError(
            f"currency must be 'INR' (no conversion, no coercion), "
            f"got {value!r}."
        )
    return value


def require_tz_aware(value: datetime, field_name: str) -> datetime:
    """Require a timezone-aware timestamp.

    Args:
        value: The candidate timestamp.
        field_name: Field name used in error messages.

    Returns:
        The timestamp unchanged.

    Raises:
        ValueError: If the timestamp is naive.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"Field '{field_name}' must be timezone-aware.")
    return value
