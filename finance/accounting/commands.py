"""Frozen command dataclasses for the sandbox accounting boundary.

Commands are immutable value objects: ``JournalLine`` (one double-entry
leg) and ``CorrectingEntryCommand`` (a balanced set of legs bound to a
refund-lag exception). All money is ``Decimal``-only: ``float``/``bool``
inputs are rejected at construction.

Validation is split across two layers on purpose:

- construction enforces *type-level* invariants (Decimal-only money,
  string shapes, known exception codes, ISO currency, tuple-of-lines);
- the adapter enforces *business* rules (account allowlist, balanced
  books, non-empty references, refund-lag-only scope) and raises
  ``ValidationError`` with no record.

This split lets callers build an invalid command and receive the
deterministic adapter verdict, which is what the spec's validation
scenario requires.

Only the Python standard library plus P1 models are used. This module
imports nothing from ``apps/`` or ``agents/``.
"""

import re
from dataclasses import dataclass
from decimal import Decimal

from finance.accounting.errors import FloatMoneyError, ValidationError
from finance.reconciliation.models import ExceptionCode

_CURRENCY_PATTERN = re.compile(r"[A-Z]{3}")

#: The three frozen exception codes admitted on commands. Scope is
#: enforced by the adapter: only the refund-lag code may create.
KNOWN_EXCEPTION_CODES = frozenset(code.value for code in ExceptionCode)


def _require_decimal(field_name: str, value: object) -> Decimal:
    """Validate that a money field is a finite ``Decimal`` instance.

    Args:
        field_name: Field name used in error messages.
        value: The raw value to validate.

    Returns:
        The value narrowed to ``Decimal``.

    Raises:
        FloatMoneyError: If the value is ``float`` or ``bool``.
        ValidationError: If the value is not a finite ``Decimal``.
    """
    if isinstance(value, (bool, float)):
        raise FloatMoneyError(
            f"Field '{field_name}' must be Decimal, got {type(value).__name__}: "
            "float/bool money is rejected, use decimal.Decimal."
        )
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValidationError(
            f"Field '{field_name}' must be a finite Decimal, got {type(value).__name__}."
        )
    return value


@dataclass(frozen=True)
class JournalLine:
    """One double-entry leg: exactly one side carries the amount.

    The adapter requires each line to be one-sided (debit xor credit
    positive, the other zero, neither negative) and the command to
    balance overall. Construction checks types only; sidedness and
    balance are adapter business rules.
    """

    account: str
    debit: Decimal
    credit: Decimal

    def __post_init__(self) -> None:
        """Enforce Decimal-only money and string account shape."""
        if not isinstance(self.account, str):
            raise ValidationError(
                f"Field 'account' must be a string, got {type(self.account).__name__}."
            )
        _require_decimal("debit", self.debit)
        _require_decimal("credit", self.credit)


@dataclass(frozen=True)
class CorrectingEntryCommand:
    """Balanced correcting entry bound to one exception.

    ``exception_type`` MUST be one of the three frozen codes; the
    adapter accepts only the refund-lag code for creation and rejects
    fee-typed commands as ``UnsupportedActionError`` (fee-mismatch is
    proposal-only). ``source_reference`` binds the entry to its
    originating evidence; the adapter rejects empty references.
    """

    tenant_id: str
    exception_id: str
    exception_type: str
    currency: str
    lines: tuple[JournalLine, ...]
    source_reference: str
    memo: str | None = None

    def __post_init__(self) -> None:
        """Enforce type-level invariants; business rules stay in adapter."""
        for field_name in ("tenant_id", "exception_id", "source_reference"):
            if not isinstance(getattr(self, field_name), str):
                raise ValidationError(
                    f"Field '{field_name}' must be a string, "
                    f"got {type(getattr(self, field_name)).__name__}."
                )
        if not isinstance(self.exception_type, str):
            raise ValidationError(
                "Field 'exception_type' must be a string, "
                f"got {type(self.exception_type).__name__}."
            )
        if self.exception_type not in KNOWN_EXCEPTION_CODES:
            raise ValidationError(
                f"Unknown exception_type {self.exception_type!r}: "
                f"must be one of {sorted(KNOWN_EXCEPTION_CODES)}."
            )
        if not isinstance(self.currency, str):
            raise ValidationError(
                f"Field 'currency' must be a string, got {type(self.currency).__name__}."
            )
        if _CURRENCY_PATTERN.fullmatch(self.currency) is None:
            raise ValidationError(
                f"Field 'currency' must be an ISO 4217 code, got {self.currency!r}."
            )
        lines = self.lines
        if isinstance(lines, list):
            lines = tuple(lines)
            object.__setattr__(self, "lines", lines)
        if not isinstance(lines, tuple) or not all(isinstance(line, JournalLine) for line in lines):
            raise ValidationError("Field 'lines' must be a tuple of JournalLine entries.")
        if self.memo is not None and not isinstance(self.memo, str):
            raise ValidationError(
                f"Field 'memo' must be a string or null, got {type(self.memo).__name__}."
            )
