"""Unit tests: Stripe webhook envelope contract + P1 normalizer (P2.3).

Covers the transport-adjacent contract the P2 ingest must satisfy:

* Strict envelope validation (Pydantic, float-rejecting like
  ``MoneyDecimal`` in ``apps/api/schemas.py``): valid envelopes yield
  ``200`` and persist; malformed envelopes yield ``400`` with no mutation.
* Normalizer behavior through the real P1 ``normalize``: minor-units to
  ``Decimal``, fee unknown (absent) vs explicit ``0`` (both ``Decimal("0")``
  numerically, distinguished only by key presence), tz-aware timestamps
  normalized to UTC, and ``float``/naive/missing money rejected.

Pure unit: in-memory store only, no DB, no network, no LLM.
All money uses ``Decimal("...")``; floats appear solely as rejection probes.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import pytest
from pydantic import BaseModel, ValidationError, field_validator

from finance.reconciliation.errors import FloatMoneyError, InvariantViolation
from finance.reconciliation.normalizer import normalize

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "reconciliation" / "stripe"

ALLOWED_EVENT_TYPES = ("charge.succeeded", "refund.created")


def _reject_float_int(value: Any) -> Any:
    """Reject ``float``/``bool`` where an int minor-unit amount is required."""
    if isinstance(value, bool | float):
        raise ValueError(f"Minor-unit amount must be int, got {type(value).__name__}.")
    return value


def _require_non_empty(value: Any, field_name: str) -> str:
    """Require a non-empty string identifier."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Field '{field_name}' must be a non-empty string.")
    return value.strip()


class StripeEnvelopeData(BaseModel):
    """Thin Stripe data block: minor-unit amount plus currency."""

    payment_id: str
    amount_minor: int
    currency: str = "USD"

    @field_validator("payment_id", mode="before")
    @classmethod
    def _payment_id(cls, value: Any) -> str:
        return _require_non_empty(value, "payment_id")

    @field_validator("amount_minor", mode="before")
    @classmethod
    def _amount_minor(cls, value: Any) -> Any:
        return _reject_float_int(value)

    @field_validator("currency", mode="before")
    @classmethod
    def _currency(cls, value: Any) -> str:
        code = _require_non_empty(value, "currency").upper()
        if len(code) != 3 or not code.isalpha():
            raise ValueError(f"Field 'currency' must be an ISO 4217 code, got {value!r}.")
        return code


class StripeWebhookEnvelope(BaseModel):
    """Strict webhook envelope: identifiers, type, timestamp, data."""

    event_id: str
    event_type: Literal["charge.succeeded", "refund.created"]
    idempotency_key: str
    tenant_id: str
    created: int
    data: StripeEnvelopeData

    @field_validator("event_id", "idempotency_key", "tenant_id", mode="before")
    @classmethod
    def _identifiers(cls, value: Any, info: Any) -> str:
        return _require_non_empty(value, str(info.field_name))

    @field_validator("created", mode="before")
    @classmethod
    def _created(cls, value: Any) -> Any:
        return _reject_float_int(value)


def handle_webhook(
    envelope_dict: dict[str, Any], store: dict[str, dict[str, Any]]
) -> tuple[int, dict[str, Any]]:
    """Validate an envelope; persist on success, 400 with no mutation on failure.

    Args:
        envelope_dict: Raw decoded JSON body of the webhook delivery.
        store: In-memory transport keyed by ``event_id`` (mutated only on 200).

    Returns:
        ``(status_code, body)`` where 200 carries the stored key and 400
        carries the validation error.
    """
    try:
        envelope = StripeWebhookEnvelope.model_validate(envelope_dict)
    except ValidationError as exc:
        return 400, {"error": "malformed_envelope", "detail": exc.errors()}
    store[envelope.event_id] = envelope.model_dump()
    return 200, {"event_id": envelope.event_id, "status": "accepted"}


