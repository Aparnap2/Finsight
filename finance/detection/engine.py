"""Deterministic P6-03 detection engine: facts in, verdict out.

``detect()`` answers the business question "what financial situation
actually exists" without any LLM involvement: provenance gate first,
currency agreement second, same-id conflict third, then the two
variance equations (actionable books-minus-provider-net, informational
expected-minus-books), with pairwise legs delegated to the frozen P1
``reconcile()`` for materiality and the catalog rules for labels.

Money is ``Decimal``-only; every model is frozen strict Pydantic; the
same inputs always yield the identical verdict (fingerprint-stable).
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from hashlib import sha256

from pydantic import BaseModel, ConfigDict

from finance.business_rules.meridian import CompanyConfiguration
from finance.detection.classification import (
    DetectionClassification,
    map_p1_code,
)
from finance.domain._types import MoneyDecimal
from finance.facts.books import BooksFact
from finance.facts.expected import ExpectedFact
from finance.facts.legacy import LegacyFact
from finance.facts.provider import ProviderNetFact
from finance.reconciliation.errors import CurrencyMismatch
from finance.reconciliation.models import ExceptionCode, PaymentRecord, PaymentStatus
from finance.reconciliation.reconciler import reconcile
from finance.reconciliation.tolerances import ReconciliationTolerance


class DetectionOutcome(StrEnum):
    """Machine outcome of one deterministic detection pass."""

    MATCHED = "MATCHED"
    """Zero variance with full coverage; creates nothing."""

    WITHIN_TOLERANCE = "WITHIN_TOLERANCE"
    """Residual inside tolerance; creates nothing."""

    EXCEPTION = "EXCEPTION"
    """Material break; may create a FinancialSituation."""

    PENDING_EVIDENCE = "PENDING_EVIDENCE"
    """Coverage incomplete; unknown data never promotes to a case."""

    CONFLICTING_AUTHORITIES = "CONFLICTING_AUTHORITIES"
    """Same id, different bodies; investigate only, never overwrite."""


class DetectionVerdict(BaseModel):
    """Immutable result of one deterministic detection pass."""

    model_config = ConfigDict(frozen=True, strict=True)

    verdict: DetectionOutcome
    """Machine outcome (drives creation routing, never agent reasoning)."""

    actionable_variance: MoneyDecimal
    """Books total minus provider net — the only actionable number."""

    expected_books_gap: MoneyDecimal
    """Expected total minus books total — informational, timing-separated."""

    classification: DetectionClassification
    """Catalog label from the deterministic rules."""

    situation_id: str | None = None
    """Always None from detect(); creation_rules() allocates."""

    fingerprint: str
    """sha256 over the input fact hashes; redelivery-stable."""


def _provider_name(provenance_endpoint: str) -> str:
    """Derive a deterministic leg label from a contract endpoint id."""
    tag = provenance_endpoint.strip().upper()
    if tag.startswith("C-") and len(tag) > 2:
        return tag[2:].lower()
    return "unknown"


def _processor_leg(provider: ProviderNetFact) -> PaymentRecord:
    """Fold a provider fact into the frozen P1 processor leg."""
    return PaymentRecord(
        payment_id=provider.fact_id,
        provider=_provider_name(provider.provenance.endpoint),
        provider_event_id=provider.fact_id,
        idempotency_key=f"{provider.batch_id}:{provider.fact_id}",
        gross=provider.gross,
        fee=provider.fee,
        refund=provider.refund,
        net=provider.net,
        currency=provider.currency,
        status=PaymentStatus.SETTLED,
        occurred_at=provider.observed_at,
        tenant_id="meridian",
    )


def _ledger_leg(books: BooksFact) -> PaymentRecord:
    """Fold a books fact into the frozen P1 observed leg (net-only)."""
    return PaymentRecord(
        payment_id=books.fact_id,
        provider="quickbooks",
        provider_event_id=books.fact_id,
        idempotency_key=f"{books.batch_id}:{books.fact_id}",
        gross=books.qb_total,
        fee=Decimal("0"),
        refund=Decimal("0"),
        net=books.qb_total,
        currency=books.currency,
        status=PaymentStatus.SETTLED,
        occurred_at=books.posted_at,
        tenant_id="meridian",
    )


def _fingerprint(parts: list[str]) -> str:
    """Return the sha256 hex over canonical input parts."""
    return sha256("|".join(parts).encode("utf-8")).hexdigest()


def detect(
    *,
    expected: ExpectedFact | None,
    provider: ProviderNetFact | None,
    books: BooksFact | None,
    legacy: LegacyFact | None,
    tolerance: Decimal | None = None,
) -> DetectionVerdict:
    """Run one deterministic detection pass over canonical facts.

    Order: currency agreement (raise) → missing legs (pending) →
    same-id conflict → legacy-structural → frozen pairwise materiality
    → catalog classification. The actionable variance is always books
    minus provider net; expected-minus-provider is never actionable.

    Args:
        expected: Sheets expected-settlement fact (None when absent).
        provider: Provider-net decomposition fact (None when absent).
        books: Books-total fact (None when absent).
        legacy: Legacy posting fact (None means no legacy leg seen).
        tolerance: Absolute materiality bound; defaults to the
            company-configured minor tolerance (100 INR).

    Returns:
        A frozen verdict with ``situation_id`` always None (creation
        allocates). Deterministic: identical inputs yield equal
        verdicts, including the fingerprint.

    Raises:
        CurrencyMismatch: Facts disagree on currency (never coerced).
    """
    bound = tolerance if tolerance is not None else CompanyConfiguration().tolerance_minor
    present = [fact for fact in (expected, provider, books, legacy) if fact is not None]
    currencies = {fact.currency for fact in present}
    if len(currencies) > 1:
        ordered = sorted(currencies)
        raise CurrencyMismatch(ordered[0], ordered[1], "detect")
    if expected is None or provider is None or books is None:
        return DetectionVerdict(
            verdict=DetectionOutcome.PENDING_EVIDENCE,
            actionable_variance=(
                books.qb_total - provider.net
                if provider is not None and books is not None
                else Decimal("0")
            ),
            expected_books_gap=Decimal("0"),
            classification=DetectionClassification.INSUFFICIENT_EVIDENCE,
            situation_id=None,
            fingerprint=_fingerprint(
                [
                    *(f.provenance.content_hash for f in present),
                    "absent-leg",
                    str(bound),
                ]
            ),
        )
    seen: dict[str, str] = {}
    for fact in present:
        prior = seen.get(fact.fact_id)
        if prior is not None and prior != fact.provenance.content_hash:
            return DetectionVerdict(
                verdict=DetectionOutcome.CONFLICTING_AUTHORITIES,
                actionable_variance=books.qb_total - provider.net,
                expected_books_gap=expected.expected_total - books.qb_total,
                classification=DetectionClassification.CONFLICTING_AUTHORITIES,
                situation_id=None,
                fingerprint=_fingerprint(
                    [*(f.provenance.content_hash for f in present), "conflict"]
                ),
            )
        seen[fact.fact_id] = fact.provenance.content_hash
    actionable = books.qb_total - provider.net
    gap = expected.expected_total - books.qb_total
    stamp = _fingerprint(
        [*(f.provenance.content_hash for f in present), str(bound)]
    )
    if legacy is None or legacy.rejected_total != 0 or legacy.rejected_reason:
        return DetectionVerdict(
            verdict=DetectionOutcome.EXCEPTION,
            actionable_variance=actionable,
            expected_books_gap=gap,
            classification=DetectionClassification.LEGACY_POSTING_MISSING,
            situation_id=None,
            fingerprint=stamp,
        )
    pair = reconcile(
        _processor_leg(provider),
        _ledger_leg(books),
        ReconciliationTolerance(absolute=bound),
        duplicate=books.duplicate_key is not None,
    )
    if pair.outcome.value == "MATCHED":
        return DetectionVerdict(
            verdict=DetectionOutcome.MATCHED,
            actionable_variance=actionable,
            expected_books_gap=gap,
            classification=DetectionClassification.MATCHED,
            situation_id=None,
            fingerprint=stamp,
        )
    if pair.outcome.value == "TOLERANCE_MATCHED":
        return DetectionVerdict(
            verdict=DetectionOutcome.WITHIN_TOLERANCE,
            actionable_variance=actionable,
            expected_books_gap=gap,
            classification=DetectionClassification.WITHIN_TOLERANCE,
            situation_id=None,
            fingerprint=stamp,
        )
    if books.duplicate_key is not None:
        label = DetectionClassification.DUPLICATE_LEDGER_ENTRY
    elif (
        books.booked_fee is not None
        and books.booked_fee != provider.fee
        and abs(books.booked_fee - provider.fee) == abs(actionable)
    ):
        label = DetectionClassification.FEE_MISMATCH
    elif provider.refund != 0 and actionable == provider.refund:
        label = DetectionClassification.PARTIAL_REFUND_LAG
    elif pair.exception_code is not None:
        label = map_p1_code(ExceptionCode(pair.exception_code))
    else:  # pragma: no cover - P1 guarantees a code on EXCEPTION
        label = DetectionClassification.PARTIAL_REFUND_LAG
    return DetectionVerdict(
        verdict=DetectionOutcome.EXCEPTION,
        actionable_variance=actionable,
        expected_books_gap=gap,
        classification=label,
        situation_id=None,
        fingerprint=stamp,
    )
