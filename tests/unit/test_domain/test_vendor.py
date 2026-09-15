"""Tests for the Vendor and related identifier value objects.

Vendors are identified across the platform by typed value objects
(`business/canonical_types/identifiers.py`): ``VendorId``, ``EntityId``,
``GLAccountNumber``, ``Department``, ``CostCenter``, and ``LedgerAccount``.
Each wraps a string with format validation, normalization, and frozen
immutability — preventing primitive obsession in the vendor/AP domain.
"""

import pytest
from pydantic import ValidationError

from business.canonical_types import (
    CostCenter,
    Department,
    EntityId,
    GLAccountNumber,
    LedgerAccount,
    VendorId,
)

# =============================================================================
# VendorId
# =============================================================================


class TestVendorId:
    """Vendor identifier construction and validation."""

    def test_valid_vendor_id_constructs(self) -> None:
        """A vendor identifier constructs from its wrapped string."""
        vid = VendorId(id="VEN-001")
        assert vid.id == "VEN-001"

    def test_whitespace_stripped(self) -> None:
        """Surrounding whitespace is stripped on construction."""
        assert VendorId(id="  VEN-001  ").id == "VEN-001"

    def test_empty_vendor_id_rejected(self) -> None:
        """An empty vendor id violates the identifier invariant."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            VendorId(id="")

    def test_blank_vendor_id_rejected(self) -> None:
        """A whitespace-only vendor id is rejected."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            VendorId(id="   ")

    def test_frozen_prevents_mutation(self) -> None:
        """VendorId is immutable."""
        vid = VendorId(id="VEN-001")
        with pytest.raises(ValidationError):
            vid.id = "VEN-002"  # type: ignore[misc]

    def test_str_returns_identifier(self) -> None:
        """The string representation is the raw identifier."""
        assert str(VendorId(id="VEN-001")) == "VEN-001"

    def test_equality(self) -> None:
        """Two vendor ids wrapping the same value are equal."""
        assert VendorId(id="VEN-001") == VendorId(id="VEN-001")
        assert VendorId(id="VEN-001") != VendorId(id="VEN-002")

    def test_serialization_round_trip(self) -> None:
        """model_dump / model_validate preserves the identifier."""
        original = VendorId(id="VEN-001")
        rebuilt = VendorId.model_validate(original.model_dump())
        assert rebuilt == original


# =============================================================================
# EntityId
# =============================================================================


class TestEntityId:
    """Legal-entity identifier invariants."""

    def test_valid_entity_constructs(self) -> None:
        """An entity id constructs from its wrapped string."""
        assert EntityId(id="US-CORP").id == "US-CORP"

    def test_whitespace_stripped(self) -> None:
        """Entity ids are normalized by stripping whitespace."""
        assert EntityId(id=" US-CORP ").id == "US-CORP"

    def test_empty_entity_rejected(self) -> None:
        """An empty entity id is rejected."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            EntityId(id="")

    def test_frozen(self) -> None:
        """EntityId is immutable."""
        entity = EntityId(id="US-CORP")
        with pytest.raises(ValidationError):
            entity.id = "UK-CORP"  # type: ignore[misc]

    def test_serialization_round_trip(self) -> None:
        """EntityId round-trips through serialization."""
        original = EntityId(id="US-CORP")
        assert EntityId.model_validate(original.model_dump()) == original


# =============================================================================
# GLAccountNumber
# =============================================================================


class TestGLAccountNumber:
    """General ledger account number invariants."""

    def test_valid_account_constructs(self) -> None:
        """A GL account number constructs."""
        assert GLAccountNumber(number="4010-100").number == "4010-100"

    def test_whitespace_stripped(self) -> None:
        """Account numbers are stripped of surrounding whitespace."""
        assert GLAccountNumber(number=" 4010 ").number == "4010"

    def test_empty_account_rejected(self) -> None:
        """An empty account number is rejected."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            GLAccountNumber(number="")

    def test_frozen(self) -> None:
        """GLAccountNumber is immutable."""
        account = GLAccountNumber(number="4010")
        with pytest.raises(ValidationError):
            account.number = "5010"  # type: ignore[misc]

    def test_used_in_ledger_lines(self) -> None:
        """Account numbers are usable as ledger line references."""
        from decimal import Decimal

        from business.canonical_types import CurrencyCode, Money
        from business.ontology.ledger import JournalLine

        account = GLAccountNumber(number="1010")
        line = JournalLine(
            account=account,
            debit=Money(amount=Decimal("100.00"), currency=CurrencyCode(code="USD")),
        )
        assert line.account == account


