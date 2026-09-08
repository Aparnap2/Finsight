"""Provider-agnostic normalization of raw payment payloads.

Converts heterogeneous provider events (Stripe-style minor units,
ledger-style decimal strings, native ``Decimal``) into the canonical
:class:`PaymentRecord`. Responsibilities: minor-units to ``Decimal``
conversion with a currency-aware exponent table, ISO 4217 currency
guard, ``Decimal``-only enforcement (``float``/``bool`` rejected),
tz-aware timestamps normalized to UTC, and required-identifier checks.
The net invariant is enforced by ``PaymentRecord`` itself; when ``net``
is absent it is derived deterministically as ``gross - fee - refund``.

Pure and deterministic: no LLM, database, network, clock reads, or
randomness. Only the Python standard library is used.
"""

import logging
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from finance.reconciliation.errors import FloatMoneyError, InvariantViolation
from finance.reconciliation.models import PaymentRecord, PaymentStatus

logger = logging.getLogger(__name__)

_CURRENCY_PATTERN = re.compile(r"[A-Z]{3}")
_DEFAULT_EXPONENT = 2

_MINOR_EXPONENTS: dict[str, int] = {
    "BHD": 3,
    "JOD": 3,
    "KWD": 3,
    "OMR": 3,
    "TND": 3,
    "CLP": 0,
    "DJF": 0,
    "GNF": 0,
    "ISK": 0,
    "JPY": 0,
    "KMF": 0,
    "KRW": 0,
    "PYG": 0,
    "RWF": 0,
    "UGX": 0,
    "UYI": 0,
    "VND": 0,
    "VUV": 0,
    "XAF": 0,
    "XOF": 0,
    "XPF": 0,
}
"""Common ISO 4217 minor-unit exponents; any other currency defaults to 2."""

_MONEY_COMPONENTS = ("gross", "fee", "refund")


def _normalize_currency(value: Any) -> str:
    """Uppercase and validate an ISO 4217 currency code."""
    if not isinstance(value, str):
        raise InvariantViolation(
            f"Field 'currency' must be a string, got {type(value).__name__}."
        )
    code = value.strip().upper()
    if _CURRENCY_PATTERN.fullmatch(code) is None:
        raise InvariantViolation(
            f"Field 'currency' must be an ISO 4217 code, got {value!r}."
        )
    return code


def _resolve_exponent(
    currency: str, raw: Mapping[str, Any], override: int | None
) -> int:
    """Resolve the minor-unit exponent: override, payload, table, default."""
    if override is not None:
        candidate: Any = override
    else:
        candidate = raw.get("exponent")
        if candidate is None:
            return _MINOR_EXPONENTS.get(currency, _DEFAULT_EXPONENT)
    if isinstance(candidate, bool) or not isinstance(candidate, int):
        raise InvariantViolation(
            f"Minor-unit exponent must be an int, got {type(candidate).__name__}."
        )
    if candidate < 0:
        raise InvariantViolation(f"Minor-unit exponent must be >= 0, got {candidate}.")
    return candidate


def _to_decimal(value: Any, *, field_name: str, minor: bool, exponent: int) -> Decimal:
    """Convert one raw money value to ``Decimal`` without precision loss.

    Minor-unit integers are scaled by ``10 ** exponent``. Major-unit
    integers convert exactly; strings parse via ``Decimal``; ``Decimal``
    passes through. ``float``/``bool`` are rejected and non-finite
    values (NaN/Infinity) are refused.
    """
    if isinstance(value, (bool, float)):
        raise FloatMoneyError(
            f"Field '{field_name}' must be Decimal, got {type(value).__name__}: "
            "float/bool money is rejected, use decimal.Decimal."
        )
    if minor:
        if not isinstance(value, int):
            raise InvariantViolation(
                f"Field '{field_name}' is in minor units and must be an int, "
                f"got {type(value).__name__}."
            )
        return Decimal(value) / (Decimal(10) ** exponent)
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, str):
        try:
            result = Decimal(value.strip())
        except InvalidOperation as exc:
            raise InvariantViolation(
                f"Field '{field_name}' is not a parseable decimal: {value!r}."
            ) from exc
    else:
        raise InvariantViolation(
            f"Field '{field_name}' must be Decimal, int, or str, "
            f"got {type(value).__name__}."
        )
    if not result.is_finite():
        raise InvariantViolation(f"Field '{field_name}' must be finite, got {result}.")
    return result


