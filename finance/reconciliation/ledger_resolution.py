"""Commit 3B: deterministic ledger lookup -> frozen P1 reconcile -> verdict, STOP.

Scope (exception-resolution track, Commit 3B ONLY):

1. Deterministic ledger lookup keyed by ``(tenant_id, provider, payment_id)``
   against a fixture/repository boundary (``InMemoryLedgerRepository`` seeded
   from ``tests/fixtures/reconciliation/stripe/ledger_legs.json``). No
   Sheets/QuickBooks adapters, no probabilistic or fuzzy matching: an exact
   triple either hits or it deterministically misses.
2. Invoke the frozen P1 :func:`reconcile` (``finance/reconciliation`` core,
   NOT modified here) with the canonical processor leg and the looked-up
   ledger leg.
3. Return ``MATCHED`` (CLOSED-path data: zero diff, no exception code) or
   ``EXCEPTION`` with the P1 classification (flagship: 50k charge / 15k
   refund vs 50k ledger -> ``PARTIAL_REFUND_ACCOUNTING_LAG`` MATERIAL), then
   STOP. No investigation, no Groq/LLM, no HITL, no QuickBooks write.
4. Missing ledger reference -> ``LEDGER_RECORD_MISSING`` deterministic state
   (a lookup-level outcome, NOT a P1 reconciler outcome), then STOP.

Canonical-state choice (event-derived projection):

* Option A (adopted conceptually): the canonical processor leg is projected
  from persisted events -- gross/fee from the charge record, refunds
  ACCUMULATED by summing ``refund`` across persisted refund records, net
  derived as ``gross - fee - total_refunds``. The canonical net is NEVER
  taken from the latest payload alone (a single ``refund.created`` payload
  carries only its own increment, not the running total).
* Option B (fixture-backed, accepted as the demo boundary): the test seeds
  the repository from the precomputed ``processor_net_35000`` fixture leg.
  That leg is fixture shorthand for the Option A projection above, and the
  projection helper :func:`project_canonical_processor` proves the
  equivalence (50k gross / 15k accumulated refunds / 35k net).

Commit 3A wiring note (STUB): the ``finance/stripe`` adapter does not exist
yet, so this module wires against the frozen ``PaymentRecord`` interface
directly. :func:`stub_processor_from_stripe_records` stands in for the 3A
adapter output -- it accepts already-normalized charge/refund
``PaymentRecord`` legs (what the 3A adapter will produce) and projects the
canonical leg. It performs no parsing and no I/O.

Only the Python standard library is used, plus the frozen P1 core. This
module imports nothing from ``apps/`` or ``agents/``.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from finance.reconciliation.errors import InvariantViolation
from finance.reconciliation.models import (
    PaymentRecord,
    PaymentStatus,
    ReconciliationOutcome,
    ReconciliationResult,
)
from finance.reconciliation.reconciler import reconcile
from finance.reconciliation.tolerances import ReconciliationTolerance

logger = logging.getLogger(__name__)


class ResolutionStatus(StrEnum):
    """Deterministic terminal state of the Commit 3B lookup+reconcile step.

    ``MATCHED``/``EXCEPTION`` mirror the frozen P1 reconciler verdicts;
    ``LEDGER_RECORD_MISSING`` is a lookup-level state for an absent ledger
    reference (the reconciler is never invoked on a miss).
    """

    MATCHED = "MATCHED"
    EXCEPTION = "EXCEPTION"
    LEDGER_RECORD_MISSING = "LEDGER_RECORD_MISSING"


@dataclass(frozen=True)
class LedgerKey:
    """Exact lookup key for the deterministic ledger repository.

    The triple ``(tenant_id, provider, payment_id)`` is the ONLY match
    criterion: no fuzzy, windowed, or probabilistic matching is performed.
    """

    tenant_id: str
    provider: str
    payment_id: str

    def __post_init__(self) -> None:
        """Strip and require every key component."""
        for field_name in ("tenant_id", "provider", "payment_id"):
            value: object = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise InvariantViolation(f"LedgerKey '{field_name}' must be a non-empty string.")
            object.__setattr__(self, field_name, value.strip())


class LedgerRepository(Protocol):
    """Fixture/repository boundary for deterministic ledger reads."""

    def get(self, key: LedgerKey) -> PaymentRecord | None:
        """Return the ledger leg for ``key``, or ``None`` on a clean miss."""
        ...  # pragma: no cover - protocol surface


class InMemoryLedgerRepository:
    """Deterministic dict-backed ledger seeded from fixtures or records.

    Demo boundary (Option B): tests seed this repository from the
    ``ledger_legs.json`` fixture legs. A production repository would read
    the same ``(tenant_id, provider, payment_id)`` triple from durable
    storage; the lookup contract is identical either way.
    """

    def __init__(self, records: Mapping[LedgerKey, PaymentRecord] | None = None) -> None:
        """Seed the repository with an exact-key mapping (copied, not shared)."""
        self._records: dict[LedgerKey, PaymentRecord] = dict(records) if records else {}

    @classmethod
    def from_records(cls, records: Sequence[PaymentRecord]) -> InMemoryLedgerRepository:
        """Index ``records`` by their own ``(tenant_id, provider, payment_id)``."""
        indexed: dict[LedgerKey, PaymentRecord] = {}
        for record in records:
            if not isinstance(record, PaymentRecord):
                raise InvariantViolation(
                    f"from_records requires PaymentRecord legs, got {type(record).__name__}."
                )
            indexed[
                LedgerKey(
                    tenant_id=record.tenant_id,
                    provider=record.provider,
                    payment_id=record.payment_id,
                )
            ] = record
        return cls(indexed)

    def get(self, key: LedgerKey) -> PaymentRecord | None:
        """Return the leg stored under the exact ``key``, else ``None``."""
        if not isinstance(key, LedgerKey):
            raise InvariantViolation(f"get requires a LedgerKey, got {type(key).__name__}.")
        return self._records.get(key)


def project_canonical_processor(
    charge: PaymentRecord,
    refunds: Sequence[PaymentRecord],
) -> PaymentRecord:
    """Project the canonical processor leg from persisted events (Option A).

    Gross and fee come from the ``charge`` record; refunds ACCUMULATE by
    summing ``refund`` across every persisted refund record; net is derived
    as ``gross - fee - total_refunds``. The net is never copied from any
    single payload: a ``refund.created`` event carries its own increment,
    and out-of-order or repeated deliveries converge because the sum is
    over persisted records, not over delivery order.

    Args:
        charge: The persisted charge leg (gross/fee source of truth).
        refunds: Persisted refund legs against the same payment (may be
            empty for an unrefunded charge).

    Returns:
        The canonical processor ``PaymentRecord`` for reconciliation.

    Raises:
        InvariantViolation: For non-record inputs or legs spanning more
            than one tenant/currency (a projection never mixes scopes).
    """
    if not isinstance(charge, PaymentRecord):
        raise InvariantViolation(f"charge must be a PaymentRecord, got {type(charge).__name__}.")
    refund_list = list(refunds)
    for refund in refund_list:
        if not isinstance(refund, PaymentRecord):
            raise InvariantViolation(
                f"refunds must hold PaymentRecord legs, got {type(refund).__name__}."
            )
        if refund.tenant_id != charge.tenant_id or refund.currency != charge.currency:
            raise InvariantViolation(
                "projection never mixes tenant/currency scopes: "
                f"charge=({charge.tenant_id}, {charge.currency}) vs "
                f"refund=({refund.tenant_id}, {refund.currency})."
            )
    total_refunds = sum((item.refund for item in refund_list), Decimal("0"))
    if refund_list:
        latest = max(refund_list, key=lambda item: item.occurred_at)
        occurred_at = max([charge.occurred_at] + [item.occurred_at for item in refund_list])
        provider_event_id = latest.provider_event_id
        idempotency_key = f"{charge.idempotency_key}+projected"
        status = PaymentStatus.PARTIALLY_REFUNDED
    else:
        occurred_at = charge.occurred_at
        provider_event_id = charge.provider_event_id
        idempotency_key = charge.idempotency_key
        status = charge.status
    canonical = PaymentRecord(
        payment_id=charge.payment_id,
        provider=charge.provider,
        provider_event_id=provider_event_id,
        idempotency_key=idempotency_key,
        gross=charge.gross,
        fee=charge.fee,
        refund=total_refunds,
        net=charge.gross - charge.fee - total_refunds,
        currency=charge.currency,
        status=status,
        occurred_at=occurred_at,
        tenant_id=charge.tenant_id,
        source_reference=charge.source_reference,
    )
    logger.info(
        "Projected canonical processor payment_id=%s gross=%s refunds=%s net=%s",
        canonical.payment_id,
        canonical.gross,
        canonical.refund,
        canonical.net,
    )
    return canonical


def stub_processor_from_stripe_records(
    charge: PaymentRecord,
    refunds: Sequence[PaymentRecord],
) -> PaymentRecord:
    """STUB for the absent Commit 3A Stripe adapter: wire to the projection.

    The 3A adapter will normalize raw Stripe events into ``PaymentRecord``
    legs; until it exists, callers pass those legs directly and this stub
    forwards them to :func:`project_canonical_processor` unchanged. No
    parsing, no network, no database, no currency conversion.
    """
    return project_canonical_processor(charge, refunds)


@dataclass(frozen=True)
class LedgerResolution:
    """Deterministic outcome of the Commit 3B lookup+reconcile step.

    ``status`` is ``LEDGER_RECORD_MISSING`` with ``ledger``/``result`` unset
    on a lookup miss (reconciler never invoked), otherwise it mirrors the
    frozen P1 verdict: ``MATCHED`` carries CLOSED-path data (zero diff, no
    exception code) and ``EXCEPTION`` carries the P1 classification. No
    investigation, HITL, or write side effects are attached -- STOP.
    """

    status: ResolutionStatus
    processor: PaymentRecord
    ledger: PaymentRecord | None
    result: ReconciliationResult | None

    def __post_init__(self) -> None:
        """Enforce miss/verdict coupling on the resolution shape."""
        status_value: object = self.status
        if isinstance(status_value, ResolutionStatus):
            status = status_value
        elif isinstance(status_value, str):
            try:
                status = ResolutionStatus(status_value.strip().upper())
            except ValueError as exc:
                raise InvariantViolation(f"Unknown resolution status {status_value!r}.") from exc
            object.__setattr__(self, "status", status)
        else:
            raise InvariantViolation(
                "Field 'status' must be a ResolutionStatus or status name, "
                f"got {type(status_value).__name__}."
            )
        if not isinstance(self.processor, PaymentRecord):
            raise InvariantViolation(
                f"processor must be a PaymentRecord, got {type(self.processor).__name__}."
            )
        if status is ResolutionStatus.LEDGER_RECORD_MISSING:
            if self.ledger is not None or self.result is not None:
                raise InvariantViolation(
                    "LEDGER_RECORD_MISSING carries no ledger leg and no result."
                )
        elif self.ledger is None or self.result is None:
            raise InvariantViolation(
                f"{status.value} requires both the ledger leg and the P1 result."
            )


def resolve_payment(
    processor: PaymentRecord,
    ledger_key: LedgerKey,
    repository: LedgerRepository,
    tolerance: ReconciliationTolerance,
    *,
    duplicate: bool = False,
) -> LedgerResolution:
    """Look up the ledger leg deterministically, then run frozen P1 reconcile.

    The lookup is an exact ``(tenant_id, provider, payment_id)`` hit: no
    Sheets/QuickBooks access, no probabilistic matching. On a miss, return
    ``LEDGER_RECORD_MISSING`` without invoking the reconciler. On a hit,
    invoke the frozen P1 :func:`reconcile` and mirror its verdict as
    ``MATCHED`` (CLOSED-path data) or ``EXCEPTION`` (P1 classification).
    Then STOP: no investigation, no Groq/LLM, no HITL, no QB-write.

    Args:
        processor: Canonical (event-projected) processor-side leg.
        ledger_key: Exact ledger lookup triple.
        repository: Fixture/repository boundary holding ledger legs.
        tolerance: Tenant-injected tolerance forwarded to P1 unchanged.
        duplicate: Dedup-layer flag forwarded to P1 unchanged.

    Returns:
        The deterministic :class:`LedgerResolution`.
    """
    if not isinstance(processor, PaymentRecord):
        raise InvariantViolation(
            f"processor must be a PaymentRecord, got {type(processor).__name__}."
        )
    if not isinstance(ledger_key, LedgerKey):
        raise InvariantViolation(
            f"ledger_key must be a LedgerKey, got {type(ledger_key).__name__}."
        )
    if not isinstance(tolerance, ReconciliationTolerance):
        raise InvariantViolation(
            f"tolerance must be a ReconciliationTolerance, got {type(tolerance).__name__}."
        )
    if not isinstance(duplicate, bool):
        raise InvariantViolation(f"duplicate must be a bool, got {type(duplicate).__name__}.")
    ledger = repository.get(ledger_key)
    if ledger is None:
        logger.info(
            "Ledger miss tenant=%s provider=%s payment=%s; STOP.",
            ledger_key.tenant_id,
            ledger_key.provider,
            ledger_key.payment_id,
        )
        return LedgerResolution(
            status=ResolutionStatus.LEDGER_RECORD_MISSING,
            processor=processor,
            ledger=None,
            result=None,
        )
    result = reconcile(processor, ledger, tolerance, duplicate=duplicate)
    # P1 close-paths (MATCHED, TOLERANCE_MATCHED) carry no exception code and
    # both resolve to MATCHED here; only a true P1 EXCEPTION becomes EXCEPTION.
    status = (
        ResolutionStatus.EXCEPTION
        if result.outcome is ReconciliationOutcome.EXCEPTION
        else ResolutionStatus.MATCHED
    )
    logger.info(
        "Resolved payment=%s ledger=%s status=%s outcome=%s difference=%s; STOP.",
        processor.payment_id,
        ledger.payment_id,
        status.value,
        result.outcome.value,
        result.difference,
    )
    return LedgerResolution(
        status=status,
        processor=processor,
        ledger=ledger,
        result=result,
    )


__all__ = [
    "InMemoryLedgerRepository",
    "LedgerKey",
    "LedgerRepository",
    "LedgerResolution",
    "ResolutionStatus",
    "project_canonical_processor",
    "resolve_payment",
    "stub_processor_from_stripe_records",
]
