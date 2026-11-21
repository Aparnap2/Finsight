"""Three-source statement reconciliation: invoice register, processor, bank.

The frozen primitives in this package each answer one question: ``reconcile``
compares two legs, ``classify`` explains a pair, ``normalize_bank_statement``
turns statement rows into deposit evidence, and ``reconcile_payout`` allocates
one deposit to its charges. This module composes them into the triangle:
invoice -> charge -> deposit, plus the derived invoice -> deposit comparison.

Composition rules, all deterministic and side-effect free:

* Invoices and charges are linked one-to-one by exact ``(currency, gross)``
  within the tenant. Ties break by closest ``occurred_at`` then ``payment_id``.
  Nothing is fuzzy, transitive, or invented.
* The bank statement is normalized under a caller-declared mapping. Exact
  row duplicates are reported, never allocated twice.
* A deposit whose identifier is reused with a drifted amount is duplicate
  evidence: the latest record for that statement line is reconciled with
  ``duplicate=True`` so the core reports ``I-DUPLICATE`` and keeps the amount
  discrepancy visible in ``open_balance`` / ``unallocated_deposit``.
* The invoice -> deposit comparison is derived from the two edges that were
  actually reconciled. It is reported beside the edge results and never
  overwrites them.

No clock, randomness, network, or float money is used. Every report is
fingerprinted from its canonical JSON form.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from finance.reconciliation.allocation import Allocation, reconcile_payout
from finance.reconciliation.bank import (
    BankDepositRecord,
    BankIngestResult,
    BankStatementMapping,
    normalize_bank_statement,
)
from finance.reconciliation.errors import (
    CurrencyMismatch,
    InvariantViolation,
    TenantIsolationError,
)
from finance.reconciliation.models import (
    PaymentRecord,
    PaymentStatus,
    PayoutOutcome,
    ReconciliationResult,
)
from finance.reconciliation.reconciler import reconcile
from finance.reconciliation.tolerances import ReconciliationTolerance

_EDGE_INVOICE_CHARGE = "invoice_to_charge"
_EDGE_CHARGE_DEPOSIT = "charge_to_deposit"
_EDGE_INVOICE_DEPOSIT = "invoice_to_deposit"


@dataclass(frozen=True)
class StatementSources:
    """The three evidence sources for one tenant and one currency.

    ``invoices`` and ``charges`` are normalized ``PaymentRecord`` legs: the
    invoice register export and the processor events, respectively. ``bank_rows``
    are already-parsed statement cells (the CSV header row is not included).
    """

    tenant_id: str
    currency: str
    invoices: Sequence[PaymentRecord]
    charges: Sequence[PaymentRecord]
    bank_rows: Sequence[Mapping[str, Any]]
    mapping: BankStatementMapping
    statement_digest: str
    tolerance: ReconciliationTolerance
    window_seconds: int | None = None

    def __post_init__(self) -> None:
        """Validate the envelope shape without touching the frozen core."""
        for field_name in ("tenant_id", "currency", "statement_digest"):
            value: object = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise InvariantViolation(f"{field_name} must be a non-empty string.")
        for field_name in ("invoices", "charges", "bank_rows"):
            value = getattr(self, field_name)
            if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
                raise InvariantViolation(f"{field_name} must be a sequence.")
        if not isinstance(self.mapping, BankStatementMapping):
            raise InvariantViolation("mapping must be a BankStatementMapping.")
        if not isinstance(self.tolerance, ReconciliationTolerance):
            raise InvariantViolation("tolerance must be a ReconciliationTolerance.")
        if self.window_seconds is not None:
            if isinstance(self.window_seconds, bool) or not isinstance(self.window_seconds, int):
                raise InvariantViolation("window_seconds must be an int or None.")
            if self.window_seconds < 0:
                raise InvariantViolation("window_seconds must be non-negative.")


@dataclass(frozen=True)
class InvoiceChargeLink:
    """One invoice and the charge that is expected to settle it."""

    invoice_id: str
    charge_id: str
    invoice_net: Decimal
    charge_net: Decimal
    result: ReconciliationResult

    @property
    def difference(self) -> Decimal:
        """Return ``charge_net - invoice_net`` in exact Decimal arithmetic."""
        return self.charge_net - self.invoice_net


@dataclass(frozen=True)
class DerivedComparison:
    """Invoice -> deposit comparison composed from two reconciled edges.

    ``difference`` is ``deposit_amount - invoice_net_total``. The comparison is
    label-derived: it is only meaningful because the invoice -> charge and
    charge -> deposit edges were each reconciled on their own evidence.
    """

    deposit_id: str
    invoice_ids: tuple[str, ...]
    invoice_net_total: Decimal
    deposit_amount: Decimal
    difference: Decimal

    def __post_init__(self) -> None:
        """Enforce the derived comparison equation and a sorted id set."""
        if self.difference != self.deposit_amount - self.invoice_net_total:
            raise InvariantViolation(
                "Derived difference must equal deposit_amount - invoice_net_total."
            )
        if tuple(sorted(self.invoice_ids)) != self.invoice_ids:
            raise InvariantViolation("invoice_ids must be sorted for determinism.")


@dataclass(frozen=True)
class DepositEvidence:
    """Statement-line provenance for one deduplicated deposit record."""

    deposit_id: str
    statement_reference: str
    line_number: int
    amount: Decimal


@dataclass(frozen=True)
class DepositResult:
    """One deposit's allocation, its derived comparison, and its provenance."""

    deposit_id: str
    allocation: Allocation
    duplicate: bool
    evidence: tuple[DepositEvidence, ...]
    comparison: DerivedComparison | None


