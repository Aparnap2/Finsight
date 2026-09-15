"""Tests for the Invoice domain models.

Invoices are represented in the platform as domain events
(`business/events/models.py`): ``InvoiceImported`` records a successfully
ingested vendor invoice and ``InvoiceRejected`` records a validation
failure. Both inherit the frozen, provenance-carrying ``DomainEvent`` base.

Monetary values are ``decimal.Decimal`` — never ``float``.
"""

from datetime import UTC, datetime
from decimal import Decimal
from json import loads

import pytest
from pydantic import ValidationError

from business.events.models import InvoiceImported, InvoiceRejected

_EVENT_DATE = datetime(2026, 7, 15, tzinfo=UTC)


def _invoice(**overrides: object) -> InvoiceImported:
    """Build an InvoiceImported event with sensible defaults."""
    payload: dict[str, object] = {
        "event_id": "evt-inv-001",
        "event_type": "invoice.imported",
        "producer": "ingestion",
        "consumer": ["ledger", "variance"],
        "vendor_id": "VEN-001",
        "invoice_number": "INV-2026-001",
        "amount": Decimal("12500.00"),
        "currency": "USD",
        "date": _EVENT_DATE,
    }
    payload.update(overrides)
    return InvoiceImported(**payload)


# =============================================================================
# DomainEvent base provenance
# =============================================================================


class TestDomainEventBase:
    """Provenance metadata shared by every invoice event."""

    def test_provenance_fields_present(self) -> None:
        """An invoice event carries full provenance metadata."""
        event = _invoice()
        assert event.event_id == "evt-inv-001"
        assert event.event_type == "invoice.imported"
        assert event.producer == "ingestion"
        assert event.consumer == ["ledger", "variance"]
        assert event.sensitivity == "internal"

    def test_default_version(self) -> None:
        """The event schema version defaults to 1.0."""
        assert _invoice().version == "1.0"

    def test_default_sensitivity_is_internal(self) -> None:
        """Sensitivity defaults to internal unless overridden."""
        assert _invoice().sensitivity == "internal"

    def test_default_payload_empty_dict(self) -> None:
        """Payload defaults to an empty dictionary."""
        assert _invoice().payload == {}

    def test_correlation_and_causation_default_none(self) -> None:
        """Correlation and causation ids are optional tracing hooks."""
        event = _invoice()
        assert event.correlation_id is None
        assert event.causation_id is None

    def test_timestamp_auto_populated(self) -> None:
        """The timestamp defaults to the event creation time."""
        assert isinstance(_invoice().timestamp, datetime)

    def test_event_id_required(self) -> None:
        """An event must carry a unique identifier."""
        with pytest.raises(ValidationError):
            _invoice(event_id=None) 

    def test_event_type_required(self) -> None:
        """An event must name its type."""
        with pytest.raises(ValidationError):
            _invoice(event_type=None) 

    def test_producer_required(self) -> None:
        """An event must name its producing component."""
        with pytest.raises(ValidationError):
            _invoice(producer=None) 

    def test_consumer_required(self) -> None:
        """An event must declare at least its consumers list."""
        with pytest.raises(ValidationError):
            _invoice(consumer=None) 

    def test_frozen_event_is_immutable(self) -> None:
        """Invoice events are immutable once constructed."""
        event = _invoice()
        with pytest.raises(ValidationError):
            event.producer = "other"  # type: ignore[misc]

    def test_extra_fields_forbidden(self) -> None:
        """Unknown fields are rejected by the event model."""
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            _invoice(unexpected_field="boom") 


# =============================================================================
# InvoiceImported
# =============================================================================


