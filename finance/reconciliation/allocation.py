"""Deterministic allocation of one bank deposit to payment charges.

The reconciliation triangle (invoice → charge → bank deposit) cannot be
closed by pairwise matching: one deposit may settle several charges, a
charge may be split across deposits, and a bank fee may arrive netted
into the deposit. This module owns the deposit-to-charge edge as a
deterministic subset search with explicit, human-readable outcomes.

Invariants (see ``openspec/changes/add-bank-payout-reconciliation``):

* Money is ``Decimal``-only and is never quantized here. A residual that
  cannot be explained is reported, never rounded away or clamped.
* Conservation is checked in ``Allocation.__post_init__``:
  ``allocated_total + unallocated_deposit == deposit.amount`` and
  ``allocated_total + open_balance == eligible_net_total``.
* Ambiguity is an outcome (``REQUIRES_HUMAN`` / ``AMBIGUOUS``), never an
  arbitrary pick. The candidate bound fails closed the same way.
* Absence of evidence (``deposit is None``, empty candidate set, deposit
  outside the window) is ``PENDING_EVIDENCE``, never a mismatch.
* Tenant scope comes from the trusted record and is enforced before any
  enumeration; a foreign charge raises ``TenantIsolationError``.
* Allocation fingerprints are order-independent, so replaying identical
  inputs yields the identical fingerprint.

Pure and deterministic: no LLM, database, network, clock reads, or
randomness. Only the standard library is used.
"""

import hashlib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from itertools import combinations

from finance.reconciliation.bank import (
    BankDepositRecord,
    canonical_deposit,
)
from finance.reconciliation.errors import (
    CurrencyMismatch,
    InvariantViolation,
    TenantIsolationError,
)
from finance.reconciliation.fingerprints import fingerprint_payment
from finance.reconciliation.models import (
    ExceptionCode,
    PaymentRecord,
    PayoutOutcome,
)
from finance.reconciliation.tolerances import ReconciliationTolerance

ZERO = Decimal("0")
MAX_ALLOCATION_CANDIDATES = 20
_FINGERPRINT_PATTERN = re.compile(r"[0-9a-f]{64}")
_CANONICAL_SEPARATOR = "\x1f"
_LEG_SEPARATOR = "\x1e"
_MAX_SURFACED_CANDIDATES = 2


class PayoutReason(StrEnum):
    """Deterministic explanation attached to every non-closing outcome."""

    PARTIAL = "PARTIAL"
    FEE_DRIFT = "FEE_DRIFT"
    REFUND_LAG = "REFUND_LAG"
    DUPLICATE = "DUPLICATE"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    UNALLOCATED_DEPOSIT = "UNALLOCATED_DEPOSIT"
    NO_DEPOSIT = "NO_DEPOSIT"
    OUTSIDE_WINDOW = "OUTSIDE_WINDOW"
    NO_CANDIDATE = "NO_CANDIDATE"
    CANDIDATE_LIMIT = "CANDIDATE_LIMIT"
    AMBIGUOUS = "AMBIGUOUS"
    FX_UNSUPPORTED = "FX_UNSUPPORTED"