@dataclass(frozen=True)
class ReconciliationReport:
    """Deterministic, serializable result of one three-source run."""

    tenant_id: str
    currency: str
    statement_digest: str
    mapping_digest: str
    exponent: int
    links: tuple[InvoiceChargeLink, ...]
    unlinked_invoices: tuple[str, ...]
    unlinked_charges: tuple[str, ...]
    deposits: tuple[DepositResult, ...]
    duplicate_groups: tuple[tuple[DepositEvidence, ...], ...]
    drift_groups: tuple[tuple[DepositEvidence, ...], ...]
    rejects: tuple[tuple[int, str, str], ...]
    skipped_debits: int
    warnings: tuple[str, ...]
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        """Render the report as a JSON-safe dict with deterministic ordering."""
        exp = self.exponent

        def _money(value: Decimal) -> str:
            return _render_money(value, exp)

        return {
            "tenant_id": self.tenant_id,
            "currency": self.currency,
            "statement_digest": self.statement_digest,
            "mapping_digest": self.mapping_digest,
            "edges": {
                _EDGE_INVOICE_CHARGE: {
                    "links": [
                        {
                            "invoice_id": link.invoice_id,
                            "charge_id": link.charge_id,
                            "invoice_net": _money(link.invoice_net),
                            "charge_net": _money(link.charge_net),
                            "difference": _money(link.difference),
                            "outcome": link.result.outcome.value,
                            "exception_code": link.result.exception_code,
                            "materiality": link.result.materiality.value,
                            "fingerprint": link.result.fingerprint,
                        }
                        for link in self.links
                    ],
                    "unlinked_invoices": list(self.unlinked_invoices),
                    "unlinked_charges": list(self.unlinked_charges),
                },
                _EDGE_CHARGE_DEPOSIT: {
                    "results": [
                        {
                            "deposit_id": deposit.deposit_id,
                            "duplicate": deposit.duplicate,
                            "outcome": deposit.allocation.outcome.value,
                            "reason": (
                                deposit.allocation.reason.value
                                if deposit.allocation.reason is not None
                                else None
                            ),
                            "exception_code": (
                                deposit.allocation.exception_code.value
                                if deposit.allocation.exception_code is not None
                                else None
                            ),
                            "eligible_net_total": _money(deposit.allocation.eligible_net_total),
                            "allocated_total": _money(deposit.allocation.allocated_total),
                            "open_balance": _money(deposit.allocation.open_balance),
                            "unallocated_deposit": _money(deposit.allocation.unallocated_deposit),
                            "fee_total": _money(deposit.allocation.fee_total),
                            "refund_total": _money(deposit.allocation.refund_total),
                            "legs": [
                                {
                                    "payment_id": leg.payment_id,
                                    "gross": _money(leg.gross),
                                    "fee": _money(leg.fee),
                                    "refund": _money(leg.refund),
                                    "net": _money(leg.net),
                                    "allocated": _money(leg.allocated),
                                }
                                for leg in deposit.allocation.legs
                            ],
                            "candidates": [
                                {
                                    "payment_ids": list(candidate.payment_ids),
                                    "total": _money(candidate.total),
                                }
                                for candidate in deposit.allocation.candidates
                            ],
                            "evidence": [
                                {
                                    "deposit_id": item.deposit_id,
                                    "statement_reference": item.statement_reference,
                                    "line_number": item.line_number,
                                    "amount": _money(item.amount),
                                }
                                for item in deposit.evidence
                            ],
                            "fingerprint": deposit.allocation.fingerprint,
                        }
                        for deposit in self.deposits
                    ]
                },
                _EDGE_INVOICE_DEPOSIT: {
                    "derived": True,
                    "note": (
                        "Composed from invoice_to_charge and charge_to_deposit; "
                        "never a direct comparison and never an overwrite."
                    ),
                    "comparisons": [
                        {
                            "deposit_id": deposit.comparison.deposit_id,
                            "invoice_ids": list(deposit.comparison.invoice_ids),
                            "invoice_net_total": _money(deposit.comparison.invoice_net_total),
                            "deposit_amount": _money(deposit.comparison.deposit_amount),
                            "difference": _money(deposit.comparison.difference),
                            "derived_from": [_EDGE_INVOICE_CHARGE, _EDGE_CHARGE_DEPOSIT],
                        }
                        for deposit in self.deposits
                        if deposit.comparison is not None
                    ],
                },
            },
            "duplicate_groups": [
                [
                    {
                        "deposit_id": item.deposit_id,
                        "statement_reference": item.statement_reference,
                        "line_number": item.line_number,
                        "amount": _money(item.amount),
                    }
                    for item in group
                ]
                for group in self.duplicate_groups
            ],
            "drift_groups": [
                [
                    {
                        "deposit_id": item.deposit_id,
                        "statement_reference": item.statement_reference,
                        "line_number": item.line_number,
                        "amount": _money(item.amount),
                    }
                    for item in group
                ]
                for group in self.drift_groups
            ],
            "rejects": [
                {"line_number": line, "reason": reason, "detail": detail}
                for line, reason, detail in self.rejects
            ],
            "skipped_debits": self.skipped_debits,
            "warnings": list(self.warnings),
            "fingerprint": self.fingerprint,
        }