class TestInvoiceConstruction:
    """Construction invariants of the imported-invoice event."""

    def test_valid_invoice_constructs(self) -> None:
        """A fully specified invoice constructs."""
        invoice = _invoice()
        assert invoice.vendor_id == "VEN-001"
        assert invoice.invoice_number == "INV-2026-001"
        assert invoice.amount == Decimal("12500.00")
        assert invoice.currency == "USD"
        assert invoice.date == _EVENT_DATE

    def test_amount_is_decimal_not_float(self) -> None:
        """The invoice amount is stored as Decimal."""
        assert isinstance(_invoice().amount, Decimal)

    def test_string_amount_coerced_to_decimal(self) -> None:
        """A string amount is coerced to Decimal at the boundary."""
        invoice = _invoice(amount="12500.50")
        assert isinstance(invoice.amount, Decimal)
        assert invoice.amount == Decimal("12500.50")

    def test_int_amount_coerced_to_decimal(self) -> None:
        """An int amount is coerced to Decimal."""
        invoice = _invoice(amount=12500)
        assert isinstance(invoice.amount, Decimal)
        assert invoice.amount == Decimal("12500")

    def test_default_currency_usd(self) -> None:
        """The invoice currency defaults to USD."""
        invoice = _invoice()
        assert invoice.currency == "USD"

    def test_non_usd_currency_preserved(self) -> None:
        """A non-default currency is preserved verbatim."""
        invoice = _invoice(currency="EUR")
        assert invoice.currency == "EUR"

    def test_negative_amount_representable(self) -> None:
        """Negative invoice amounts are representable (credit-memo scenario).

        Note: the event model deliberately does not reject negative amounts;
        credit notes are modelled as negative invoices in the ingestion path.
        """
        invoice = _invoice(amount=Decimal("-100.00"))
        assert invoice.amount == Decimal("-100.00")

    def test_zero_amount_constructs(self) -> None:
        """A zero-amount invoice is representable (pending / no-charge)."""
        invoice = _invoice(amount=Decimal("0.00"))
        assert invoice.amount == Decimal("0.00")

    def test_large_amount_preserved(self) -> None:
        """Large invoice amounts are preserved without precision loss."""
        invoice = _invoice(amount=Decimal("999999999999.99"))
        assert invoice.amount == Decimal("999999999999.99")

    def test_missing_vendor_rejected(self) -> None:
        """An invoice must reference a vendor."""
        with pytest.raises(ValidationError):
            _invoice(vendor_id=None) 

    def test_missing_invoice_number_rejected(self) -> None:
        """An invoice must carry a reference number."""
        with pytest.raises(ValidationError):
            _invoice(invoice_number=None) 

    def test_missing_amount_rejected(self) -> None:
        """An invoice must carry an amount."""
        with pytest.raises(ValidationError):
            _invoice(amount=None) 

    def test_missing_date_rejected(self) -> None:
        """An invoice must carry an invoice date."""
        with pytest.raises(ValidationError):
            _invoice(date=None) 

    def test_empty_vendor_representable(self) -> None:
        """An empty vendor identifier is representable at the event boundary.

        Note: the event model performs no non-empty check on ``vendor_id``;
        deeper referential validation is delegated to the ingestion pipeline.
        """
        invoice = _invoice(vendor_id="")
        assert invoice.vendor_id == ""


class TestInvoiceSerialization:
    """Serialization / deserialization round-trips for invoice events."""

    def test_model_dump_round_trip(self) -> None:
        """model_dump followed by model_validate preserves the event."""
        original = _invoice()
        rebuilt = InvoiceImported.model_validate(original.model_dump())
        assert rebuilt == original

    def test_json_round_trip(self) -> None:
        """model_dump_json followed by model_validate_json preserves the event."""
        original = _invoice()
        rebuilt = InvoiceImported.model_validate_json(original.model_dump_json())
        assert rebuilt == original

    def test_json_serializes_amount_as_string(self) -> None:
        """Decimal amounts serialize to strings, preserving precision."""
        data = loads(_invoice().model_dump_json())
        assert data["amount"] == "12500.00"
        assert isinstance(data["amount"], str)

    def test_json_round_trip_preserves_decimal(self) -> None:
        """Round-tripping through JSON keeps the amount as Decimal."""
        rebuilt = InvoiceImported.model_validate_json(_invoice().model_dump_json())
        assert isinstance(rebuilt.amount, Decimal)
        assert rebuilt.amount == Decimal("12500.00")

    def test_currency_round_trip(self) -> None:
        """The currency survives a serialization round trip."""
        rebuilt = InvoiceImported.model_validate_json(
            _invoice(currency="EUR").model_dump_json()
        )
        assert rebuilt.currency == "EUR"


# =============================================================================
# InvoiceRejected
# =============================================================================


class TestInvoiceRejected:
    """The invoice-rejection event model."""

    def _rejected(self, **overrides: object) -> InvoiceRejected:
        """Build a rejection event with sensible defaults."""
        payload: dict[str, object] = {
            "event_id": "evt-inv-rej-001",
            "event_type": "invoice.rejected",
            "producer": "validation",
            "consumer": ["ingestion"],
            "vendor_id": "VEN-002",
            "invoice_number": "INV-2026-999",
            "rejection_reason": "amount exceeds PO threshold",
            "validation_errors": ["amount too large"],
        }
        payload.update(overrides)
        return InvoiceRejected(**payload)

    def test_valid_rejection_constructs(self) -> None:
        """A rejection event with errors constructs."""
        event = self._rejected()
        assert event.vendor_id == "VEN-002"
        assert event.rejection_reason == "amount exceeds PO threshold"
        assert event.validation_errors == ["amount too large"]

    def test_rejection_reason_required(self) -> None:
        """A rejection must state a high-level reason."""
        with pytest.raises(ValidationError):
            self._rejected(rejection_reason=None) 

    def test_validation_errors_default_empty(self) -> None:
        """The detailed error list defaults to empty when omitted."""
        event = InvoiceRejected(
            event_id="evt-inv-rej-002",
            event_type="invoice.rejected",
            producer="validation",
            consumer=["ingestion"],
            vendor_id="VEN-002",
            invoice_number="INV-2026-999",
            rejection_reason="duplicate invoice",
        )
        assert event.validation_errors == []

    def test_rejection_serialization_round_trip(self) -> None:
        """Rejection events round-trip through JSON."""
        original = self._rejected()
        rebuilt = InvoiceRejected.model_validate_json(original.model_dump_json())
        assert rebuilt == original

    def test_rejection_is_distinct_event_type(self) -> None:
        """Rejections are emitted under their own event type."""
        assert self._rejected().event_type == "invoice.rejected"
