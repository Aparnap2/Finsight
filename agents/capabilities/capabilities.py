"""Read-only deterministic capability implementations (P4.3).

Five closed capabilities, each evidence-only: no financial mutation, no
state transitions, no proposals. Every ``run`` returns a ``ToolResult``
envelope whose ``data`` rows carry ``source``, ``source_record_id``,
``retrieved_at``, and ``content_hash`` per the llm-boundary spec.

Read-path provenance (never live provider SDKs):

* Stripe capabilities fold from persisted :class:`StripePayment` records
  built through ``finance/stripe`` read paths (charge + accumulated
  refunds), never the live Stripe SDK.
* :class:`QBTransactionCapability` reads through
  ``MockQuickBooksAdapter.get_entry`` (read-only; create/void never called).
* :class:`ExpectedStateCapability` looks up the deterministic ledger via
  ``(tenant_id, provider, payment_id)`` exactly as Commit 3B does.
* :class:`GmailSearchCapability` searches a constructor-injected fixture
  corpus (default empty yields a no-result outcome), never real Gmail.

All money serializes as ``str(Decimal)``; datetimes serialize as ISO-8601.
Only the standard library plus ``shared`` and ``finance`` read paths are
used. No Groq/OpenAI imports; no ``apps`` or ``finance/execution`` imports.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from agents.capabilities.types import CapabilityRequest
from finance.accounting.adapter import AccountingAdapter
from finance.accounting.errors import EntryNotFoundError
from finance.reconciliation.ledger_resolution import InMemoryLedgerRepository, LedgerKey
from finance.reconciliation.models import PaymentRecord
from finance.stripe.adapter import RefundRecord, StripePayment
from shared.utils.tools.tool_result import (
    ToolResult,
    compute_degraded_mode,
    compute_quality_score,
    compute_query_fingerprint,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0"
"""Evidence schema version stamped on every ``ToolResult``."""

_MAX_GMAIL_HITS = 10
"""Bound on deterministic Gmail fixture hits per call."""


def _now_iso() -> str:
    """Return the current UTC instant as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


def _content_hash(*parts: str) -> str:
    """Compute a deterministic sha256 hash over ``parts``."""
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def _empty_result(
    capability: str, request: CapabilityRequest, *, degraded: str | None = None
) -> ToolResult:
    """Build a no-result ``ToolResult`` (zero rows, low-coverage degraded)."""
    from shared.models.degraded_mode import DegradedMode

    mode = degraded or DegradedMode.LOW_COVERAGE.value
    return ToolResult(
        data=[],
        row_count=0,
        coverage_pct=0.0,
        quality_score=0.0,
        freshness_seconds=None,
        schema_version=SCHEMA_VERSION,
        source_diversity=1,
        source_type="financial_fact",
        retrieval_scope="factual",
        tenant_id=request.tenant_id,
        required_filters_present=True,
        insufficient_data=True,
        degraded_mode=mode,
        query_fingerprint=compute_query_fingerprint(capability, **dict(request.args)),
    )


def _success_result(
    capability: str,
    request: CapabilityRequest,
    rows: list[dict[str, Any]],
    *,
    coverage: float = 1.0,
) -> ToolResult:
    """Build a success ``ToolResult`` around evidence ``rows``."""
    row_count = len(rows)
    quality = compute_quality_score(coverage, row_count, None)
    degraded = compute_degraded_mode(coverage, row_count)
    return ToolResult(
        data=rows,
        row_count=row_count,
        coverage_pct=coverage,
        quality_score=quality,
        freshness_seconds=None,
        schema_version=SCHEMA_VERSION,
        source_diversity=1,
        source_type="financial_fact",
        retrieval_scope="factual",
        tenant_id=request.tenant_id,
        required_filters_present=True,
        insufficient_data=(coverage < 0.5 or row_count == 0),
        degraded_mode=degraded,
        query_fingerprint=compute_query_fingerprint(capability, **dict(request.args)),
    )


def _payment_record_to_dict(
    record: PaymentRecord, *, source: str, retrieved_at: str
) -> dict[str, Any]:
    """Serialize a ``PaymentRecord`` to an evidence row (Decimal as string)."""
    body = (
        f"{record.tenant_id}|{record.provider}|{record.payment_id}|"
        f"{record.gross}|{record.fee}|{record.refund}|{record.net}"
    )
    return {
        "source": source,
        "source_record_id": record.payment_id,
        "retrieved_at": retrieved_at,
        "content_hash": _content_hash(source, body),
        "payment_id": record.payment_id,
        "provider": record.provider,
        "provider_event_id": record.provider_event_id,
        "gross": str(record.gross),
        "fee": str(record.fee),
        "refund": str(record.refund),
        "net": str(record.net),
        "currency": record.currency,
        "status": record.status.value,
        "occurred_at": record.occurred_at.isoformat(),
        "tenant_id": record.tenant_id,
    }