def run_statement_reconciliation(sources: StatementSources) -> ReconciliationReport:
    """Reconcile one tenant's three sources and return a frozen report.

    Args:
        sources: Invoice register, processor charges, and bank statement rows.

    Returns:
        A ``ReconciliationReport`` covering every edge plus any unresolved
        evidence. The report is deterministic for equal inputs.

    Raises:
        TenantIsolationError: If a payment leg belongs to another tenant.
        CurrencyMismatch: If a leg or the mapping uses another currency.
        InvariantViolation: For malformed source or mapping input.
    """
    tenant = sources.tenant_id.strip()
    currency = sources.currency.strip().upper()
    if sources.mapping.statement_currency != currency:
        raise CurrencyMismatch(currency, sources.mapping.statement_currency, "statement")

    exponent = sources.mapping.exponent()
    invoices = _checked_legs(sources.invoices, tenant, currency, "invoices")
    charges = _checked_legs(sources.charges, tenant, currency, "charges")

    ingest = normalize_bank_statement(
        sources.bank_rows,
        sources.mapping,
        tenant_id=tenant,
        statement_digest=sources.statement_digest,
    )
    chronology = _ingest_chronology(ingest)

    links, unlinked_invoices, unlinked_charges = _link_invoices(
        invoices, charges, sources.tolerance
    )
    linked_by_charge = {link.charge_id: link.invoice_id for link in links}
    invoice_net = {invoice.payment_id: invoice.net for invoice in invoices}

    deposits, duplicate_groups, drift_groups = _reconcile_deposits(
        ingest,
        charges,
        sources.tolerance,
        sources.window_seconds,
        linked_by_charge,
        invoice_net,
    )

    warnings = _warnings(
        invoices,
        charges,
        ingest,
        deposits,
        duplicate_groups,
        drift_groups,
        unlinked_invoices,
        unlinked_charges,
        exponent,
    )
    rejects = tuple(
        (reject.line_number, reject.reason.value, reject.detail) for reject in ingest.rejects
    )
    payload: dict[str, Any] = {
        "tenant_id": tenant,
        "currency": currency,
        "statement_digest": sources.statement_digest,
        "mapping_digest": ingest.mapping_digest,
        "links": tuple(
            {
                "invoice_id": link.invoice_id,
                "charge_id": link.charge_id,
                "invoice_net": _render_money(link.invoice_net, exponent),
                "charge_net": _render_money(link.charge_net, exponent),
                "difference": _render_money(link.difference, exponent),
                "outcome": link.result.outcome.value,
                "exception_code": link.result.exception_code,
                "materiality": link.result.materiality.value,
                "fingerprint": link.result.fingerprint,
            }
            for link in links
        ),
        "unlinked_invoices": unlinked_invoices,
        "unlinked_charges": unlinked_charges,
        "deposits": tuple(
            {
                "deposit_id": deposit.deposit_id,
                "duplicate": deposit.duplicate,
                "allocation": deposit.allocation.fingerprint,
                "evidence": tuple(
                    (
                        item.statement_reference,
                        item.line_number,
                        _render_money(item.amount, exponent),
                    )
                    for item in deposit.evidence
                ),
                "comparison": (
                    None
                    if deposit.comparison is None
                    else (
                        deposit.comparison.invoice_ids,
                        _render_money(deposit.comparison.invoice_net_total, exponent),
                        _render_money(deposit.comparison.deposit_amount, exponent),
                        _render_money(deposit.comparison.difference, exponent),
                    )
                ),
            }
            for deposit in deposits
        ),
        "duplicate_groups": tuple(
            tuple(item.statement_reference for item in group) for group in duplicate_groups
        ),
        "drift_groups": tuple(
            tuple(item.statement_reference for item in group) for group in drift_groups
        ),
        "rejects": rejects,
        "skipped_debits": ingest.skipped_debits,
        "warnings": warnings,
        "chronology": chronology,
    }
    fingerprint = _fingerprint(payload)
    return ReconciliationReport(
        tenant_id=tenant,
        currency=currency,
        statement_digest=sources.statement_digest,
        mapping_digest=ingest.mapping_digest,
        exponent=exponent,
        links=links,
        unlinked_invoices=unlinked_invoices,
        unlinked_charges=unlinked_charges,
        deposits=deposits,
        duplicate_groups=duplicate_groups,
        drift_groups=drift_groups,
        rejects=rejects,
        skipped_debits=ingest.skipped_debits,
        warnings=warnings,
        fingerprint=fingerprint,
    )