@dataclass(frozen=True)
class AllocationLeg:
    """One charge inside an allocation and the amount credited to it.

    ``allocated`` equals ``net`` for a fully settled charge and is smaller
    than ``net`` only when the deposit absorbs part of a single charge; the
    remainder is surfaced as ``open_balance``, never guessed away.
    """

    payment_id: str
    fingerprint: str
    gross: Decimal
    fee: Decimal
    refund: Decimal
    net: Decimal
    allocated: Decimal

    def __post_init__(self) -> None:
        """Validate identifiers, digest, Decimal money, and the leg identity."""
        if not isinstance(self.payment_id, str) or not self.payment_id.strip():
            raise InvariantViolation("payment_id must be a non-empty string.")
        fingerprint_value: object = self.fingerprint
        if (
            not isinstance(fingerprint_value, str)
            or _FINGERPRINT_PATTERN.fullmatch(fingerprint_value) is None
        ):
            raise InvariantViolation("fingerprint must be a sha256 hex digest.")
        for field_name in ("gross", "fee", "refund", "net", "allocated"):
            value: object = getattr(self, field_name)
            if not isinstance(value, Decimal) or not value.is_finite():
                raise InvariantViolation(f"Leg field '{field_name}' must be a finite Decimal.")
        if self.net != self.gross - self.fee - self.refund:
            raise InvariantViolation("Leg invariant broken: net must equal gross - fee - refund.")
        if self.allocated <= ZERO:
            raise InvariantViolation("Leg allocated amount must be positive.")
        if self.allocated > self.net:
            raise InvariantViolation("Leg allocated amount cannot exceed the charge net.")

    def canonical(self) -> str:
        """Return the canonical string form used in allocation digests."""
        return _CANONICAL_SEPARATOR.join(
            (self.payment_id, self.fingerprint, format(self.net, "f"), format(self.allocated, "f"))
        )


@dataclass(frozen=True)
class CandidateAllocation:
    """One plausible allocation surfaced when the search is ambiguous."""

    payment_ids: tuple[str, ...]
    total: Decimal

    def __post_init__(self) -> None:
        """Require a non-empty, unique, sorted id set and finite money."""
        ids: object = self.payment_ids
        if not isinstance(ids, tuple) or not ids:
            raise InvariantViolation("payment_ids must be a non-empty tuple.")
        for payment_id in ids:
            if not isinstance(payment_id, str) or not payment_id.strip():
                raise InvariantViolation("Candidate ids must be non-empty strings.")
        if len(set(ids)) != len(ids):
            raise InvariantViolation("Candidate ids must be unique.")
        if tuple(sorted(ids)) != ids:
            raise InvariantViolation("Candidate ids must be sorted for determinism.")
        total_value: object = self.total
        if not isinstance(total_value, Decimal) or not total_value.is_finite():
            raise InvariantViolation("Candidate total must be a finite Decimal.")


