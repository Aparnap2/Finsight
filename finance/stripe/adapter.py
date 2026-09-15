"""Stripe event normalizer: raw Stripe deliveries to canonical payment facts.

Commit 3A owns the field-extraction edge ONLY. This module answers a single
boring question per event — "what financial fact does this event represent?"
— and performs no suspicion scoring, accounting decisions, proposal logic,
or reconciliation. Wiring those facts into the reconciler is Commit 3B and
lives outside this module.

Supported events (and nothing else):

* ``charge.succeeded`` — a capture fact: gross, fee knowledge, zero refund.
* ``refund.created`` — a refund-delta fact: parent charge link plus one
  positive delta. The delta is folded into a canonical net only through
  :class:`StripePayment`, which keys refund records by
  ``(provider, refund_id)`` so replaying the same lifecycle event never
  subtracts twice.

Fee tri-state:

``FeeKnowledge`` is ``KNOWN(amount)`` / ``UNKNOWN`` / ``NOT_APPLICABLE``.
A missing fee is NEVER coerced to a known zero: ``UNKNOWN`` (fee keys absent
or null) and ``KNOWN(Decimal("0"))`` (fee key explicitly zero) are distinct
states even though both carry ``Decimal("0")`` in the emitted
:class:`PaymentRecord`. The P0.2 ``PaymentRecord`` shape (see
``finance/reconciliation/models.py``) has no tri-state field — its ``fee``
stays ``Decimal``-only — so the record holds an arithmetic placeholder while
``FeeKnowledge`` is authoritative. Consumers MUST consult
:func:`fee_knowledge_of` (or :class:`StripeNormalized`) and MUST NOT infer
fee presence from ``record.fee == 0``.

PROPOSED (models.py, P0.2 follow-up — DO NOT APPLY HERE, Commit 3A must not
rewrite models.py):

.. code-block:: python

    @dataclass(frozen=True)
    class PaymentRecord:
        ...
        fee: Decimal  # unchanged: arithmetic placeholder, Decimal-only
        fee_knowledge: FeeKnowledge  # NEW, default FeeKnowledge.unknown()
        # Net invariant unchanged (net == gross - fee - refund); when
        # fee_knowledge.state is not KNOWN, fee MUST be Decimal("0") and
        # downstream MUST treat net as fee-exclusive via fee_knowledge.

Money, identity, and time rules:

* ``Decimal``-only money; minor units scale by the Stripe exponent (0 for
  zero-decimal currencies, else 2). ``float``/``bool`` money is rejected.
* Refund deltas are strictly positive; a delta (or cumulative total) above
  gross is rejected; refund currency must equal charge currency.
* Canonical identity is ``(tenant_id, provider, payment_id)`` — never
  amount, timestamp, or name. ``tenant_id`` is an explicit caller-supplied
  scope; there is no default tenant.
* Timestamps normalize to UTC; tz-naive instants are rejected.
* A missing ledger reference is a downstream concern (``LEDGER_RECORD_MISSING``
  is emitted later); this normalizer sets ``source_reference`` to ``None``
  and just emits the record.

Only the Python standard library plus ``finance.reconciliation`` is used.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from finance.reconciliation.errors import (
    CurrencyMismatch,
    FloatMoneyError,
    InvariantViolation,
)
from finance.reconciliation.models import PaymentRecord, PaymentStatus
from finance.reconciliation.normalizer import normalize

logger = logging.getLogger(__name__)

PROVIDER = "stripe"
"""Provider literal stamped on every record this adapter emits."""

SUPPORTED_EVENT_TYPES: tuple[str, str] = ("charge.succeeded", "refund.created")
"""Allow-listed Stripe event types; anything else is malformed for 3A."""

_CURRENCY_PATTERN = re.compile(r"[A-Z]{3}")

_ZERO_DECIMAL_CURRENCIES = frozenset(
    {
        "BIF",
        "CLP",
        "DJF",
        "GNF",
        "ISK",
        "JPY",
        "KMF",
        "KRW",
        "MGA",
        "PYG",
        "RWF",
        "UGX",
        "UYI",
        "VND",
        "VUV",
        "XAF",
        "XOF",
        "XPF",
    }
)
"""Stripe zero-decimal currencies (exponent 0); every other currency is 2.