def _raw_charge(
    *,
    tenant_id: str = "tenant-acme",
    occurred_at: Any = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC),
) -> dict[str, Any]:
    """Build a valid minor-unit charge payload for the normalizer."""
    return {
        "payment_id": "pi-flagship-charge",
        "provider": "stripe",
        "provider_event_id": "evt-flagship-charge",
        "idempotency_key": "stripe-flagship-001",
        "gross_minor": 5000000,
        "fee_minor": 0,
        "refund_minor": 0,
        "currency": "USD",
        "status": "SETTLED",
        "occurred_at": occurred_at,
        "tenant_id": tenant_id,
    }


class TestEnvelopeAccepted:
    """Valid envelopes persist and return 200."""

    def test_valid_charge_envelope_returns_200_and_persists(self) -> None:
        """Arrange a charge envelope; Act handle; Assert stored once."""
        store: dict[str, dict[str, Any]] = {}
        envelope = json.loads((FIXTURES / "envelope_charge.json").read_text())
        status, body = handle_webhook(envelope, store)
        assert status == 200
        assert body["event_id"] == "evt-flagship-charge"
        assert len(store) == 1
        assert store["evt-flagship-charge"]["idempotency_key"] == "stripe-flagship-001"

    def test_valid_refund_envelope_returns_200(self) -> None:
        """A refund envelope for the same payment is a distinct event."""
        store: dict[str, dict[str, Any]] = {}
        refund = json.loads((FIXTURES / "envelope_refund.json").read_text())
        status, _ = handle_webhook(refund, store)
        assert status == 200
        assert len(store) == 1


class TestMalformedEnvelope400NoMutation:
    """Malformed envelopes yield 400 and never mutate the store."""

    def test_missing_event_id_is_400_without_mutation(self) -> None:
        """Arrange envelope without event_id; Assert 400 and empty store."""
        store: dict[str, dict[str, Any]] = {}
        envelope = json.loads((FIXTURES / "envelope_charge.json").read_text())
        del envelope["event_id"]
        status, body = handle_webhook(envelope, store)
        assert status == 400
        assert body["error"] == "malformed_envelope"
        assert store == {}

    def test_empty_idempotency_key_is_400_without_mutation(self) -> None:
        """Blank idempotency keys are rejected."""
        store: dict[str, dict[str, Any]] = {}
        envelope = json.loads((FIXTURES / "envelope_charge.json").read_text())
        envelope["idempotency_key"] = "   "
        assert handle_webhook(envelope, store)[0] == 400
        assert store == {}

    def test_float_amount_minor_is_400_without_mutation(self) -> None:
        """Float minor-unit amounts are rejected like float money."""
        store: dict[str, dict[str, Any]] = {}
        envelope = json.loads((FIXTURES / "envelope_charge.json").read_text())
        envelope["data"]["amount_minor"] = 5000000.0
        assert handle_webhook(envelope, store)[0] == 400
        assert store == {}

    def test_bool_amount_minor_is_400_without_mutation(self) -> None:
        """Bools are ints in disguise and must be rejected."""
        store: dict[str, dict[str, Any]] = {}
        envelope = json.loads((FIXTURES / "envelope_charge.json").read_text())
        envelope["data"]["amount_minor"] = True
        assert handle_webhook(envelope, store)[0] == 400
        assert store == {}

    def test_unknown_event_type_is_400_without_mutation(self) -> None:
        """Only the allow-listed Stripe types are accepted."""
        store: dict[str, dict[str, Any]] = {}
        envelope = json.loads((FIXTURES / "envelope_charge.json").read_text())
        envelope["event_type"] = "customer.deleted"
        assert handle_webhook(envelope, store)[0] == 400
        assert store == {}

    def test_fixture_malformed_envelope_is_400(self) -> None:
        """The checked-in malformed fixture is rejected with no mutation."""
        store: dict[str, dict[str, Any]] = {}
        malformed = json.loads((FIXTURES / "envelope_malformed.json").read_text())
        status, _ = handle_webhook(malformed, store)
        assert status == 400
        assert store == {}


