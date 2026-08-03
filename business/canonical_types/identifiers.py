"""Typed identifier wrappers for financial domain primitives.

These frozen value objects prevent primitive obsession — exchanging a
CostCenter where a GLAccountNumber is expected is a type error, not
a runtime bug. Each class wraps a string with format validation.
"""

# mypy: disable-error-code="misc,untyped-decorator"

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, field_validator


class GLAccountNumber(BaseModel):
    """A General Ledger account number.

    Format varies by entity but is typically a dot-separated or fixed-width
    number string. Validation is entity-specific; this class enforces
    non-empty and stripped format.

    Usage:
        account = GLAccountNumber("4010-100")
    """

    model_config = ConfigDict(frozen=True)

    number: str

    @field_validator("number")
    @classmethod
    def _validate_number(cls, v: str) -> str:
        normalized = v.strip()
        if not normalized:
            raise ValueError("GL account number cannot be empty")
        return normalized

    def __str__(self) -> str:
        return self.number


class CostCenter(BaseModel):
    """A cost center identifier within the organization.

    Cost centers are alphanumeric codes assigned by the organization to
    track spending by business unit. The optional class-level registry
    enables validation against known cost centers at construction.

    Usage:
        cc = CostCenter("CC-ENG-001")
        CostCenter.register("CC-ENG-001")
        cc.is_valid  # True
    """

    model_config = ConfigDict(frozen=True)

    code: str
    _registry: ClassVar[set[str]] = set()

    @field_validator("code")
    @classmethod
    def _validate_code(cls, v: str) -> str:
        normalized = v.strip().upper()
        if not normalized:
            raise ValueError("Cost center code cannot be empty")
        return normalized

    @classmethod
    def register(cls, code: str) -> None:
        """Register a valid cost center code in the class-level registry.

        Args:
            code: The cost center code to register (will be normalized).
        """
        cls._registry.add(code.strip().upper())

    @property
    def is_valid(self) -> bool:
        """Check whether this cost center exists in the registry."""
        return self.code in self._registry

    def __str__(self) -> str:
        return self.code


class Department(BaseModel):
    """A department identifier within the organization.

    Represents a functional unit such as Engineering, Sales, or Finance.
    """

    model_config = ConfigDict(frozen=True)

    code: str

    @field_validator("code")
    @classmethod
    def _validate_code(cls, v: str) -> str:
        normalized = v.strip().upper()
        if not normalized:
            raise ValueError("Department code cannot be empty")
        return normalized

    def __str__(self) -> str:
        return self.code


class EntityId(BaseModel):
    """A legal entity or tenant identifier.

    In multi-entity deployments, each legal entity (e.g., "US Corp",
    "UK Subsidiary") has a unique identifier used for tenant isolation.
    """

    model_config = ConfigDict(frozen=True)

    id: str

    @field_validator("id")
    @classmethod
    def _validate_id(cls, v: str) -> str:
        normalized = v.strip()
        if not normalized:
            raise ValueError("Entity ID cannot be empty")
        return normalized

    def __str__(self) -> str:
        return self.id


class VendorId(BaseModel):
    """A vendor or supplier identifier.

    References a vendor in the Accounts Payable subsystem. Vendors are
    typically maintained in the ERP vendor master table.
    """

    model_config = ConfigDict(frozen=True)

    id: str

    @field_validator("id")
    @classmethod
    def _validate_id(cls, v: str) -> str:
        normalized = v.strip()
        if not normalized:
            raise ValueError("Vendor ID cannot be empty")
        return normalized

    def __str__(self) -> str:
        return self.id


class LedgerAccount(BaseModel):
    """A chart of accounts entry with a normal balance direction.

    Every account in the general ledger has a normal balance direction:
    - Debit-normal accounts: Assets, Expenses, Dividends
    - Credit-normal accounts: Liabilities, Equity, Revenue

    Usage:
        account = LedgerAccount(
            number=GLAccountNumber("1010"),
            name="Cash - Operating",
            normal_balance="debit",
        )
    """

    model_config = ConfigDict(frozen=True)

    number: GLAccountNumber
    name: str
    normal_balance: str  # "debit" or "credit"

    @field_validator("normal_balance")
    @classmethod
    def _validate_normal_balance(cls, v: str) -> str:
        normalized = v.strip().lower()
        if normalized not in ("debit", "credit"):
            raise ValueError(
                f"Normal balance must be 'debit' or 'credit', got '{v}'"
            )
        return normalized

    def __str__(self) -> str:
        return f"{self.number} - {self.name}"