This mirrors Stripe API semantics (not the wider ISO table): minor-unit
amounts divide by ``10 ** exponent`` with no float involved.
"""


class FeeState(StrEnum):
    """Provenance of the fee fact carried by a Stripe event."""

    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class FeeKnowledge:
    """Tri-state fee fact: known amount, unknown, or not applicable.

    ``KNOWN`` carries the exact ``Decimal`` amount (including an explicit
    zero). ``UNKNOWN`` means the event carried no fee information and MUST
    NOT be treated as zero. ``NOT_APPLICABLE`` marks legs that never carry
    fee information (refund deltas; the fee belongs to the charge leg).
    """

    state: FeeState
    amount: Decimal | None = None

    def __post_init__(self) -> None:
        """Enforce Decimal-only amounts for KNOWN and null otherwise."""
        state_value: object = self.state
        if not isinstance(state_value, FeeState):
            raise InvariantViolation(
                f"Field 'state' must be a FeeState, got {type(state_value).__name__}."
            )
        amount_value: object = self.amount
        if state_value is FeeState.KNOWN:
            if isinstance(amount_value, (bool, float)):
                raise FloatMoneyError(
                    "Field 'amount' must be Decimal, "
                    f"got {type(amount_value).__name__}: "
                    "float/bool money is rejected, use decimal.Decimal."
                )
            if not isinstance(amount_value, Decimal) or not amount_value.is_finite():
                raise InvariantViolation(
                    "Field 'amount' must be a finite Decimal when fee is KNOWN, "
                    f"got {type(amount_value).__name__}."
                )
        elif amount_value is not None:
            raise InvariantViolation(
                f"Field 'amount' must be null when fee is {state_value.value}, "
                f"got {amount_value!r}."
            )

    @classmethod
    def known(cls, amount: Decimal) -> FeeKnowledge:
        """Build a KNOWN fee fact around an exact Decimal amount."""
        return cls(state=FeeState.KNOWN, amount=amount)

    @classmethod
    def unknown(cls) -> FeeKnowledge:
        """Build an UNKNOWN fee fact (no fee information in the event)."""
        return cls(state=FeeState.UNKNOWN, amount=None)

    @classmethod
    def not_applicable(cls) -> FeeKnowledge:
        """Build a NOT_APPLICABLE fee fact (refund-delta legs)."""
        return cls(state=FeeState.NOT_APPLICABLE, amount=None)


@dataclass(frozen=True)
class RefundRecord:
    """One idempotent refund delta, keyed by ``(provider, refund_id)``.

    Identity is the provider-side refund identifier only — never amount,
    timestamp, or name — so lifecycle replays collapse to a no-op instead
    of subtracting twice.
    """

    provider: str
    refund_id: str
    payment_id: str
    amount: Decimal
    currency: str
    tenant_id: str
    provider_event_id: str
    occurred_at: datetime

    def __post_init__(self) -> None:
        """Enforce identifiers, Decimal-only positive amounts, UTC time."""
        for field_name in (
            "provider",
            "refund_id",
            "payment_id",
            "tenant_id",
            "provider_event_id",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise InvariantViolation(f"Field '{field_name}' must be a non-empty string.")
        amount_value: object = self.amount
        if isinstance(amount_value, (bool, float)):
            raise FloatMoneyError(
                "Field 'amount' must be Decimal, "
                f"got {type(amount_value).__name__}: "
                "float/bool money is rejected, use decimal.Decimal."
            )
        if not isinstance(amount_value, Decimal) or not amount_value.is_finite():
            raise InvariantViolation(
                f"Field 'amount' must be a finite Decimal, got {type(amount_value).__name__}."
            )
        if amount_value <= Decimal("0"):
            raise InvariantViolation(
                f"Field 'amount' must be a positive refund delta, got {amount_value}."
            )
        currency_value: object = self.currency
        if not isinstance(currency_value, str):
            raise InvariantViolation("Field 'currency' must be a string.")
        if _CURRENCY_PATTERN.fullmatch(currency_value) is None:
            raise InvariantViolation(
                f"Field 'currency' must be an ISO 4217 code, got {currency_value!r}."
            )
        occurred_value: object = self.occurred_at
        if not isinstance(occurred_value, datetime):
            raise InvariantViolation("Field 'occurred_at' must be a datetime.")
        tzinfo = occurred_value.tzinfo
        if tzinfo is None or tzinfo.utcoffset(occurred_value) is None:
            raise InvariantViolation("Field 'occurred_at' must be tz-aware.")

    @property
    def identity(self) -> tuple[str, str]:
        """Refund-record identity: ``(provider, refund_id)``."""
        return (self.provider, self.refund_id)


@dataclass(frozen=True)
class StripeNormalized:
    """One normalized Stripe fact: canonical record plus its provenance.

    ``record`` is the P0.2 ``PaymentRecord`` (``fee`` is a Decimal-only
    arithmetic placeholder when the fee is not known). ``fee`` is the
    authoritative tri-state fee fact. ``refund`` carries the refund-record
    identity for ``refund.created`` legs and is ``None`` for charges.
    """

    record: PaymentRecord
    fee: FeeKnowledge
    refund: RefundRecord | None


def _require_text(value: Any, *, field_name: str) -> str:
    """Require a non-empty string and return it stripped."""
    if not isinstance(value, str) or not value.strip():
        raise InvariantViolation(f"Field '{field_name}' must be a non-empty string.")
    return value.strip()


def _require_mapping(value: Any, *, field_name: str) -> Mapping[str, Any]:
    """Require a mapping payload section."""
    if not isinstance(value, Mapping):
        raise InvariantViolation(
            f"Field '{field_name}' must be a mapping, got {type(value).__name__}."
        )
    return value


def _normalize_currency(value: Any) -> str:
    """Uppercase and validate an ISO 4217 currency code."""
    if not isinstance(value, str):
        raise InvariantViolation(f"Field 'currency' must be a string, got {type(value).__name__}.")
    code = value.strip().upper()
    if _CURRENCY_PATTERN.fullmatch(code) is None:
        raise InvariantViolation(f"Field 'currency' must be an ISO 4217 code, got {value!r}.")
    return code


def _minor_to_decimal(value: Any, *, field_name: str, currency: str) -> Decimal:
    """Convert a Stripe minor-unit int to an exact ``Decimal`` major amount."""
    if isinstance(value, (bool, float)):
        raise FloatMoneyError(
            f"Field '{field_name}' must be Decimal, got {type(value).__name__}: "
            "float/bool money is rejected, use decimal.Decimal."
        )
    if not isinstance(value, int):
        raise InvariantViolation(
            f"Field '{field_name}' is in minor units and must be an int, "
            f"got {type(value).__name__}."
        )
    exponent = 0 if currency in _ZERO_DECIMAL_CURRENCIES else 2
    return Decimal(value) / (Decimal(10) ** exponent)


def _minor_field(obj: Mapping[str, Any], currency: str, *names: str, field_name: str) -> int | None:
    """Read the first present minor-unit key; ``None`` means absent-or-null.

    Priority order is the argument order. An explicit ``None`` is treated
    exactly like an absent key (UNKNOWN), while an explicit ``0`` is a real
    zero. Non-int, non-null values are malformed.
    """
    for name in names:
        if name not in obj:
            continue
        value = obj[name]
        if value is None:
            return None
        if isinstance(value, (bool, float)):
            raise FloatMoneyError(
                f"Field '{name}' must be Decimal, got {type(value).__name__}: "
                "float/bool money is rejected, use decimal.Decimal."
            )
        if not isinstance(value, int):
            raise InvariantViolation(
                f"Field '{name}' is in minor units and must be an int, got {type(value).__name__}."
            )
        _minor_to_decimal(value, field_name=field_name, currency=currency)
        return value
    return None


def _parse_occurred_at(value: Any) -> datetime:
    """Require a Stripe instant (unix seconds or ISO-8601) normalized to UTC."""
    if isinstance(value, bool):
        raise InvariantViolation("Field 'created' must be unix seconds or ISO-8601.")
    if isinstance(value, int):
        try:
            return datetime.fromtimestamp(value, tz=UTC)
        except (OverflowError, OSError, ValueError) as exc:
            raise InvariantViolation(
                f"Field 'created' is not a valid unix timestamp: {value!r}."
            ) from exc
    if isinstance(value, float):
        raise InvariantViolation(
            f"Field 'created' must be integer unix seconds, got float {value!r}."
        )
    if isinstance(value, str):
        text = value.strip()
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise InvariantViolation(f"Field 'created' is not ISO-8601: {value!r}.") from exc
        tzinfo = parsed.tzinfo
        if tzinfo is None or tzinfo.utcoffset(parsed) is None:
            raise InvariantViolation("Field 'created' must be tz-aware.")
        return parsed.astimezone(UTC)
    raise InvariantViolation(
        "Field 'created' must be integer unix seconds or an ISO-8601 string, "
        f"got {type(value).__name__}."
    )


def _envelope_parts(event: Mapping[str, Any]) -> tuple[str, str, Mapping[str, Any]]:
    """Extract ``(event_id, event_type, object)`` from a Stripe envelope.

    Only field presence/shape is checked here; the event type allow-list is
    enforced by the caller. The Stripe object lives at
    ``data.object``; anything else is malformed.
    """
    if not isinstance(event, Mapping):
        raise InvariantViolation(f"Stripe event must be a mapping, got {type(event).__name__}.")
    event_id = _require_text(event.get("id"), field_name="id")
    raw_type = event.get("type")
    event_type = _require_text(raw_type, field_name="type")
    data = _require_mapping(event.get("data"), field_name="data")
    obj = _require_mapping(data.get("object"), field_name="data.object")
    return event_id, event_type, obj


def _occurred_at_of(event: Mapping[str, Any], obj: Mapping[str, Any]) -> datetime:
    """Resolve the event instant: envelope ``created``, else object ``created``."""
    if event.get("created") is not None:
        return _parse_occurred_at(event.get("created"))
    if obj.get("created") is not None:
        return _parse_occurred_at(obj.get("created"))
    raise InvariantViolation("Field 'created' is required (envelope or object).")


def _extract_fee(obj: Mapping[str, Any], currency: str) -> FeeKnowledge:
    """Extract the charge fee fact without ever coercing absence to zero.

    Priority: explicit ``application_fee_amount`` int (including ``0``),
    then an expanded ``balance_transaction`` mapping with an int ``fee``.
    Absent or null fee information yields ``UNKNOWN``.
    """
    direct = _minor_field(
        obj, currency, "application_fee_amount", field_name="application_fee_amount"
    )
    if direct is not None:
        return FeeKnowledge.known(
            _minor_to_decimal(direct, field_name="application_fee_amount", currency=currency)
        )
    txn = obj.get("balance_transaction")
    if isinstance(txn, Mapping):
        nested = _minor_field(txn, currency, "fee", field_name="balance_transaction.fee")
        if nested is not None:
            return FeeKnowledge.known(
                _minor_to_decimal(nested, field_name="balance_transaction.fee", currency=currency)
            )
    elif txn is not None and not isinstance(txn, str):
        raise InvariantViolation(
            "Field 'balance_transaction' must be an id string, null, or a mapping, "
            f"got {type(txn).__name__}."
        )
    return FeeKnowledge.unknown()


def fee_knowledge_of(event: Mapping[str, Any]) -> FeeKnowledge:
    """Return the authoritative tri-state fee fact for one Stripe event.

    Charge legs report ``KNOWN`` when the event carries an explicit fee and
    ``UNKNOWN`` otherwise. Refund-delta legs never carry fee information and
    report ``NOT_APPLICABLE`` (the fee belongs to the charge leg).
    """
    _require_mapping(event, field_name="event")
    _event_id, event_type, obj = _envelope_parts(event)
    if event_type == "charge.succeeded":
        currency = _normalize_currency(obj.get("currency"))
        return _extract_fee(obj, currency)
    if event_type == "refund.created":
        return FeeKnowledge.not_applicable()
    raise InvariantViolation(
        f"Unsupported Stripe event type {event_type!r}; "
        f"expected one of {list(SUPPORTED_EVENT_TYPES)}."
    )


def _charge_parts(obj: Mapping[str, Any], *, currency: str) -> tuple[str, Decimal]:
    """Extract ``(payment_id, gross)`` from a charge object."""
    payment_id = _require_text(obj.get("id"), field_name="data.object.id")
    gross_minor = _minor_field(obj, currency, "amount", "amount_minor", field_name="amount")
    if gross_minor is None:
        raise InvariantViolation("Field 'amount' is required on a charge object.")
    gross = _minor_to_decimal(gross_minor, field_name="amount", currency=currency)
    if gross < Decimal("0"):
        raise InvariantViolation(f"Charge gross must be >= 0, got {gross}.")
    return payment_id, gross


def _refund_parts(obj: Mapping[str, Any], *, currency: str) -> tuple[str, str, Decimal, Decimal]:
    """Extract ``(refund_id, payment_id, delta, gross)`` from a refund object.

    The delta is ``data.object.amount`` (strictly positive, ``refund > gross``
    rejected here). The charge gross comes from an expanded ``charge``
    mapping when present, else from the documented ``charge_amount_minor``
    context key — a ``refund.created`` delivery carries no gross of its own.
    """
    refund_id = _require_text(obj.get("id"), field_name="data.object.id")
    delta_minor = _minor_field(obj, currency, "amount", "amount_minor", field_name="amount")
    if delta_minor is None:
        raise InvariantViolation("Field 'amount' is required on a refund object.")
    delta = _minor_to_decimal(delta_minor, field_name="amount", currency=currency)
    if delta <= Decimal("0"):
        raise InvariantViolation(f"Refund delta must be positive, got {delta}.")
    charge = obj.get("charge")
    payment_id: str
    gross: Decimal
    if isinstance(charge, Mapping):
        payment_id = _require_text(charge.get("id"), field_name="data.object.charge.id")
        charge_gross_minor = _minor_field(
            charge, currency, "amount", "amount_minor", field_name="charge.amount"
        )
        if charge_gross_minor is None:
            context_minor = _minor_field(
                obj,
                currency,
                "charge_amount_minor",
                field_name="charge_amount_minor",
            )
            if context_minor is None:
                raise InvariantViolation(
                    "Refund charge snapshot carries no amount; "
                    "provide 'charge_amount_minor' on the refund object."
                )
            gross = _minor_to_decimal(
                context_minor, field_name="charge_amount_minor", currency=currency
            )
        else:
            gross = _minor_to_decimal(
                charge_gross_minor, field_name="charge.amount", currency=currency
            )
    elif isinstance(charge, str) and charge.strip():
        payment_id = charge.strip()
        context_minor = _minor_field(
            obj, currency, "charge_amount_minor", field_name="charge_amount_minor"
        )
        if context_minor is None:
            raise InvariantViolation(
                "Refund event links a bare charge id with no gross context; "
                "provide 'charge_amount_minor' on the refund object."
            )
        gross = _minor_to_decimal(
            context_minor, field_name="charge_amount_minor", currency=currency
        )
    else:
        raise InvariantViolation(
            "Field 'data.object.charge' must be a charge id string or mapping."
        )
    if delta > gross:
        raise InvariantViolation(f"Refund delta {delta} exceeds charge gross {gross}; rejected.")
    return refund_id, payment_id, delta, gross


def _charge_idempotency_key(tenant_id: str, payment_id: str, event_id: str) -> str:
    """Deterministic key for one charge fact: tenant + payment + event."""
    return f"stripe:{tenant_id}:{payment_id}:charge:{event_id}"


def stripe_to_normalized(event: Mapping[str, Any], *, tenant_id: str) -> StripeNormalized:
    """Normalize one Stripe event to its canonical payment fact.

    Args:
        event: Raw Stripe envelope (``id``, ``type``, ``created``,
            ``data.object``). Only ``charge.succeeded`` and
            ``refund.created`` are accepted.
        tenant_id: Explicit tenant scope; there is no default tenant.

    Returns:
        The canonical fact with its authoritative fee knowledge (and the
        refund-record identity for refund legs).

    Raises:
        InvariantViolation: Malformed envelope, unsupported type, missing
            identifiers, bad currency/timestamp, non-positive refund delta,
            or refund above gross.
        FloatMoneyError: Any money value arriving as ``float``/``bool``.
        CurrencyMismatch: Never raised here (single-leg currency is guarded,
            cross-leg mismatch is enforced by :class:`StripePayment`).
    """
    tenant = _require_text(tenant_id, field_name="tenant_id")
    event_id, event_type, obj = _envelope_parts(event)
    currency = _normalize_currency(obj.get("currency"))
    occurred_at = _occurred_at_of(event, obj)

    if event_type == "charge.succeeded":
        payment_id, gross = _charge_parts(obj, currency=currency)
        fee = _extract_fee(obj, currency)
        record = normalize(
            {
                "payment_id": payment_id,
                "provider": PROVIDER,
                "provider_event_id": event_id,
                "idempotency_key": _charge_idempotency_key(tenant, payment_id, event_id),
                "gross": gross,
                **({"fee": fee.amount} if fee.state is FeeState.KNOWN else {}),
                "refund": Decimal("0"),
                "currency": currency,
                "status": PaymentStatus.CAPTURED,
                "occurred_at": occurred_at,
                "tenant_id": tenant,
                "source_reference": None,
            }
        )
        logger.info(
            "Stripe charge normalized payment_id=%s gross=%s %s fee=%s",
            payment_id,
            gross,
            currency,
            fee.state.value,
        )
        return StripeNormalized(record=record, fee=fee, refund=None)

    if event_type == "refund.created":
        refund_id, payment_id, delta, gross = _refund_parts(obj, currency=currency)
        fee = FeeKnowledge.not_applicable()
        status = PaymentStatus.REFUNDED if delta == gross else PaymentStatus.PARTIALLY_REFUNDED
        record = normalize(
            {
                "payment_id": payment_id,
                "provider": PROVIDER,
                "provider_event_id": event_id,
                "idempotency_key": f"stripe:{tenant}:{payment_id}:refund:{refund_id}",
                "gross": gross,
                "refund": delta,
                "currency": currency,
                "status": status,
                "occurred_at": occurred_at,
                "tenant_id": tenant,
                "source_reference": None,
            }
        )
        refund = RefundRecord(
            provider=PROVIDER,
            refund_id=refund_id,
            payment_id=payment_id,
            amount=delta,
            currency=currency,
            tenant_id=tenant,
            provider_event_id=event_id,
            occurred_at=occurred_at,
        )
        logger.info(
            "Stripe refund normalized payment_id=%s refund_id=%s delta=%s %s",
            payment_id,
            refund_id,
            delta,
            currency,
        )
        return StripeNormalized(record=record, fee=fee, refund=refund)

    raise InvariantViolation(
        f"Unsupported Stripe event type {event_type!r}; "
        f"expected one of {list(SUPPORTED_EVENT_TYPES)}."
    )


def stripe_to_record(event: Mapping[str, Any], *, tenant_id: str) -> PaymentRecord:
    """Normalize one Stripe event to its canonical :class:`PaymentRecord`.

    Thin projection of :func:`stripe_to_normalized`: the returned record's
    ``fee`` is a ``Decimal``-only arithmetic placeholder when the fee is not
    known, so consumers MUST consult :func:`fee_knowledge_of` (or
    :func:`stripe_to_normalized`) to distinguish ``UNKNOWN`` from an explicit
    zero — never infer fee presence from ``record.fee == 0``.
    """
    return stripe_to_normalized(event, tenant_id=tenant_id).record


@dataclass(frozen=True)
class StripePayment:
    """Canonical per-payment fold: one charge plus unique refund records.

    Identity is ``(tenant_id, provider, payment_id)``. Refunds accumulate as
    an order-independent set keyed by ``(provider, refund_id)``; applying the
    same refund lifecycle event twice is a no-op and never subtracts twice.
    Cumulative refunds above gross are rejected.
    """

    tenant_id: str
    payment_id: str
    gross: Decimal
    currency: str
    fee: FeeKnowledge
    charge_event_id: str
    charge_occurred_at: datetime
    refunds: tuple[RefundRecord, ...] = ()

    def __post_init__(self) -> None:
        """Enforce identifiers, Decimal-only gross, currency, and UTC time."""
        for field_name in ("tenant_id", "payment_id", "charge_event_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise InvariantViolation(f"Field '{field_name}' must be a non-empty string.")
        gross_value: object = self.gross
        if isinstance(gross_value, (bool, float)):
            raise FloatMoneyError(
                "Field 'gross' must be Decimal, "
                f"got {type(gross_value).__name__}: "
                "float/bool money is rejected, use decimal.Decimal."
            )
        if not isinstance(gross_value, Decimal) or not gross_value.is_finite():
            raise InvariantViolation(
                f"Field 'gross' must be a finite Decimal, got {type(gross_value).__name__}."
            )
        if gross_value < Decimal("0"):
            raise InvariantViolation(f"Field 'gross' must be >= 0, got {gross_value}.")
        currency_value: object = self.currency
        if not isinstance(currency_value, str):
            raise InvariantViolation("Field 'currency' must be a string.")
        if _CURRENCY_PATTERN.fullmatch(currency_value) is None:
            raise InvariantViolation(
                f"Field 'currency' must be an ISO 4217 code, got {currency_value!r}."
            )
        fee_value: object = self.fee
        if not isinstance(fee_value, FeeKnowledge):
            raise InvariantViolation(
                f"Field 'fee' must be a FeeKnowledge, got {type(fee_value).__name__}."
            )
        occurred_value: object = self.charge_occurred_at
        if not isinstance(occurred_value, datetime):
            raise InvariantViolation("Field 'charge_occurred_at' must be a datetime.")
        tzinfo = occurred_value.tzinfo
        if tzinfo is None or tzinfo.utcoffset(occurred_value) is None:
            raise InvariantViolation("Field 'charge_occurred_at' must be tz-aware.")
        refunds_value: object = self.refunds
        if not isinstance(refunds_value, tuple) or not all(
            isinstance(item, RefundRecord) for item in refunds_value
        ):
            raise InvariantViolation("Field 'refunds' must be a tuple of RefundRecord.")

    @property
    def provider(self) -> str:
        """Provider literal for this payment (always ``stripe``)."""
        return PROVIDER

    def canonical_key(self) -> tuple[str, str, str]:
        """Canonical identity: ``(tenant_id, provider, payment_id)``."""
        return (self.tenant_id, PROVIDER, self.payment_id)

    def total_refunded(self) -> Decimal:
        """Sum of unique refund deltas (identities, never this-request sums)."""
        total = Decimal("0")
        for refund in self.refunds:
            total += refund.amount
        return total

    def net_amount(self) -> Decimal:
        """Canonical net: gross minus known fee (else 0 placeholder) minus refunds."""
        fee_amount = (
            self.fee.amount
            if self.fee.state is FeeState.KNOWN and self.fee.amount is not None
            else Decimal("0")
        )
        return self.gross - fee_amount - self.total_refunded()

    def derived_status(self) -> PaymentStatus:
        """Lifecycle fact from refund progress: captured, partial, or refunded."""
        refunded = self.total_refunded()
        if refunded == Decimal("0"):
            return PaymentStatus.CAPTURED
        if refunded == self.gross:
            return PaymentStatus.REFUNDED
        return PaymentStatus.PARTIALLY_REFUNDED

    def _latest_provenance(self) -> tuple[str, datetime]:
        """Latest ``(provider_event_id, occurred_at)`` across charge + refunds.

        Ties break by refund id so out-of-order application converges to the
        same provenance — and therefore the same canonical record.
        """
        latest_id = self.charge_event_id
        latest_at = self.charge_occurred_at
        for refund in sorted(self.refunds, key=lambda item: item.refund_id):
            if (refund.occurred_at, refund.refund_id) >= (latest_at, latest_id):
                latest_id = refund.provider_event_id
                latest_at = refund.occurred_at
        return latest_id, latest_at

    def canonical_idempotency_key(self) -> str:
        """Content-derived key: same refund set (any order) yields the same key."""
        ordered = sorted(self.refunds, key=lambda item: item.refund_id)
        refund_part = (
            ",".join(f"{item.refund_id}={item.amount}" for item in ordered) if ordered else "none"
        )
        fee_part = f"fee={self.fee.state.value}"
        if self.fee.state is FeeState.KNOWN and self.fee.amount is not None:
            fee_part += f":{self.fee.amount}"
        return (
            f"stripe:{self.tenant_id}:{self.payment_id}"
            f":gross={self.gross}:{fee_part}:refunds={refund_part}"
        )

    def apply_refund(self, refund: RefundRecord) -> StripePayment:
        """Fold one refund delta in, keyed by refund-record identity.

        The same ``(provider, refund_id)`` applied twice is a no-op; the
        same id with a different amount/currency is a conflicting replay and
        is rejected. Cross-tenant, cross-payment, and cross-currency merges
        are rejected — linkage is by identifier, never by amount.
        """
        if not isinstance(refund, RefundRecord):
            raise InvariantViolation(
                f"apply_refund requires a RefundRecord, got {type(refund).__name__}."
            )
        if refund.provider != PROVIDER:
            raise InvariantViolation(
                f"Refund provider {refund.provider!r} does not match {PROVIDER!r}."
            )
        if refund.tenant_id != self.tenant_id:
            raise InvariantViolation(
                "Refund tenant does not match payment tenant; "
                "same payment id under different tenants is isolated."
            )
        if refund.payment_id != self.payment_id:
            raise InvariantViolation(
                f"Refund links payment {refund.payment_id!r}, "
                f"not {self.payment_id!r}; refusing to merge by amount."
            )
        if refund.currency != self.currency:
            raise CurrencyMismatch(refund.currency, self.currency, operation="apply_refund")
        for seen in self.refunds:
            if seen.identity == refund.identity:
                if seen.amount == refund.amount and seen.currency == refund.currency:
                    logger.info(
                        "Duplicate refund replay ignored refund_id=%s payment_id=%s.",
                        refund.refund_id,
                        self.payment_id,
                    )
                    return self
                raise InvariantViolation(
                    f"Conflicting replay for refund {refund.refund_id!r}: "
                    "same identity with a different amount."
                )
        merged = (*self.refunds, refund)
        total = sum((item.amount for item in merged), Decimal("0"))
        if total > self.gross:
            raise InvariantViolation(
                f"Cumulative refunds {total} exceed gross {self.gross}; rejected."
            )
        return StripePayment(
            tenant_id=self.tenant_id,
            payment_id=self.payment_id,
            gross=self.gross,
            currency=self.currency,
            fee=self.fee,
            charge_event_id=self.charge_event_id,
            charge_occurred_at=self.charge_occurred_at,
            refunds=merged,
        )

    def to_record(self) -> PaymentRecord:
        """Emit the canonical :class:`PaymentRecord` for the folded state."""
        provider_event_id, occurred_at = self._latest_provenance()
        fee_amount = (
            self.fee.amount
            if self.fee.state is FeeState.KNOWN and self.fee.amount is not None
            else Decimal("0")
        )
        return normalize(
            {
                "payment_id": self.payment_id,
                "provider": PROVIDER,
                "provider_event_id": provider_event_id,
                "idempotency_key": self.canonical_idempotency_key(),
                "gross": self.gross,
                "fee": fee_amount,
                "refund": self.total_refunded(),
                "currency": self.currency,
                "status": self.derived_status(),
                "occurred_at": occurred_at,
                "tenant_id": self.tenant_id,
                "source_reference": None,
            }
        )


def payment_from_charge(event: Mapping[str, Any], *, tenant_id: str) -> StripePayment:
    """Build the canonical :class:`StripePayment` fold from a charge event.

    Only ``charge.succeeded`` is accepted; refund lifecycle events fold in
    through :func:`apply_refund_event`.
    """
    tenant = _require_text(tenant_id, field_name="tenant_id")
    normalized = stripe_to_normalized(event, tenant_id=tenant)
    if normalized.refund is not None:
        raise InvariantViolation(
            "payment_from_charge requires a charge.succeeded event; "
            "fold refund.created through apply_refund_event."
        )
    record = normalized.record
    return StripePayment(
        tenant_id=tenant,
        payment_id=record.payment_id,
        gross=record.gross,
        currency=record.currency,
        fee=normalized.fee,
        charge_event_id=record.provider_event_id,
        charge_occurred_at=record.occurred_at,
        refunds=(),
    )


def apply_refund_event(payment: StripePayment, event: Mapping[str, Any]) -> StripePayment:
    """Fold one ``refund.created`` event into a payment fold, idempotently.

    The refund inherits the payment's tenant scope; replaying the same
    refund lifecycle event returns an unchanged fold (no double subtract).
    """
    if not isinstance(payment, StripePayment):
        raise InvariantViolation(
            f"apply_refund_event requires a StripePayment, got {type(payment).__name__}."
        )
    normalized = stripe_to_normalized(event, tenant_id=payment.tenant_id)
    if normalized.refund is None:
        raise InvariantViolation("apply_refund_event requires a refund.created event.")
    return payment.apply_refund(normalized.refund)


__all__ = [
    "PROVIDER",
    "SUPPORTED_EVENT_TYPES",
    "FeeKnowledge",
    "FeeState",
    "RefundRecord",
    "StripeNormalized",
    "StripePayment",
    "apply_refund_event",
    "fee_knowledge_of",
    "payment_from_charge",
    "stripe_to_normalized",
    "stripe_to_record",
]
