"""Canonical payment and reconciliation-result contracts.

This module defines the immutable data contracts of the P1 pure
reconciliation core: the normalized provider-agnostic ``PaymentRecord``
and the deterministic ``ReconciliationResult``.

Only the Python standard library is used (``dataclasses`` plus
``decimal``). All monetary fields are ``Decimal``-only: ``float`` (and
``bool``) inputs are rejected at the validation boundary, and the net
invariant ``net == gross - fee - refund`` is enforced in exact
``Decimal`` arithmetic, mirroring the ``MoneyDecimal`` boundary used
elsewhere in FinSight.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from finance.reconciliation.errors import FloatMoneyError, InvariantViolation

_CURRENCY_PATTERN = re.compile(r"[A-Z]{3}")
_FINGERPRINT_PATTERN = re.compile(r"[0-9a-f]{64}")


class PaymentStatus(StrEnum):
    """Lifecycle status of a normalized payment leg."""

    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    SETTLED = "SETTLED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"
    FAILED = "FAILED"
    VOIDED = "VOIDED"


class ReconciliationOutcome(StrEnum):
    """Terminal verdict of a deterministic reconciliation run.

    ``PENDING_EVIDENCE`` is reserved for the evidence-gated path (later
    phases); the P1 pure reconciler emits the other three outcomes.
    """

    MATCHED = "MATCHED"
    TOLERANCE_MATCHED = "TOLERANCE_MATCHED"
    EXCEPTION = "EXCEPTION"
    PENDING_EVIDENCE = "PENDING_EVIDENCE"


class MaterialityVerdict(StrEnum):
    """Whether the reconciled difference is material against tolerance."""

    MATERIAL = "MATERIAL"
    IMMATERIAL = "IMMATERIAL"


class ExceptionCode(StrEnum):
    """Versioned P0 break-classification codes (the 3 P1 exception types)."""

    PARTIAL_REFUND_ACCOUNTING_LAG = "I-REFUND-LAG"
    FEE_MISMATCH = "I-FEE-DRIFT"
    DUPLICATE_LEDGER_ENTRY = "I-DUPLICATE"


def _require_decimal(field_name: str, value: object) -> Decimal:
    """Validate that a money field is a finite ``Decimal`` instance.

    Args:
        field_name: Field name used in error messages.
        value: The raw value to validate.

    Returns:
        The value narrowed to ``Decimal``.

    Raises:
        FloatMoneyError: If the value is ``float`` or ``bool``.
        InvariantViolation: If the value is not a finite ``Decimal``.
    """
    if isinstance(value, (bool, float)):
        raise FloatMoneyError(
            f"Field '{field_name}' must be Decimal, got {type(value).__name__}: "
            "float/bool money is rejected, use decimal.Decimal."
        )
    if not isinstance(value, Decimal) or not value.is_finite():
        raise InvariantViolation(
            f"Field '{field_name}' must be a finite Decimal, "
            f"got {type(value).__name__}."
        )
    return value


def _require_non_empty(field_name: str, value: object) -> str:
    """Validate that a field is a non-empty string and return it stripped.

    Raises:
        InvariantViolation: If the value is not a non-empty string.
    """
    if not isinstance(value, str) or not value.strip():
        raise InvariantViolation(f"Field '{field_name}' must be a non-empty string.")
    return value.strip()


@dataclass(frozen=True)
class PaymentRecord:
    """Normalized provider-agnostic payment leg.

    All money fields are ``Decimal``-only and the net invariant
    ``net == gross - fee - refund`` holds by construction. Instances are
    immutable and therefore safe to hash, fingerprint, and share across
    deterministic pipeline stages.
    """

    payment_id: str
    provider: str
    provider_event_id: str
    idempotency_key: str
    gross: Decimal
    fee: Decimal
    refund: Decimal
    net: Decimal
    currency: str
    status: PaymentStatus
    occurred_at: datetime
    tenant_id: str
    source_reference: str | None = None

    def __post_init__(self) -> None:
        """Enforce Decimal-only money, identifiers, currency, and net equation."""
        for field_name in ("gross", "fee", "refund", "net"):
            _require_decimal(field_name, getattr(self, field_name))
        for field_name in (
            "payment_id",
            "provider",
            "provider_event_id",
            "idempotency_key",
            "tenant_id",
        ):
            _require_non_empty(field_name, getattr(self, field_name))
        currency_value: object = self.currency
        if not isinstance(currency_value, str):
            raise InvariantViolation("Field 'currency' must be a string.")
        if _CURRENCY_PATTERN.fullmatch(currency_value) is None:
            raise InvariantViolation(
                f"Field 'currency' must be an ISO 4217 code, got {currency_value!r}."
            )
        status_value: object = self.status
        if isinstance(status_value, PaymentStatus):
            status = status_value
        elif isinstance(status_value, str):
            try:
                status = PaymentStatus(status_value.strip().upper())
            except ValueError as exc:
                raise InvariantViolation(
                    f"Unknown payment status {status_value!r}."
                ) from exc
            object.__setattr__(self, "status", status)
        else:
            raise InvariantViolation(
                "Field 'status' must be a PaymentStatus or status name, "
                f"got {type(status_value).__name__}."
            )
        occurred_value: object = self.occurred_at
        if not isinstance(occurred_value, datetime):
            raise InvariantViolation("Field 'occurred_at' must be a datetime.")
        tzinfo = occurred_value.tzinfo
        if tzinfo is None or tzinfo.utcoffset(occurred_value) is None:
            raise InvariantViolation("Field 'occurred_at' must be tz-aware.")
        source_value: object = self.source_reference
        if source_value is not None and not isinstance(source_value, str):
            raise InvariantViolation("Field 'source_reference' must be a string or null.")
        if self.net != self.gross - self.fee - self.refund:
            raise InvariantViolation(
                f"net invariant violated: net={self.net} != "
                f"gross - fee - refund={self.gross - self.fee - self.refund}."
            )


@dataclass(frozen=True)
class ReconciliationResult:
    """Deterministic outcome of reconciling an expected/observed leg pair.

    ``expected``/``observed`` hold the legs' net amounts; ``difference``
    is ``observed - expected`` and ``variance`` is ``abs(difference)``.
    ``exception_code`` is an I-code when (and only when) ``outcome`` is
    ``EXCEPTION``. ``fingerprint`` binds the canonical leg pair.
    """

    outcome: ReconciliationOutcome
    expected: Decimal
    observed: Decimal
    difference: Decimal
    variance: Decimal
    tolerance_applied: Decimal
    currency: str
    exception_code: str | None
    fingerprint: str
    materiality: MaterialityVerdict

    def __post_init__(self) -> None:
        """Enforce money arithmetic, outcome/code coupling, and formats."""
        for field_name in (
            "expected",
            "observed",
            "difference",
            "variance",
            "tolerance_applied",
        ):
            _require_decimal(field_name, getattr(self, field_name))
        if self.difference != self.observed - self.expected:
            raise InvariantViolation(
                "difference must equal observed - expected in Decimal arithmetic."
            )
        if self.variance != abs(self.difference):
            raise InvariantViolation("variance must equal abs(difference).")
        currency_value: object = self.currency
        if not isinstance(currency_value, str):
            raise InvariantViolation("Field 'currency' must be a string.")
        if _CURRENCY_PATTERN.fullmatch(currency_value) is None:
            raise InvariantViolation(
                f"Field 'currency' must be an ISO 4217 code, got {currency_value!r}."
            )
        outcome = self._coerce_outcome()
        object.__setattr__(self, "outcome", outcome)
        code_value: object = self.exception_code
        if outcome is ReconciliationOutcome.EXCEPTION:
            if not isinstance(code_value, str) or not code_value:
                raise InvariantViolation(
                    "exception_code (I-code) is required when outcome is EXCEPTION."
                )
        elif code_value is not None:
            raise InvariantViolation(
                "exception_code must be null unless outcome is EXCEPTION."
            )
        fingerprint_value: object = self.fingerprint
        if not isinstance(fingerprint_value, str):
            raise InvariantViolation("Field 'fingerprint' must be a string.")
        if _FINGERPRINT_PATTERN.fullmatch(fingerprint_value) is None:
            raise InvariantViolation("Field 'fingerprint' must be a sha256 hex digest.")
        materiality = self._coerce_materiality()
        object.__setattr__(self, "materiality", materiality)

    def _coerce_outcome(self) -> ReconciliationOutcome:
        """Coerce a raw string outcome to the enum, rejecting unknowns."""
        outcome_value: object = self.outcome
        if isinstance(outcome_value, ReconciliationOutcome):
            return outcome_value
        if isinstance(outcome_value, str):
            try:
                return ReconciliationOutcome(outcome_value.strip().upper())
            except ValueError as exc:
                raise InvariantViolation(
                    f"Unknown reconciliation outcome {outcome_value!r}."
                ) from exc
        raise InvariantViolation(
            "Field 'outcome' must be a ReconciliationOutcome or outcome name, "
            f"got {type(outcome_value).__name__}."
        )

    def _coerce_materiality(self) -> MaterialityVerdict:
        """Coerce a raw string verdict to the enum, rejecting unknowns."""
        materiality_value: object = self.materiality
        if isinstance(materiality_value, MaterialityVerdict):
            return materiality_value
        if isinstance(materiality_value, str):
            try:
                return MaterialityVerdict(materiality_value.strip().upper())
            except ValueError as exc:
                raise InvariantViolation(
                    f"Unknown materiality verdict {materiality_value!r}."
                ) from exc
        raise InvariantViolation(
            "Field 'materiality' must be a MaterialityVerdict or verdict name, "
            f"got {type(materiality_value).__name__}."
        )