def _checked_legs(
    legs: Sequence[PaymentRecord],
    tenant_id: str,
    currency: str,
    label: str,
) -> tuple[PaymentRecord, ...]:
    for index, leg in enumerate(legs):
        if not isinstance(leg, PaymentRecord):
            raise InvariantViolation(f"{label}[{index}] must be a PaymentRecord.")
        if leg.tenant_id != tenant_id:
            raise TenantIsolationError(
                f"{label}[{index}] belongs to {leg.tenant_id!r}, expected {tenant_id!r}."
            )
        if leg.currency != currency:
            raise CurrencyMismatch(currency, leg.currency, label)
    return tuple(legs)


def _link_invoices(
    invoices: Sequence[PaymentRecord],
    charges: Sequence[PaymentRecord],
    tolerance: ReconciliationTolerance,
) -> tuple[tuple[InvoiceChargeLink, ...], tuple[str, ...], tuple[str, ...]]:
    buckets: dict[tuple[str, Decimal], list[PaymentRecord]] = {}
    for charge in charges:
        buckets.setdefault((charge.currency, charge.gross), []).append(charge)
    for same_gross in buckets.values():
        same_gross.sort(key=lambda charge: (charge.occurred_at, charge.payment_id))

    consumed: set[str] = set()
    links: list[InvoiceChargeLink] = []
    unlinked: list[str] = []
    for invoice in sorted(invoices, key=lambda leg: (leg.occurred_at, leg.payment_id)):
        candidates = buckets.get((invoice.currency, invoice.gross))
        if not candidates:
            unlinked.append(invoice.payment_id)
            continue
        chosen = min(
            candidates,
            key=lambda charge: (
                abs((charge.occurred_at - invoice.occurred_at).total_seconds()),
                charge.payment_id,
            ),
        )
        candidates.remove(chosen)
        consumed.add(chosen.payment_id)
        links.append(
            InvoiceChargeLink(
                invoice_id=invoice.payment_id,
                charge_id=chosen.payment_id,
                invoice_net=invoice.net,
                charge_net=chosen.net,
                result=reconcile(invoice, chosen, tolerance),
            )
        )
    unlinked_charges = tuple(
        sorted(charge.payment_id for charge in charges if charge.payment_id not in consumed)
    )
    return tuple(links), tuple(sorted(unlinked)), unlinked_charges