class TestNormalizerMinorUnits:
    """Stripe minor units convert exactly to Decimal major units."""

    def test_charge_minor_units_become_50000(self) -> None:
        """5,000,000 cents normalizes to Decimal 50000 with zero net drift."""
        record = normalize(_raw_charge())
        assert record.gross == Decimal("50000.00")
        assert record.gross == Decimal(5000000) / Decimal(100)
        assert record.fee == Decimal("0")
        assert record.refund == Decimal("0")
        assert record.net == Decimal("50000.00")

    def test_refund_minor_units_become_15000(self) -> None:
        """1,500,000 refund cents normalizes to Decimal 15000."""
        raw = _raw_charge()
        raw["refund_minor"] = 1500000
        raw["provider_event_id"] = "evt-flagship-refund"
        raw["idempotency_key"] = "stripe-flagship-001-refund"
        record = normalize(raw)
        assert record.refund == Decimal("15000.00")
        assert record.net == Decimal("35000.00")

    def test_fixture_charge_file_normalizes(self) -> None:
        """The checked-in charge fixture normalizes to a 50k leg."""
        raw = json.loads((FIXTURES / "charge_50000.json").read_text())
        record = normalize(raw)
        assert record.gross == Decimal("50000")
        assert record.net == Decimal("50000")
        assert isinstance(record.gross, Decimal)

    def test_fixture_refund_file_normalizes(self) -> None:
        """The checked-in refund fixture normalizes to a 15k refund leg."""
        raw = json.loads((FIXTURES / "refund_15000.json").read_text())
        record = normalize(raw)
        assert record.refund == Decimal("15000")
        assert record.net == Decimal("35000")


class TestFeeUnknownVsExplicitZero:
    """Absent fee defaults to zero numerically but stays distinguishable."""

    def test_missing_fee_defaults_to_zero_decimal(self) -> None:
        """Unknown fee defaults to Decimal 0 for net arithmetic."""
        raw = _raw_charge()
        del raw["fee_minor"]
        record = normalize(raw)
        assert record.fee == Decimal("0")
        assert record.net == record.gross - record.refund

    def test_explicit_zero_fee_matches_default_numerically(self) -> None:
        """Explicit 0 and absent fee agree numerically (both zero)."""
        explicit = normalize(_raw_charge())
        raw = _raw_charge()
        del raw["fee_minor"]
        defaulted = normalize(raw)
        assert explicit.fee == defaulted.fee == Decimal("0")
        assert explicit.net == defaulted.net

    def test_presence_distinguishes_unknown_from_explicit(self) -> None:
        """Callers can tell unknown (key absent) from explicit 0 (key present)."""
        raw_unknown = _raw_charge()
        del raw_unknown["fee_minor"]
        raw_explicit = _raw_charge()
        assert "fee_minor" not in raw_unknown
        assert raw_explicit["fee_minor"] == 0
        assert normalize(raw_unknown).fee == normalize(raw_explicit).fee


class TestUtcAndFloatGuards:
    """Timestamps normalize to UTC; float money and naive times are rejected."""

    def test_non_utc_offset_normalizes_to_utc(self) -> None:
        """A +05:30 instant is stored as the same instant in UTC."""
        raw = _raw_charge(occurred_at="2026-05-01T17:30:00+05:30")
        record = normalize(raw)
        assert record.occurred_at.tzinfo is not None
        assert record.occurred_at == datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)

    def test_z_suffix_normalizes_to_utc(self) -> None:
        """A Z-suffixed instant is accepted and tz-aware."""
        raw = _raw_charge(occurred_at="2026-05-01T12:00:00Z")
        assert normalize(raw).occurred_at == datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)

    def test_float_gross_rejected(self) -> None:
        """Float money is rejected at the normalizer boundary."""
        raw = _raw_charge()
        raw["gross_minor"] = 5000000.0
        with pytest.raises(FloatMoneyError):
            normalize(raw)

    def test_naive_datetime_rejected(self) -> None:
        """Tz-naive timestamps are rejected."""
        with pytest.raises(InvariantViolation, match="tz-aware"):
            normalize(_raw_charge(occurred_at=datetime(2026, 5, 1, 12, 0, 0)))

    def test_missing_gross_rejected(self) -> None:
        """A payload without gross is rejected."""
        raw = _raw_charge()
        del raw["gross_minor"]
        with pytest.raises(InvariantViolation, match="gross"):
            normalize(raw)