# =============================================================================
# Department
# =============================================================================


class TestDepartmentIdentifier:
    """Department identifier invariants (canonical value object)."""

    def test_valid_department_constructs(self) -> None:
        """A department code constructs."""
        assert Department(code="ENG").code == "ENG"

    def test_lowercase_normalized_to_upper(self) -> None:
        """Department codes are normalized to uppercase."""
        assert Department(code="eng").code == "ENG"

    def test_whitespace_stripped(self) -> None:
        """Surrounding whitespace is stripped."""
        assert Department(code="  SALES ").code == "SALES"

    def test_empty_department_rejected(self) -> None:
        """An empty department code is rejected."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            Department(code="")

    def test_frozen(self) -> None:
        """Department identifiers are immutable."""
        dept = Department(code="ENG")
        with pytest.raises(ValidationError):
            dept.code = "FIN"  # type: ignore[misc]

    def test_str_returns_code(self) -> None:
        """The string representation is the normalized code."""
        assert str(Department(code="eng")) == "ENG"


# =============================================================================
# CostCenter
# =============================================================================


class TestCostCenterIdentifier:
    """Cost center identifier with class-level registry validation."""

    def test_valid_cost_center_constructs(self) -> None:
        """A cost center code constructs."""
        assert CostCenter(code="CC-ENG-001").code == "CC-ENG-001"

    def test_lowercase_normalized_to_upper(self) -> None:
        """Cost center codes are normalized to uppercase."""
        assert CostCenter(code="cc-eng-001").code == "CC-ENG-001"

    def test_empty_cost_center_rejected(self) -> None:
        """An empty cost center code is rejected."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            CostCenter(code="")

    def test_unregistered_is_invalid(self) -> None:
        """An unregistered cost center is not valid by default."""
        assert CostCenter(code="CC-XYZ-999").is_valid is False

    def test_registered_is_valid(self) -> None:
        """A registered cost center validates against the registry."""
        CostCenter.register("CC-TEST-001")
        try:
            assert CostCenter(code="CC-TEST-001").is_valid is True
        finally:
            CostCenter._registry.discard("CC-TEST-001")

    def test_register_normalizes_input(self) -> None:
        """Registration normalizes the code before storing."""
        CostCenter.register("cc-test-002")
        try:
            assert CostCenter(code="CC-TEST-002").is_valid is True
        finally:
            CostCenter._registry.discard("CC-TEST-002")

    def test_frozen(self) -> None:
        """Cost center identifiers are immutable."""
        cc = CostCenter(code="CC-ENG-001")
        with pytest.raises(ValidationError):
            cc.code = "CC-ENG-002"  # type: ignore[misc]


# =============================================================================
# LedgerAccount
# =============================================================================


class TestLedgerAccount:
    """Chart-of-accounts entry with a normal balance direction."""

    def _account(self) -> LedgerAccount:
        """Build a debit-normal cash account."""
        return LedgerAccount(
            number=GLAccountNumber(number="1010"),
            name="Cash - Operating",
            normal_balance="debit",
        )

    def test_valid_debit_account_constructs(self) -> None:
        """A debit-normal account constructs."""
        account = self._account()
        assert account.normal_balance == "debit"
        assert account.name == "Cash - Operating"

    def test_valid_credit_account_constructs(self) -> None:
        """A credit-normal account constructs."""
        account = LedgerAccount(
            number=GLAccountNumber(number="4010"),
            name="Consulting Revenue",
            normal_balance="credit",
        )
        assert account.normal_balance == "credit"

    def test_normal_balance_case_insensitive(self) -> None:
        """The normal balance direction is normalized to lowercase."""
        account = LedgerAccount(
            number=GLAccountNumber(number="1010"),
            name="Cash",
            normal_balance="DEBIT",
        )
        assert account.normal_balance == "debit"

    def test_invalid_normal_balance_rejected(self) -> None:
        """A normal balance other than debit/credit is rejected."""
        with pytest.raises(ValidationError, match="Normal balance"):
            LedgerAccount(
                number=GLAccountNumber(number="1010"),
                name="Cash",
                normal_balance="sideways",
            )

    def test_frozen(self) -> None:
        """LedgerAccount is immutable."""
        account = self._account()
        with pytest.raises(ValidationError):
            account.name = "Changed"  # type: ignore[misc]

    def test_str_representation(self) -> None:
        """The string shows number and name."""
        assert str(self._account()) == "1010 - Cash - Operating"