@dataclass(frozen=True)
class Allocation:
    """Immutable result of allocating (or refusing to allocate) a deposit.

    ``deposit is None`` is only valid for ``PENDING_EVIDENCE`` where the
    missing evidence *is* the deposit.
    """

    outcome: PayoutOutcome
    reason: PayoutReason | None
    exception_code: ExceptionCode | None
    tenant_id: str
    currency: str
    deposit: BankDepositRecord | None = None
    legs: tuple[AllocationLeg, ...] = ()
    candidates: tuple[CandidateAllocation, ...] = ()
    eligible_net_total: Decimal = ZERO
    allocated_total: Decimal = ZERO
    unallocated_deposit: Decimal = ZERO
    open_balance: Decimal = ZERO
    fee_total: Decimal = ZERO
    refund_total: Decimal = ZERO
    fingerprint: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        """Enforce outcome/code coupling and the conservation equations."""
        if not isinstance(self.outcome, PayoutOutcome):
            raise InvariantViolation("outcome must be a PayoutOutcome.")
        if self.reason is not None and not isinstance(self.reason, PayoutReason):
            raise InvariantViolation("reason must be a PayoutReason or None.")
        if self.exception_code is not None and not isinstance(self.exception_code, ExceptionCode):
            raise InvariantViolation("exception_code must be an ExceptionCode or None.")
        if not isinstance(self.tenant_id, str) or not self.tenant_id.strip():
            raise InvariantViolation("tenant_id must be a non-empty string.")
        if not isinstance(self.currency, str) or len(self.currency) != 3:
            raise InvariantViolation("currency must be a 3-letter code.")
        deposit_value: object = self.deposit
        if deposit_value is not None and not isinstance(deposit_value, BankDepositRecord):
            raise InvariantViolation("deposit must be a BankDepositRecord or None.")
        if (
            self.outcome
            in (
                PayoutOutcome.PENDING_EVIDENCE,
                PayoutOutcome.REQUIRES_HUMAN,
            )
            and self.reason is None
        ):
            raise InvariantViolation("An open outcome requires a reason.")
        if self.outcome in (
            PayoutOutcome.MATCHED,
            PayoutOutcome.TOLERANCE_MATCHED,
        ) and (self.reason is not None or self.exception_code is not None):
            raise InvariantViolation("A closed allocation carries no reason or code.")
        if self.outcome is PayoutOutcome.EXCEPTION and (
            self.exception_code is None or self.reason is None
        ):
            raise InvariantViolation("EXCEPTION requires an exception_code and reason.")
        if (self.reason is PayoutReason.AMBIGUOUS) != bool(self.candidates):
            raise InvariantViolation("candidates are present if and only if AMBIGUOUS.")
        if len({leg.payment_id for leg in self.legs}) != len(self.legs):
            raise InvariantViolation("Allocation legs must be unique per payment.")
        if tuple(sorted(self.legs, key=lambda leg: leg.payment_id)) != self.legs:
            raise InvariantViolation("Allocation legs must be sorted by payment_id.")
        for field_name in (
            "eligible_net_total",
            "allocated_total",
            "unallocated_deposit",
            "open_balance",
            "fee_total",
            "refund_total",
        ):
            value: object = getattr(self, field_name)
            if not isinstance(value, Decimal) or not value.is_finite():
                raise InvariantViolation(
                    f"Allocation field '{field_name}' must be a finite Decimal."
                )
        leg_fee = _total(leg.fee for leg in self.legs)
        leg_refund = _total(leg.refund for leg in self.legs)
        if self.allocated_total != _total(leg.allocated for leg in self.legs):
            raise InvariantViolation("allocated_total must equal the sum of leg allocations.")
        if self.fee_total != leg_fee:
            raise InvariantViolation("fee_total must equal the sum of leg fees.")
        if self.refund_total != leg_refund:
            raise InvariantViolation("refund_total must equal the sum of leg refunds.")
        if self.allocated_total + self.open_balance != self.eligible_net_total:
            raise InvariantViolation(
                "Conservation broken: allocated_total + open_balance must equal "
                "the eligible charge net total."
            )
        if deposit_value is None:
            if self.unallocated_deposit != ZERO:
                raise InvariantViolation("A missing deposit cannot have a residual.")
        elif self.allocated_total + self.unallocated_deposit != deposit_value.amount:
            raise InvariantViolation(
                "Conservation broken: allocated_total + unallocated_deposit must "
                "equal deposit.amount."
            )
        fingerprint_value: object = self.fingerprint
        if not isinstance(fingerprint_value, str):
            raise InvariantViolation("fingerprint must be a string.")
        if fingerprint_value:
            if _FINGERPRINT_PATTERN.fullmatch(fingerprint_value) is None:
                raise InvariantViolation("fingerprint must be a sha256 hex digest.")
        else:
            object.__setattr__(
                self,
                "fingerprint",
                _allocation_fingerprint(
                    deposit_value,
                    self.legs,
                    self.candidates,
                    self.eligible_net_total,
                    self.allocated_total,
                    self.unallocated_deposit,
                    self.open_balance,
                    self.outcome,
                    self.reason,
                ),
            )


def _total(values: Iterable[Decimal]) -> Decimal:
    """Sum Decimal values deterministically from zero."""
    total = ZERO
    for value in values:
        total += value
    return total