def _refund_to_dict(refund: RefundRecord, *, retrieved_at: str) -> dict[str, Any]:
    """Serialize a ``RefundRecord`` to an evidence row (Decimal as string)."""
    body = f"{refund.tenant_id}|{refund.payment_id}|{refund.refund_id}|{refund.amount}"
    return {
        "source": "stripe",
        "source_record_id": refund.refund_id,
        "retrieved_at": retrieved_at,
        "content_hash": _content_hash("stripe-refund", body),
        "refund_id": refund.refund_id,
        "payment_id": refund.payment_id,
        "amount": str(refund.amount),
        "currency": refund.currency,
        "tenant_id": refund.tenant_id,
        "provider_event_id": refund.provider_event_id,
        "occurred_at": refund.occurred_at.isoformat(),
    }


class BaseCapability(Protocol):
    """Structural contract every closed capability satisfies."""

    @property
    def name(self) -> str:
        """Closed capability name (frozen allowlist member)."""
        ...

    @property
    def required_args(self) -> tuple[str, ...]:
        """Arg keys the capability reads (missing keys yield no-result)."""
        ...

    def run(self, request: CapabilityRequest) -> ToolResult:
        """Execute a read-only lookup; evidence only, never a mutation."""
        ...


class StripePaymentCapability:
    """Read a persisted Stripe payment fold (charge + accumulated refunds)."""

    def __init__(self, payments: Mapping[tuple[str, str], StripePayment] | None = None) -> None:
        """Seed from persisted folds keyed by ``(tenant_id, payment_id)``."""
        self._payments: dict[tuple[str, str], StripePayment] = dict(payments or {})

    @property
    def name(self) -> str:
        """Return the closed capability name."""
        return "get_stripe_payment"

    @property
    def required_args(self) -> tuple[str, ...]:
        """Return the args this capability reads."""
        return ("payment_id",)

    def run(self, request: CapabilityRequest) -> ToolResult:
        """Return the canonical payment record for ``payment_id`` (or empty)."""
        payment_id = request.args.get("payment_id", "").strip()
        if not payment_id:
            return _empty_result(self.name, request)
        payment = self._payments.get((request.tenant_id, payment_id))
        if payment is None:
            logger.info("stripe payment miss tenant=%s payment=%s", request.tenant_id, payment_id)
            return _empty_result(self.name, request)
        retrieved_at = _now_iso()
        record = payment.to_record()
        row = _payment_record_to_dict(record, source="stripe", retrieved_at=retrieved_at)
        row["fee_state"] = payment.fee.state.value
        logger.info("stripe payment hit tenant=%s payment=%s", request.tenant_id, payment_id)
        return _success_result(self.name, request, [row])


class StripeRefundsCapability:
    """Read persisted refund deltas for one Stripe payment fold."""

    def __init__(self, payments: Mapping[tuple[str, str], StripePayment] | None = None) -> None:
        """Seed from persisted folds keyed by ``(tenant_id, payment_id)``."""
        self._payments: dict[tuple[str, str], StripePayment] = dict(payments or {})

    @property
    def name(self) -> str:
        """Return the closed capability name."""
        return "get_stripe_refunds"

    @property
    def required_args(self) -> tuple[str, ...]:
        """Return the args this capability reads."""
        return ("payment_id",)

    def run(self, request: CapabilityRequest) -> ToolResult:
        """Return one row per persisted refund delta (or empty when none)."""
        payment_id = request.args.get("payment_id", "").strip()
        if not payment_id:
            return _empty_result(self.name, request)
        payment = self._payments.get((request.tenant_id, payment_id))
        if payment is None or not payment.refunds:
            return _empty_result(self.name, request)
        retrieved_at = _now_iso()
        ordered = sorted(payment.refunds, key=lambda item: item.refund_id)
        rows = [_refund_to_dict(item, retrieved_at=retrieved_at) for item in ordered]
        return _success_result(self.name, request, rows)


class QBTransactionCapability:
    """Read-only QuickBooks entry lookup via ``get_entry`` (never write)."""

    def __init__(self, adapter: AccountingAdapter) -> None:
        """Bind a sandbox adapter; only ``get_entry`` is ever called."""
        self._adapter = adapter

    @property
    def name(self) -> str:
        """Return the closed capability name."""
        return "get_qb_transaction"

    @property
    def required_args(self) -> tuple[str, ...]:
        """Return the args this capability reads."""
        return ("entry_id",)

    def run(self, request: CapabilityRequest) -> ToolResult:
        """Return the sandbox entry for ``entry_id`` tenant-scoped (or empty).

        Raises:
            EntryNotFoundError: On a read miss (converted by the executor).
            TransientError: On a scripted 5xx (converted by the executor).
        """
        entry_id = request.args.get("entry_id", "").strip()
        if not entry_id:
            return _empty_result(self.name, request)
        entry = self._adapter.get_entry(entry_id)
        if entry.tenant_id != request.tenant_id:
            logger.info("qb entry tenant mismatch entry=%s", entry_id)
            raise EntryNotFoundError(f"Entry {entry_id!r} is outside the tenant scope.")
        retrieved_at = _now_iso()
        body = f"{entry.tenant_id}|{entry.entry_id}|{entry.total}|{entry.status.value}"
        row: dict[str, Any] = {
            "source": "quickbooks",
            "source_record_id": entry.entry_id,
            "retrieved_at": retrieved_at,
            "content_hash": _content_hash("quickbooks", body),
            "entry_id": entry.entry_id,
            "tenant_id": entry.tenant_id,
            "exception_id": entry.exception_id,
            "exception_type": entry.exception_type,
            "status": entry.status.value,
            "currency": entry.currency,
            "total": str(entry.total),
            "source_reference": entry.source_reference,
            "memo": entry.memo,
            "lines": [
                {
                    "account": line.account,
                    "debit": str(line.debit),
                    "credit": str(line.credit),
                }
                for line in entry.lines
            ],
        }
        return _success_result(self.name, request, [row])