def _parse_occurred_at(value: Any) -> datetime:
    """Require a tz-aware instant and normalize it to UTC."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise InvariantViolation(
                f"Field 'occurred_at' is not ISO-8601: {value!r}."
            ) from exc
    else:
        raise InvariantViolation(
            "Field 'occurred_at' must be a tz-aware datetime or ISO-8601 string, "
            f"got {type(value).__name__}."
        )
    tzinfo = parsed.tzinfo
    if tzinfo is None or tzinfo.utcoffset(parsed) is None:
        raise InvariantViolation("Field 'occurred_at' must be tz-aware.")
    return parsed.astimezone(UTC)


def _parse_status(value: Any) -> PaymentStatus:
    """Coerce a status name to :class:`PaymentStatus`, rejecting unknowns."""
    if isinstance(value, PaymentStatus):
        return value
    if isinstance(value, str):
        try:
            return PaymentStatus(value.strip().upper())
        except ValueError as exc:
            raise InvariantViolation(f"Unknown payment status {value!r}.") from exc
    raise InvariantViolation(
        f"Field 'status' must be a PaymentStatus or status name, "
        f"got {type(value).__name__}."
    )


def _require_text(raw: Mapping[str, Any], key: str) -> str:
    """Fetch a required non-empty string field from the raw payload."""
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InvariantViolation(f"Field '{key}' must be a non-empty string.")
    return value.strip()


def normalize(
    raw: Mapping[str, Any],
    *,
    tenant_id: str | None = None,
    amount_unit: str = "major",
    exponent: int | None = None,
) -> PaymentRecord:
    """Normalize one raw provider payload into a :class:`PaymentRecord`.

    Args:
        raw: Provider payload with ``payment_id``, ``provider``,
            ``provider_event_id``, ``idempotency_key``, money fields
            (``gross`` required; ``fee``/``refund`` default to zero;
            ``net`` derived as ``gross - fee - refund`` when absent),
            ``currency``, ``status``, and ``occurred_at``. Any money
            field also accepts a ``<name>_minor`` integer key carrying
            minor units (e.g. cents).
        tenant_id: Explicit tenant scope; overrides ``raw["tenant_id"]``.
        amount_unit: ``"major"`` (default) or ``"minor"`` for bare
            integer money fields. ``<name>_minor`` keys are always minor.
        exponent: Explicit minor-unit exponent, overriding the payload
            ``exponent`` and the currency table.

    Returns:
        The validated, UTC-normalized ``PaymentRecord``.

    Raises:
        FloatMoneyError: If any money field arrives as ``float``/``bool``.
        InvariantViolation: If required fields, currency, status,
            timestamps, or the net equation are invalid.
    """
    raw_value: object = raw
    if not isinstance(raw_value, Mapping):
        raise InvariantViolation(
            f"normalize requires a mapping payload, got {type(raw_value).__name__}."
        )
    if amount_unit not in ("major", "minor"):
        raise InvariantViolation(
            f"amount_unit must be 'major' or 'minor', got {amount_unit!r}."
        )
    currency = _normalize_currency(raw.get("currency"))
    resolved_exponent = _resolve_exponent(currency, raw, exponent)
    minor_default = amount_unit == "minor"

    amounts: dict[str, Decimal] = {}
    for name in _MONEY_COMPONENTS:
        if f"{name}_minor" in raw:
            amounts[name] = _to_decimal(
                raw[f"{name}_minor"],
                field_name=f"{name}_minor",
                minor=True,
                exponent=resolved_exponent,
            )
        elif name in raw:
            amounts[name] = _to_decimal(
                raw[name], field_name=name, minor=minor_default,
                exponent=resolved_exponent,
            )
        elif name == "gross":
            raise InvariantViolation("Field 'gross' is required.")
        else:
            amounts[name] = Decimal("0")
    if "net_minor" in raw:
        net = _to_decimal(
            raw["net_minor"], field_name="net_minor", minor=True,
            exponent=resolved_exponent,
        )
    elif "net" in raw:
        net = _to_decimal(
            raw["net"], field_name="net", minor=minor_default,
            exponent=resolved_exponent,
        )
    else:
        net = amounts["gross"] - amounts["fee"] - amounts["refund"]

    tenant_raw = tenant_id if tenant_id is not None else raw.get("tenant_id")
    if not isinstance(tenant_raw, str) or not tenant_raw.strip():
        raise InvariantViolation("Field 'tenant_id' must be a non-empty string.")
    source_reference = raw.get("source_reference")
    if source_reference is not None and not isinstance(source_reference, str):
        raise InvariantViolation("Field 'source_reference' must be a string or null.")

    record = PaymentRecord(
        payment_id=_require_text(raw, "payment_id"),
        provider=_require_text(raw, "provider"),
        provider_event_id=_require_text(raw, "provider_event_id"),
        idempotency_key=_require_text(raw, "idempotency_key"),
        gross=amounts["gross"],
        fee=amounts["fee"],
        refund=amounts["refund"],
        net=net,
        currency=currency,
        status=_parse_status(raw.get("status")),
        occurred_at=_parse_occurred_at(raw.get("occurred_at")),
        tenant_id=tenant_raw.strip(),
        source_reference=source_reference,
    )
    logger.info(
        "Normalized payment payment_id=%s provider=%s net=%s %s",
        record.payment_id,
        record.provider,
        record.net,
        record.currency,
    )
    return record
