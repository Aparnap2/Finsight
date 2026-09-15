"""Identity models for the FinSight platform (Layer 0, authorization scope).

Reduced scope per plan v3 (``docs/14-platform/implementation-plan.md``, Phase 1):
``Organization -> Tenant -> User -> Role`` plus the ``UserRole`` join model.
The ``Environment`` model is explicitly deferred out of MVP.

All monetary values use ``decimal.Decimal`` — never ``float`` or ``int``. The
local ``MoneyDecimal`` alias rejects ``float``/``int`` at the validation
boundary and is intentionally defined here rather than imported from ``apps``
(a layer violation: ``shared/`` must not import ``apps/``).
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID, uuid4

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

_APPROVAL_ROLES: frozenset[str] = frozenset({"manager", "director", "cfo"})


def _reject_float_int_money(value: Any) -> Any:
    """Reject ``float``/``int`` values for monetary fields; pass others through."""
    if isinstance(value, (float, int)):
        raise ValueError(
            "Float and int values are not allowed for monetary fields. "
            "Use decimal.Decimal or str instead."
        )
    return value


#: Monetary value alias — Decimal-backed, rejects float/int at the boundary.
MoneyDecimal = Annotated[Decimal, Field(), BeforeValidator(_reject_float_int_money)]


def _utcnow() -> datetime:
    """Return the current UTC timestamp (tz-aware)."""
    return datetime.now(UTC)


class Organization(BaseModel):
    """Top-level owning entity in the identity hierarchy."""

    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    code: str
    name: str
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class Tenant(BaseModel):
    """A customer tenant: currency, fiscal calendar, materiality and approval limits."""

    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    organization_id: UUID
    slug: str
    name: str
    currency_code: str = Field(pattern=r"[A-Z]{3}")
    fiscal_year_start_month: int = Field(ge=1, le=12)
    default_materiality_amount: MoneyDecimal = Decimal("0")
    default_materiality_pct: MoneyDecimal = Decimal("0")
    approval_limits: dict[str, MoneyDecimal]

    @field_validator("approval_limits")
    @classmethod
    def _validate_approval_limits(cls, v: dict[str, Decimal]) -> dict[str, Decimal]:
        """Restrict approval-limit keys to the manager/director/cfo roles."""
        unknown = set(v) - _APPROVAL_ROLES
        if unknown:
            raise ValueError(
                f"approval_limits keys must be a subset of {sorted(_APPROVAL_ROLES)}; "
                f"got {sorted(unknown)}"
            )
        return v

    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class User(BaseModel):
    """A user account scoped to a single tenant."""

    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    name: str
    email: str
    tenant_id: UUID
    active: bool = True
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class Role(BaseModel):
    """A named role carrying a set of RBAC permissions."""

    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    name: str
    description: str = ""
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class UserRole(BaseModel):
    """Join model linking a user to a role (many-to-many)."""

    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    role_id: UUID
    created_at: datetime = Field(default_factory=_utcnow)
