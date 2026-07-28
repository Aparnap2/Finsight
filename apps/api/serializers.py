"""Serialization helpers for Decimal money values."""
from decimal import Decimal


def serialize_decimal(value: Decimal) -> str:
    return str(value)


def serialize_amounts(model) -> dict:
    raw = model.model_dump()
    result = {}
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