def _allocation_fingerprint(
    deposit: BankDepositRecord | None,
    legs: Sequence[AllocationLeg],
    candidates: Sequence[CandidateAllocation],
    eligible_net_total: Decimal,
    allocated_total: Decimal,
    unallocated_deposit: Decimal,
    open_balance: Decimal,
    outcome: PayoutOutcome,
    reason: PayoutReason | None,
) -> str:
    """Compute an order-independent digest of an allocation result."""
    deposit_key = "-" if deposit is None else canonical_deposit(deposit)
    leg_key = _LEG_SEPARATOR.join(sorted(leg.canonical() for leg in legs))
    candidate_key = _LEG_SEPARATOR.join(
        sorted(
            _CANONICAL_SEPARATOR.join((*candidate.payment_ids, format(candidate.total, "f")))
            for candidate in candidates
        )
    )
    parts = (
        deposit_key,
        leg_key,
        candidate_key,
        format(eligible_net_total, "f"),
        format(allocated_total, "f"),
        format(unallocated_deposit, "f"),
        format(open_balance, "f"),
        outcome.value,
        "-" if reason is None else reason.value,
    )
    return hashlib.sha256(_CANONICAL_SEPARATOR.join(parts).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class _Search:
    """What the bounded subset search found."""

    exact: tuple[tuple[int, ...], ...] = ()
    tolerant: tuple[tuple[int, ...], ...] = ()
    best: tuple[int, ...] = ()
    best_total: Decimal = ZERO
    best_ties: tuple[tuple[int, ...], ...] = ()


def _search_subsets(
    charges: Sequence[PaymentRecord],
    amount: Decimal,
    tolerance: ReconciliationTolerance,
) -> _Search:
    """Enumerate non-empty subsets for exact, tolerant, and best-under fits.

    The caller bounds the candidate count, so this stays deterministic
    and finite. Two exact fits are enough to declare ambiguity; two
    tolerance fits are recorded but the scan continues, because an exact
    fit anywhere later takes precedence.
    """
    indices = range(len(charges))
    exact: list[tuple[int, ...]] = []
    tolerant: list[tuple[int, ...]] = []
    best: tuple[int, ...] = ()
    best_total = ZERO
    best_ties: list[tuple[int, ...]] = []
    for size in range(1, len(charges) + 1):
        for subset in combinations(indices, size):
            subtotal = _total(charges[index].net for index in subset)
            if subtotal == amount:
                exact.append(subset)
                if len(exact) == _MAX_SURFACED_CANDIDATES:
                    return _Search(
                        exact=tuple(exact),
                        tolerant=tuple(tolerant[:_MAX_SURFACED_CANDIDATES]),
                        best=best,
                        best_total=best_total,
                        best_ties=tuple(best_ties),
                    )
                continue
            if subtotal < amount and tolerance.allows(amount - subtotal, amount):
                if len(tolerant) < _MAX_SURFACED_CANDIDATES:
                    tolerant.append(subset)
                continue
            if subtotal < amount:
                if subtotal > best_total:
                    best = subset
                    best_total = subtotal
                    best_ties = [subset]
                elif subtotal == best_total and subtotal > ZERO:
                    if len(best_ties) < _MAX_SURFACED_CANDIDATES:
                        best_ties.append(subset)
    return _Search(
        exact=tuple(exact[:_MAX_SURFACED_CANDIDATES]),
        tolerant=tuple(tolerant[:_MAX_SURFACED_CANDIDATES]),
        best=best,
        best_total=best_total,
        best_ties=tuple(best_ties),
    )


def _leg_for(charge: PaymentRecord, allocated: Decimal | None = None) -> AllocationLeg:
    """Build the leg for one charge, defaulting to full settlement."""
    credited = charge.net if allocated is None else allocated
    return AllocationLeg(
        payment_id=charge.payment_id,
        fingerprint=fingerprint_payment(charge),
        gross=charge.gross,
        fee=charge.fee,
        refund=charge.refund,
        net=charge.net,
        allocated=credited,
    )


def _legs_for(charges: Sequence[PaymentRecord], subset: Sequence[int]) -> tuple[AllocationLeg, ...]:
    """Build sorted legs for an index subset."""
    return tuple(
        sorted(
            (_leg_for(charges[index]) for index in subset),
            key=lambda leg: leg.payment_id,
        )
    )


def _candidate_for(charges: Sequence[PaymentRecord], subset: Sequence[int]) -> CandidateAllocation:
    """Describe one plausible allocation without committing to it."""
    return CandidateAllocation(
        payment_ids=tuple(sorted(charges[index].payment_id for index in subset)),
        total=_total(charges[index].net for index in subset),
    )


def _build(
    *,
    outcome: PayoutOutcome,
    reason: PayoutReason | None,
    exception_code: ExceptionCode | None,
    deposit: BankDepositRecord | None,
    tenant_id: str,
    currency: str,
    legs: tuple[AllocationLeg, ...],
    candidates: tuple[CandidateAllocation, ...],
    scope: Sequence[PaymentRecord],
    unallocated_deposit: Decimal,
) -> Allocation:
    """Assemble an allocation, deriving totals from the legs and scope."""
    allocated_total = _total(leg.allocated for leg in legs)
    eligible_net_total = _total(charge.net for charge in scope)
    return Allocation(
        outcome=outcome,
        reason=reason,
        exception_code=exception_code,
        tenant_id=tenant_id,
        currency=currency,
        deposit=deposit,
        legs=legs,
        candidates=candidates,
        eligible_net_total=eligible_net_total,
        allocated_total=allocated_total,
        unallocated_deposit=unallocated_deposit,
        open_balance=eligible_net_total - allocated_total,
        fee_total=_total(leg.fee for leg in legs),
        refund_total=_total(leg.refund for leg in legs),
    )


def _validate_inputs(
    deposit: BankDepositRecord | None,
    charges: Sequence[PaymentRecord],
    tolerance: ReconciliationTolerance,
    *,
    window_seconds: int | None,
    duplicate: bool,
    max_candidates: int,
) -> tuple[str, str]:
    """Validate types, tenant isolation, and one currency; return scope keys."""
    deposit_value: object = deposit
    if deposit_value is not None and not isinstance(deposit_value, BankDepositRecord):
        raise InvariantViolation("deposit must be a BankDepositRecord or None.")
    charges_value: object = charges
    if not isinstance(charges_value, Sequence) or isinstance(charges_value, (str, bytes)):
        raise InvariantViolation("charges must be a sequence of PaymentRecord.")
    if not charges_value and deposit_value is None:
        raise InvariantViolation("charges must be non-empty when no deposit is supplied.")
    tolerance_value: object = tolerance
    if not isinstance(tolerance_value, ReconciliationTolerance):
        raise InvariantViolation("tolerance must be a ReconciliationTolerance.")
    for index, charge in enumerate(charges_value):
        charge_value: object = charge
        if not isinstance(charge_value, PaymentRecord):
            raise InvariantViolation(
                f"charges[{index}] must be a PaymentRecord, got {type(charge_value).__name__}."
            )
    if window_seconds is not None:
        if isinstance(window_seconds, bool) or not isinstance(window_seconds, int):
            raise InvariantViolation("window_seconds must be an int or None.")
        if window_seconds < 0:
            raise InvariantViolation("window_seconds must be non-negative.")
    if not isinstance(duplicate, bool):
        raise InvariantViolation("duplicate must be a bool.")
    if isinstance(max_candidates, bool) or not isinstance(max_candidates, int):
        raise InvariantViolation("max_candidates must be an int.")
    if max_candidates < 1:
        raise InvariantViolation("max_candidates must be >= 1.")
    if deposit_value is None:
        tenant = charges_value[0].tenant_id
        currency = charges_value[0].currency
        for charge in charges_value:
            if charge.tenant_id != tenant:
                raise TenantIsolationError(
                    f"Payout spans multiple tenants: {tenant!r} and {charge.tenant_id!r}."
                )
            if charge.currency != currency:
                raise CurrencyMismatch(currency, charge.currency, "reconcile_payout")
        return tenant, currency
    tenant = deposit_value.tenant_id
    currency = deposit_value.currency
    for charge in charges_value:
        if charge.tenant_id != tenant:
            raise TenantIsolationError(
                f"Charge tenant does not match deposit tenant: {charge.tenant_id!r} != {tenant!r}."
            )
        if charge.currency != currency:
            raise CurrencyMismatch(currency, charge.currency, "allocate_deposit")
    return tenant, currency


def _in_window(
    deposit: BankDepositRecord,
    charge: PaymentRecord,
    window_seconds: int | None,
) -> bool:
    """Return whether a charge occurred inside the deposit window."""
    if window_seconds is None:
        return True
    delta = abs((deposit.posted_at - charge.occurred_at).total_seconds())
    return delta <= window_seconds


def _ambiguous(
    subsets: Sequence[Sequence[int]],
    eligible: Sequence[PaymentRecord],
    deposit: BankDepositRecord,
    tenant_id: str,
    currency: str,
    scope: Sequence[PaymentRecord],
) -> Allocation:
    """Build a fail-closed ambiguous result from at least two subsets."""
    candidates = tuple(
        sorted(
            (_candidate_for(eligible, subset) for subset in subsets[:2]),
            key=lambda candidate: candidate.payment_ids,
        )
    )
    return _build(
        outcome=PayoutOutcome.REQUIRES_HUMAN,
        reason=PayoutReason.AMBIGUOUS,
        exception_code=None,
        deposit=deposit,
        tenant_id=tenant_id,
        currency=currency,
        legs=(),
        candidates=candidates,
        scope=scope,
        unallocated_deposit=deposit.amount,
    )


def _classify_residual(
    eligible: Sequence[PaymentRecord],
    deposit: BankDepositRecord,
    allocated_total: Decimal,
    unallocated: Decimal,
    open_balance: Decimal,
    fee_total: Decimal,
    *,
    duplicate: bool,
) -> tuple[ExceptionCode, PayoutReason]:
    """Explain a residual by precedence: duplicate, partial, refund, fee, over-deposit.

    Duplicate evidence outranks every residual explanation: a re-import whose
    amount drifted is unsafe evidence, and reporting it as a partial, fee, or
    refund outcome would hide the duplicate. ``I-PARTIAL`` requires a charge to
    have absorbed part of its net; when nothing fits and there is more than one
    charge, no partial allocation is invented and ``I-PAYOUT`` is reported
    instead.
    """
    if duplicate:
        return ExceptionCode.DUPLICATE_LEDGER_ENTRY, PayoutReason.DUPLICATE
    refunds = {charge.refund for charge in eligible if charge.refund > ZERO}
    if open_balance > ZERO and allocated_total > ZERO:
        return ExceptionCode.PARTIAL_SETTLEMENT, PayoutReason.PARTIAL
    if allocated_total == ZERO and unallocated > ZERO:
        return ExceptionCode.PAYOUT_MISMATCH, PayoutReason.NO_CANDIDATE
    if unallocated > ZERO and unallocated in refunds:
        return ExceptionCode.PARTIAL_REFUND_ACCOUNTING_LAG, PayoutReason.REFUND_LAG
    if unallocated > ZERO and fee_total > ZERO and unallocated != fee_total:
        return ExceptionCode.FEE_MISMATCH, PayoutReason.FEE_DRIFT
    if unallocated > ZERO:
        return ExceptionCode.PAYOUT_MISMATCH, PayoutReason.UNALLOCATED_DEPOSIT
    return ExceptionCode.PAYOUT_MISMATCH, PayoutReason.NO_CANDIDATE


def allocate_deposit(
    deposit: BankDepositRecord,
    charges: Sequence[PaymentRecord],
    tolerance: ReconciliationTolerance,
    *,
    window_seconds: int | None = None,
    duplicate: bool = False,
    max_candidates: int = MAX_ALLOCATION_CANDIDATES,
) -> Allocation:
    """Allocate one known deposit against the eligible charges.

    Args:
        deposit: Normalized bank deposit evidence.
        charges: Candidate charges from the tenant's ledger.
        tolerance: Tolerance applied to a non-exact residual.
        window_seconds: Optional maximum |posted_at - occurred_at|.
        duplicate: Mark the result ``I-DUPLICATE`` even when amounts fit.
        max_candidates: Hard ceiling on enumerated eligible charges.

    Returns:
        A conservation-checked ``Allocation`` with a deterministic reason.

    Raises:
        TenantIsolationError: If a charge belongs to another tenant.
        CurrencyMismatch: If a charge currency differs from the deposit.
        InvariantViolation: For malformed input.
    """
    tenant, currency = _validate_inputs(
        deposit,
        charges,
        tolerance,
        window_seconds=window_seconds,
        duplicate=duplicate,
        max_candidates=max_candidates,
    )
    if not charges:
        return _build(
            outcome=PayoutOutcome.PENDING_EVIDENCE,
            reason=PayoutReason.NO_CANDIDATE,
            exception_code=None,
            deposit=deposit,
            tenant_id=tenant,
            currency=currency,
            legs=(),
            candidates=(),
            scope=(),
            unallocated_deposit=deposit.amount,
        )
    in_window = tuple(charge for charge in charges if _in_window(deposit, charge, window_seconds))
    if not in_window:
        return _build(
            outcome=PayoutOutcome.PENDING_EVIDENCE,
            reason=PayoutReason.OUTSIDE_WINDOW,
            exception_code=None,
            deposit=deposit,
            tenant_id=tenant,
            currency=currency,
            legs=(),
            candidates=(),
            scope=tuple(charges),
            unallocated_deposit=deposit.amount,
        )
    eligible = tuple(charge for charge in in_window if charge.net > ZERO)
    if not eligible:
        return _build(
            outcome=PayoutOutcome.PENDING_EVIDENCE,
            reason=PayoutReason.NO_CANDIDATE,
            exception_code=None,
            deposit=deposit,
            tenant_id=tenant,
            currency=currency,
            legs=(),
            candidates=(),
            scope=in_window,
            unallocated_deposit=deposit.amount,
        )
    if len(eligible) > max_candidates:
        return _build(
            outcome=PayoutOutcome.REQUIRES_HUMAN,
            reason=PayoutReason.CANDIDATE_LIMIT,
            exception_code=None,
            deposit=deposit,
            tenant_id=tenant,
            currency=currency,
            legs=(),
            candidates=(),
            scope=in_window,
            unallocated_deposit=deposit.amount,
        )
    search = _search_subsets(eligible, deposit.amount, tolerance)
    if len(search.exact) > 1:
        return _ambiguous(search.exact, eligible, deposit, tenant, currency, in_window)
    if len(search.tolerant) > 1 and not search.exact:
        return _ambiguous(search.tolerant, eligible, deposit, tenant, currency, in_window)
    if search.exact or search.tolerant:
        subset = search.exact[0] if search.exact else search.tolerant[0]
        legs = _legs_for(eligible, subset)
        unallocated = deposit.amount - _total(leg.allocated for leg in legs)
        if duplicate:
            return _build(
                outcome=PayoutOutcome.EXCEPTION,
                reason=PayoutReason.DUPLICATE,
                exception_code=ExceptionCode.DUPLICATE_LEDGER_ENTRY,
                deposit=deposit,
                tenant_id=tenant,
                currency=currency,
                legs=legs,
                candidates=(),
                scope=in_window,
                unallocated_deposit=unallocated,
            )
        return _build(
            outcome=(PayoutOutcome.MATCHED if search.exact else PayoutOutcome.TOLERANCE_MATCHED),
            reason=None,
            exception_code=None,
            deposit=deposit,
            tenant_id=tenant,
            currency=currency,
            legs=legs,
            candidates=(),
            scope=in_window,
            unallocated_deposit=unallocated,
        )
    if len(search.best_ties) > 1:
        return _ambiguous(search.best_ties, eligible, deposit, tenant, currency, in_window)
    if len(eligible) == 1 and deposit.amount < eligible[0].net:
        leg = _leg_for(eligible[0], deposit.amount)
        code, reason = _classify_residual(
            eligible,
            deposit,
            deposit.amount,
            ZERO,
            eligible[0].net - deposit.amount,
            leg.fee,
            duplicate=duplicate,
        )
        return _build(
            outcome=PayoutOutcome.EXCEPTION,
            reason=reason,
            exception_code=code,
            deposit=deposit,
            tenant_id=tenant,
            currency=currency,
            legs=(leg,),
            candidates=(),
            scope=in_window,
            unallocated_deposit=ZERO,
        )
    legs = _legs_for(eligible, search.best) if search.best else ()
    allocated = _total(leg.allocated for leg in legs)
    unallocated = deposit.amount - allocated
    open_balance = _total(charge.net for charge in in_window) - allocated
    code, reason = _classify_residual(
        eligible,
        deposit,
        allocated,
        unallocated,
        open_balance,
        _total(leg.fee for leg in legs),
        duplicate=duplicate,
    )
    return _build(
        outcome=PayoutOutcome.EXCEPTION,
        reason=reason,
        exception_code=code,
        deposit=deposit,
        tenant_id=tenant,
        currency=currency,
        legs=legs,
        candidates=(),
        scope=in_window,
        unallocated_deposit=unallocated,
    )


def reconcile_payout(
    deposit: BankDepositRecord | None,
    charges: Sequence[PaymentRecord],
    tolerance: ReconciliationTolerance,
    *,
    window_seconds: int | None = None,
    duplicate: bool = False,
    max_candidates: int = MAX_ALLOCATION_CANDIDATES,
) -> Allocation:
    """Reconcile the deposit side of the triangle, including its absence.

    ``deposit=None`` is explicit missing evidence: the result is
    ``PENDING_EVIDENCE`` / ``NO_DEPOSIT`` with every charge left open, not
    a mismatch and not a success.

    Args:
        deposit: Normalized bank deposit, or ``None`` when not yet seen.
        charges: Candidate charges from the tenant's ledger.
        tolerance: Tolerance applied to a non-exact residual.
        window_seconds: Optional maximum |posted_at - occurred_at|.
        duplicate: Mark an amount fit as ``I-DUPLICATE``.
        max_candidates: Hard ceiling on enumerated eligible charges.

    Returns:
        A conservation-checked ``Allocation``.

    Raises:
        TenantIsolationError: If the charges span tenants.
        CurrencyMismatch: If the charges span currencies.
        InvariantViolation: For malformed input.
    """
    tenant, currency = _validate_inputs(
        deposit,
        charges,
        tolerance,
        window_seconds=window_seconds,
        duplicate=duplicate,
        max_candidates=max_candidates,
    )
    if deposit is not None:
        return allocate_deposit(
            deposit,
            charges,
            tolerance,
            window_seconds=window_seconds,
            duplicate=duplicate,
            max_candidates=max_candidates,
        )
    if len(charges) > max_candidates:
        return _build(
            outcome=PayoutOutcome.REQUIRES_HUMAN,
            reason=PayoutReason.CANDIDATE_LIMIT,
            exception_code=None,
            deposit=None,
            tenant_id=tenant,
            currency=currency,
            legs=(),
            candidates=(),
            scope=charges,
            unallocated_deposit=ZERO,
        )
    return _build(
        outcome=PayoutOutcome.PENDING_EVIDENCE,
        reason=PayoutReason.NO_DEPOSIT,
        exception_code=None,
        deposit=None,
        tenant_id=tenant,
        currency=currency,
        legs=(),
        candidates=(),
        scope=charges,
        unallocated_deposit=ZERO,
    )