def _ingest_chronology(ingest: BankIngestResult) -> tuple[tuple[str, int], ...]:
    """Return every ingested deposit, including deduplicated copies, in line order."""
    entries: list[BankDepositRecord] = list(ingest.deposits)
    for group in ingest.duplicates:
        entries.extend(group)
    entries.sort(key=lambda record: record.line_number)
    return tuple((record.deposit_id, record.line_number) for record in entries)


def _evidence(record: BankDepositRecord) -> DepositEvidence:
    return DepositEvidence(
        deposit_id=record.deposit_id,
        statement_reference=record.source_reference,
        line_number=record.line_number,
        amount=record.amount,
    )


def _reconcile_deposits(
    ingest: BankIngestResult,
    charges: Sequence[PaymentRecord],
    tolerance: ReconciliationTolerance,
    window_seconds: int | None,
    linked_by_charge: Mapping[str, str],
    invoice_net: Mapping[str, Decimal],
) -> tuple[
    tuple[DepositResult, ...],
    tuple[tuple[DepositEvidence, ...], ...],
    tuple[tuple[DepositEvidence, ...], ...],
]:
    duplicates = tuple(tuple(_evidence(record) for record in group) for group in ingest.duplicates)

    by_line: dict[str, list[BankDepositRecord]] = {}
    for record in ingest.deposits:
        by_line.setdefault(record.deposit_id, []).append(record)

    drift: list[tuple[DepositEvidence, ...]] = []
    results: list[DepositResult] = []
    for deposit_id in sorted(by_line):
        records = sorted(by_line[deposit_id], key=lambda record: record.line_number)
        target = records[-1]
        duplicate = len(records) > 1
        if duplicate:
            drift.append(tuple(_evidence(record) for record in records))
        allocation = reconcile_payout(
            target,
            charges,
            tolerance,
            window_seconds=window_seconds,
            duplicate=duplicate,
        )
        comparison = _derived_comparison(target, allocation, linked_by_charge, invoice_net)
        results.append(
            DepositResult(
                deposit_id=deposit_id,
                allocation=allocation,
                duplicate=duplicate,
                evidence=tuple(_evidence(record) for record in records),
                comparison=comparison,
            )
        )
    return (
        tuple(results),
        duplicates,
        tuple(sorted(drift, key=lambda group: group[0].statement_reference)),
    )


