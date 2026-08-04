"""Tests for the Transaction domain model.

Covers ``finance/domain/transaction.py``: the atomic financial transaction
record. Key invariants: amounts use ``MoneyDecimal`` (float rejected),
transactions carry an ISO currency defaulting to USD, and they reference a
fiscal period and optional department/cost-centre attribution.
"""

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from finance.domain.transaction import Transaction


def _now() -> datetime:
    """A fixed timestamp for created_at."""
    return datetime(2026, 7, 15, 12, 0, 0, tzinfo=UTC)


def _transaction(**overrides: object) -> Transaction:
    """Build a default transaction."""
    defaults: dict[str, object] = {
        "id": "TXN-0001",
        "account_id": "6400",
        "amount": "350.00",
        "description": "Airfare booking",
        "transaction_date": date(2026, 6, 18),
        "period_id": "2026-06",
        "created_at": _now(),
    }
    defaults.update(overrides)
    return Transaction(**defaults)


class TestTransaction:
    """Transaction construction."""

    def test_constructs_with_required_fields(self) -> None:
        """A transaction builds with required fields."""
        txn = _transaction()
        assert txn.id == "TXN-0001"
        assert txn.account_id == "6400"
        assert txn.description == "Airfare booking"
        assert txn.transaction_date == date(2026, 6, 18)
        assert txn.period_id == "2026-06"

    def test_currency_defaults_to_usd(self) -> None:
        """currency defaults to USD."""
        assert _transaction().currency == "USD"

    def test_source_defaults_to_gl(self) -> None:
        """source defaults to 'gl'."""
        assert _transaction().source == "gl"

    def test_department_defaults_to_none(self) -> None:
        """department_id defaults to None."""
        assert _transaction().department_id is None

    def test_cost_center_defaults_to_none(self) -> None:
        """cost_center_id defaults to None."""
        assert _transaction().cost_center_id is None

    def test_reference_defaults_to_none(self) -> None:
        """reference defaults to None."""
        assert _transaction().reference is None

    def test_float_amount_rejected(self) -> None:
        """A float amount is rejected."""
        with pytest.raises(ValidationError):
            _transaction(amount=350.0)

    def test_string_amount_coerced(self) -> None:
        """A string amount is coerced to Decimal."""
        assert str(_transaction(amount="350.50").amount) == "350.50"

    def test_negative_amount_representable(self) -> None:
        """A negative amount (reversal) is representable."""
        txn = _transaction(amount="-350.00")
        assert str(txn.amount) == "-350.00"

    def test_zero_amount_representable(self) -> None:
        """A zero amount is representable."""
        assert str(_transaction(amount="0.00").amount) == "0.00"

    def test_currency_settable(self) -> None:
        """The transaction currency is settable."""
        assert _transaction(currency="EUR").currency == "EUR"

    def test_attribution_stored(self) -> None:
        """Department and cost-centre attribution are preserved."""
        txn = _transaction(department_id="FINANCE", cost_center_id="CC-100")
        assert txn.department_id == "FINANCE"
        assert txn.cost_center_id == "CC-100"

    def test_reference_stored(self) -> None:
        """An external reference is preserved."""
        txn = _transaction(reference="INV-90210")
        assert txn.reference == "INV-90210"

    def test_source_settable(self) -> None:
        """The source system is settable."""
        txn = _transaction(source="journal")
        assert txn.source == "journal"

    def test_id_required(self) -> None:
        """A transaction requires an id."""
        with pytest.raises(ValidationError):
            _transaction(id=None)

    def test_account_id_required(self) -> None:
        """A transaction requires an account id."""
        with pytest.raises(ValidationError):
            _transaction(account_id=None)

    def test_amount_required(self) -> None:
        """A transaction requires an amount."""
        with pytest.raises(ValidationError):
            _transaction(amount=None)

    def test_description_required(self) -> None:
        """A transaction requires a description."""
        with pytest.raises(ValidationError):
            _transaction(description=None)

    def test_transaction_date_required(self) -> None:
        """A transaction requires a transaction date."""
        with pytest.raises(ValidationError):
            _transaction(transaction_date=None)

    def test_period_id_required(self) -> None:
        """A transaction requires a period id."""
        with pytest.raises(ValidationError):
            _transaction(period_id=None)

    def test_created_at_required(self) -> None:
        """A transaction requires a created_at timestamp."""
        with pytest.raises(ValidationError):
            _transaction(created_at=None)

    def test_round_trip_serialization(self) -> None:
        """A transaction round-trips through model_dump."""
        txn = _transaction()
        dumped = txn.model_dump()
        rebuilt = Transaction(**dumped)
        assert rebuilt == txn