class ExpectedStateCapability:
    """Deterministic ledger lookup keyed by ``(tenant, provider, payment)``."""

    def __init__(self, repository: InMemoryLedgerRepository) -> None:
        """Bind the fixture/repository boundary used exactly as Commit 3B does."""
        self._repository = repository

    @property
    def name(self) -> str:
        """Return the closed capability name."""
        return "get_expected_state"

    @property
    def required_args(self) -> tuple[str, ...]:
        """Return the args this capability reads."""
        return ("payment_id", "provider")

    def run(self, request: CapabilityRequest) -> ToolResult:
        """Return the ledger leg for the exact triple (or empty on miss)."""
        payment_id = request.args.get("payment_id", "").strip()
        if not payment_id:
            return _empty_result(self.name, request)
        provider = request.args.get("provider", "stripe").strip() or "stripe"
        key = LedgerKey(tenant_id=request.tenant_id, provider=provider, payment_id=payment_id)
        leg = self._repository.get(key)
        if leg is None:
            logger.info("ledger miss tenant=%s payment=%s", request.tenant_id, payment_id)
            return _empty_result(self.name, request)
        retrieved_at = _now_iso()
        row = _payment_record_to_dict(leg, source="ledger", retrieved_at=retrieved_at)
        return _success_result(self.name, request, [row])


class GmailSearchCapability:
    """Deterministic fixture-backed message search (never real Gmail)."""

    def __init__(self, corpus: Mapping[str, Sequence[Mapping[str, Any]]] | None = None) -> None:
        """Seed a per-tenant fixture corpus (copied; default empty).

        Args:
            corpus: Tenant id to message mappings. Each message is a plain
                mapping with at least ``message_id``, ``subject``, and
                ``body`` string fields.
        """
        copied: dict[str, list[dict[str, Any]]] = {}
        for tenant, messages in dict(corpus or {}).items():
            copied[tenant] = [dict(message) for message in messages]
        self._corpus = copied

    @property
    def name(self) -> str:
        """Return the closed capability name."""
        return "search_gmail"

    @property
    def required_args(self) -> tuple[str, ...]:
        """Return the args this capability reads."""
        return ("query",)

    def run(self, request: CapabilityRequest) -> ToolResult:
        """Substring-search fixture messages tenant-scoped (or empty)."""
        query = request.args.get("query", "").strip().lower()
        if not query:
            return _empty_result(self.name, request)
        messages = self._corpus.get(request.tenant_id, [])
        hits: list[dict[str, Any]] = []
        for message in messages:
            subject = str(message.get("subject", ""))
            body = str(message.get("body", ""))
            if query in subject.lower() or query in body.lower():
                message_id = str(message.get("message_id", ""))
                retrieved_at = _now_iso()
                content = f"{subject}\n{body}"
                hits.append(
                    {
                        "source": "gmail",
                        "source_record_id": message_id or _content_hash(content)[:16],
                        "retrieved_at": retrieved_at,
                        "content_hash": _content_hash("gmail", content),
                        "message_id": message_id,
                        "subject": subject,
                        "snippet": body[:280],
                        "tenant_id": request.tenant_id,
                    }
                )
                if len(hits) >= _MAX_GMAIL_HITS:
                    break
        if not hits:
            return _empty_result(self.name, request)
        return _success_result(self.name, request, hits)


@dataclass(frozen=True)
class AdapterBundle:
    """Constructor-injected read-only stores for the deterministic executor."""

    stripe_payments: Mapping[tuple[str, str], StripePayment] = field(default_factory=dict)
    qb_adapter: AccountingAdapter | None = None
    ledger_repository: InMemoryLedgerRepository | None = None
    gmail_corpus: Mapping[str, Sequence[Mapping[str, Any]]] = field(default_factory=dict)


__all__ = [
    "SCHEMA_VERSION",
    "AdapterBundle",
    "BaseCapability",
    "ExpectedStateCapability",
    "GmailSearchCapability",
    "QBTransactionCapability",
    "StripePaymentCapability",
    "StripeRefundsCapability",
]