def _derived_comparison(
    deposit: BankDepositRecord,
    allocation: Allocation,
    linked_by_charge: Mapping[str, str],
    invoice_net: Mapping[str, Decimal],
) -> DerivedComparison | None:
    invoice_ids = tuple(
        sorted(
            {
                linked_by_charge[leg.payment_id]
                for leg in allocation.legs
                if leg.payment_id in linked_by_charge
            }
        )
    )
    if not invoice_ids:
        return None
    total = sum((invoice_net[invoice_id] for invoice_id in invoice_ids), Decimal("0"))
    return DerivedComparison(
        deposit_id=deposit.deposit_id,
        invoice_ids=invoice_ids,
        invoice_net_total=total,
        deposit_amount=deposit.amount,
        difference=deposit.amount - total,
    )


def _warnings(
    invoices: Sequence[PaymentRecord],
    charges: Sequence[PaymentRecord],
    ingest: BankIngestResult,
    deposits: Sequence[DepositResult],
    duplicate_groups: Sequence[Sequence[DepositEvidence]],
    drift_groups: Sequence[Sequence[DepositEvidence]],
    unlinked_invoices: Sequence[str],
    unlinked_charges: Sequence[str],
    exponent: int,
) -> tuple[str, ...]:
    warnings: list[str] = []
    if not charges:
        warnings.append(
            "no processor legs: the invoice_to_charge and charge_to_deposit edges have no evidence"
        )
    if not ingest.deposits:
        warnings.append("no bank evidence: the charge_to_deposit edge has no deposits")
    for deposit in deposits:
        if deposit.allocation.outcome is PayoutOutcome.PENDING_EVIDENCE:
            warnings.append(
                f"deposit {deposit.deposit_id!r} is pending evidence "
                f"({_reason_name(deposit.allocation)})"
            )
    if unlinked_invoices:
        warnings.append(f"unlinked invoices: {', '.join(unlinked_invoices)}")
    if unlinked_charges:
        warnings.append(f"unlinked charges: {', '.join(unlinked_charges)}")
    for group in duplicate_groups:
        rendered = ", ".join(
            f"{item.statement_reference}@{_render_money(item.amount, exponent)}" for item in group
        )
        warnings.append("exact duplicate statement rows: " + rendered)
    for group in drift_groups:
        rendered = ", ".join(
            f"{item.statement_reference}@{_render_money(item.amount, exponent)}" for item in group
        )
        warnings.append("statement rows share an id with differing amounts: " + rendered)
    if not invoices:
        warnings.append("no invoice register rows")
    return tuple(warnings)


def _reason_name(allocation: Allocation) -> str:
    return allocation.reason.value if allocation.reason is not None else "UNKNOWN"


def _render_money(value: Decimal, exponent: int) -> str:
    """Render money at the currency exponent without changing its value.

    Core money guards already quantize every amount to the currency exponent,
    so this only pads the text (``0`` becomes ``0.00`` for USD); it never
    rounds a value.
    """
    quantized = value.quantize(Decimal(1).scaleb(-exponent))
    return format(quantized, "f")


