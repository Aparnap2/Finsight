"""Serialization helpers for Decimal money values."""
from decimal import Decimal
from typing import Any


def serialize_decimal(value: Decimal) -> str:
    return str(value)


def serialize_amounts(model: Any) -> dict[str, Any]:
    raw = model.model_dump()
    result: dict[str, Any] = {}
    for key, value in raw.items():
        if isinstance(value, Decimal):
            result[key] = str(value)
        elif isinstance(value, dict):
            result[key] = {
                k: str(v) if isinstance(v, Decimal) else v
                for k, v in value.items()
            }
        else:
            result[key] = value
    return result