def _fingerprint(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Export adapter (fixtures and API callers)
# ---------------------------------------------------------------------------


def sources_from_export(
    case: Mapping[str, Any],
    *,
    tenant_id: str,
    currency: str,
    tolerance: ReconciliationTolerance,
    statement_digest: str,
    window_seconds: int | None = None,
) -> StatementSources:
    """Build ``StatementSources`` from the canonical JSON export shape.

    The export shape is ``{"invoice": [...], "stripe": [...], "bank": [...]}``
    where each leg carries ``payment_id``, ``provider``, ``gross``, ``fee``,
    ``refund``, ``currency``, ``status``, and ``occurred_at``. Bank entries are
    statement lines: their ``source_reference`` is the line identity, so a
    re-import of the same line deduplicates while an edited amount surfaces as
    a drifted duplicate.
    """
    invoices = tuple(_leg(entry, tenant_id) for entry in case.get("invoice", ()))
    charges = tuple(_leg(entry, tenant_id) for entry in case.get("stripe", ()))
    rows = tuple(
        {
            "deposit_id": entry["source_reference"],
            "amount": entry["gross"],
            "posted_at": str(entry["occurred_at"])[:10],
            "account": entry.get("account", "operating"),
            "reference": entry["source_reference"],
            "description": entry["payment_id"],
            "fee": entry.get("fee", "0.00"),
        }
        for entry in case.get("bank", ())
    )
    return StatementSources(
        tenant_id=tenant_id,
        currency=currency,
        invoices=invoices,
        charges=charges,
        bank_rows=rows,
        mapping=BankStatementMapping(statement_currency=currency),
        statement_digest=statement_digest,
        tolerance=tolerance,
        window_seconds=window_seconds,
    )


def _leg(entry: Mapping[str, Any], tenant_id: str) -> PaymentRecord:
    gross = Decimal(str(entry["gross"]))
    fee = Decimal(str(entry.get("fee", "0.00")))
    refund = Decimal(str(entry.get("refund", "0.00")))
    occurred_at = datetime.fromisoformat(str(entry["occurred_at"]).replace("Z", "+00:00"))
    return PaymentRecord(
        payment_id=str(entry["payment_id"]),
        provider=str(entry["provider"]),
        provider_event_id=str(entry["provider_event_id"]),
        idempotency_key=str(entry["idempotency_key"]),
        gross=gross,
        fee=fee,
        refund=refund,
        net=gross - fee - refund,
        currency=str(entry["currency"]),
        status=PaymentStatus(str(entry["status"])),
        occurred_at=occurred_at.astimezone(UTC),
        tenant_id=tenant_id,
        source_reference=entry.get("source_reference"),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run one or every fixture scenario and print the report as JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True, help="Path to cases.json")
    parser.add_argument(
        "--scenario", action="append", default=None, help="Scenario id (repeatable)"
    )
    parser.add_argument("--window-seconds", type=int, default=None)
    parser.add_argument("--out", type=Path, default=None, help="Write JSON here instead of stdout")
    args = parser.parse_args(argv)

    document = json.loads(args.cases.read_text(encoding="utf-8"))
    tenant_id = str(document["tenant_id"])
    currency = str(document["currency"])
    digest = hashlib.sha256(args.cases.read_bytes()).hexdigest()
    scenarios: Mapping[str, Any] = document["scenarios"]
    selected = args.scenario or sorted(scenarios)

    reports: dict[str, Any] = {}
    for name in selected:
        if name not in scenarios:
            raise SystemExit(f"unknown scenario: {name}")
        sources = sources_from_export(
            scenarios[name],
            tenant_id=tenant_id,
            currency=currency,
            tolerance=ReconciliationTolerance(),
            statement_digest=digest,
            window_seconds=args.window_seconds,
        )
        reports[name] = run_statement_reconciliation(sources).to_dict()

    rendered = json.dumps(reports, indent=2, sort_keys=True)
    if args.out is None:
        sys.stdout.write(rendered + "\n")
    else:
        args.out.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
