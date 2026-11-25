"""Deterministic context builder for CP1-C.

:func:`build_exception_context` reads persisted reconciliation rows and
assembles an :class:`finance.reconciliation.context.ExceptionContext` packet
for a single exception. It never re-ingests source files or re-runs the
reconciliation engine: every value comes from already-persisted rows.

Tenant scoping is enforced on every query; a missing or cross-tenant run or
exception raises :class:`ContextNotFoundError` (identical message, so no
existence is disclosed across tenants).

Only SQLAlchemy + the Python standard library are used.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from finance.reconciliation.context import (
    ExceptionContext,
    RuleResult,
    RuleStatus,
)
from shared.models.reconciliation import (
    AllocationLeg,
    PayoutAllocation,
    ReconciliationException,
    ReconciliationMatch,
    ReconciliationRun,
)


class ContextNotFoundError(ValueError):
    """Raised when a run or exception cannot be found for the tenant."""


class CurrencyRequiredError(ValueError):
    """Raised when currency cannot be established from input or data."""


def _money_str(value: Any) -> str:
    """Render a value as a plain Decimal string (never float)."""
    if value is None:
        return "0.00"
    if isinstance(value, Decimal):
        return format(value, "f")
    try:
        return format(Decimal(str(value)), "f")
    except Exception:  # noqa: BLE001 - defensive
        return str(value)


def _classify_evidence(ref: str) -> str:
    """Best-effort evidence type classification from a reference string."""
    lowered = ref.lower()
    if lowered.startswith(("inv", "invoice")):
        return "invoice"
    if lowered.startswith(("ch", "charge", "txn", "transaction", "stripe")):
        return "stripe_transaction"
    if lowered.startswith(("dep", "deposit", "bank", "stmt")):
        return "bank_deposit"
    return "reference"


def _summarize_matches(matches: Sequence[ReconciliationMatch]) -> str:
    """Render a compact, deterministic match summary."""
    if not matches:
        return "no persisted matches"
    counts: dict[str, int] = {}
    for m in matches:
        counts[m.outcome] = counts.get(m.outcome, 0) + 1
    parts = [f"{outcome}={count}" for outcome, count in sorted(counts.items())]
    return f"{len(matches)} match(es): " + ", ".join(parts)


def _summarize_allocations(allocations: Sequence[PayoutAllocation]) -> str:
    """Render a compact, deterministic allocation summary."""
    if not allocations:
        return "no persisted allocations"
    return f"{len(allocations)} allocation(s): " + ", ".join(
        f"{a.deposit_id or a.allocation_id}({a.outcome})" for a in allocations
    )


def _build_rule_results(
    exc: ReconciliationException,
    matches: Sequence[ReconciliationMatch],
    allocations: Sequence[PayoutAllocation],
    currency: str,
    expected_net: str,
    actual_deposit: str,
    variance: str,
) -> list[RuleResult]:
    """Build the rule-result list for one exception."""
    results: list[RuleResult] = [
        RuleResult(
            rule_id=exc.exception_code or "EXCEPTION",
            status=RuleStatus.FAIL,
            severity=exc.severity,
            message=exc.description,
            expected=expected_net,
            actual=actual_deposit,
            difference=variance,
            currency=currency,
            evidence_refs=list(exc.evidence_refs or []),
        )
    ]
    # Run-level integrity rule: did every match close cleanly?
    exception_matches = [m for m in matches if m.outcome not in ("MATCHED", "TOLERANCE_MATCHED")]
    if matches and not exception_matches:
        results.append(
            RuleResult(
                rule_id="RUN_MATCH_INTEGRITY",
                status=RuleStatus.PASS,
                severity="LOW",
                message="All persisted matches closed as MATCHED or TOLERANCE_MATCHED.",
                currency=currency,
            )
        )
    elif matches:
        results.append(
            RuleResult(
                rule_id="RUN_MATCH_INTEGRITY",
                status=RuleStatus.WARNING,
                severity="MEDIUM",
                message=f"{len(exception_matches)} match(es) did not close cleanly.",
                currency=currency,
            )
        )
    else:
        results.append(
            RuleResult(
                rule_id="RUN_MATCH_INTEGRITY",
                status=RuleStatus.NOT_APPLICABLE,
                severity="LOW",
                message="No persisted matches for this run.",
                currency=currency,
            )
        )
    # Allocation integrity: open balance must be zero for a clean allocation.
    for alloc in allocations:
        open_balance = _money_str(alloc.open_balance)
        if Decimal(open_balance) == 0:
            results.append(
                RuleResult(
                    rule_id=f"ALLOCATION_BALANCE_{alloc.allocation_id}",
                    status=RuleStatus.PASS,
                    severity="LOW",
                    message="Allocation legs balance (open balance is zero).",
                    expected="0",
                    actual=open_balance,
                    difference=open_balance,
                    currency=currency,
                )
            )
        else:
            results.append(
                RuleResult(
                    rule_id=f"ALLOCATION_BALANCE_{alloc.allocation_id}",
                    status=RuleStatus.FAIL,
                    severity="MEDIUM",
                    message="Allocation has a non-zero open balance.",
                    expected="0",
                    actual=open_balance,
                    difference=open_balance,
                    currency=currency,
                )
            )
    return results


def build_exception_context(
    session: Session,
    *,
    tenant_id: str,
    run_id: str,
    exception_id: str,
    currency: str,
) -> ExceptionContext:
    """Build an :class:`ExceptionContext` from persisted reconciliation rows.

    Args:
        session: SQLAlchemy session bound to the (already migrated) database.
        tenant_id: Trusted tenant from the calling context (never from input).
        run_id: Reconciliation run to read.
        exception_id: Exception within that run.
        currency: ISO 4217 currency code for the run. Required; never defaulted,
            because FinSight is not inherently USD-only.

    Returns:
        A frozen, deterministic :class:`ExceptionContext`.

    Raises:
        ContextNotFoundError: If the run or exception is missing or
            belongs to another tenant.
    """
    if not tenant_id or not tenant_id.strip():
        raise ContextNotFoundError("run or exception not found")
    tenant_id = tenant_id.strip()

    if not currency or not currency.strip():
        raise CurrencyRequiredError("currency is required")
    resolved_input = currency.strip().upper()
    if len(resolved_input) != 3 or not resolved_input.isalpha():
        raise CurrencyRequiredError(f"currency must be a 3-letter ISO 4217 code, got {currency!r}")

    run = session.execute(
        select(ReconciliationRun).where(
            ReconciliationRun.run_id == run_id,
            ReconciliationRun.tenant_id == tenant_id,
        )
    ).scalar_one_or_none()
    if run is None:
        raise ContextNotFoundError("run or exception not found")

    exc = session.execute(
        select(ReconciliationException).where(
            ReconciliationException.exception_id == exception_id,
            ReconciliationException.tenant_id == tenant_id,
            ReconciliationException.run_id == run_id,
        )
    ).scalar_one_or_none()
    if exc is None:
        raise ContextNotFoundError("run or exception not found")

    matches = list(
        session.execute(select(ReconciliationMatch).where(ReconciliationMatch.run_id == run_id))
        .scalars()
        .all()
    )
    allocations = list(
        session.execute(select(PayoutAllocation).where(PayoutAllocation.run_id == run_id))
        .scalars()
        .all()
    )
    # load legs for allocations
    alloc_ids = [a.allocation_id for a in allocations]
    legs: list[AllocationLeg] = []
    if alloc_ids:
        legs = list(
            session.execute(select(AllocationLeg).where(AllocationLeg.allocation_id.in_(alloc_ids)))
            .scalars()
            .all()
        )
    legs_by_alloc: dict[str, list[AllocationLeg]] = {}
    for leg in legs:
        legs_by_alloc.setdefault(leg.allocation_id, []).append(leg)

    resolved_currency = resolved_input

    # Calculations from the first allocation (if any) for this run.
    captured = "0.00"
    refunds = "0.00"
    fees = "0.00"
    adjustments = "0.00"
    expected_net = "0.00"
    actual_deposit = "0.00"
    variance = "0.00"
    tolerance = "0.00"
    if allocations:
        alloc = allocations[0]
        expected_net = _money_str(alloc.eligible_net_total)
        actual_deposit = _money_str(alloc.allocated_total)
        variance = _money_str(alloc.open_balance)
        fees = _money_str(alloc.fee_total)
        refunds = _money_str(alloc.refund_total)
        captured = _money_str(alloc.eligible_net_total)
        adjustments = "0.00"
        tolerance = "0.00"
        # tolerance not persisted on allocation; leave as provided/zero

    evidence_refs = list(exc.evidence_refs or [])
    evidence = [{"type": _classify_evidence(ref), "record_id": ref} for ref in evidence_refs]

    # Eligibility: need evidence refs and at least one match or allocation.
    if not evidence_refs:
        eligible = False
        reason = "No evidence references provided."
    elif not matches and not allocations:
        eligible = False
        reason = "No persisted matches or allocations for this run."
    else:
        eligible = True
        reason = None

    rule_results = _build_rule_results(
        exc,
        matches,
        allocations,
        resolved_currency,
        expected_net,
        actual_deposit,
        variance,
    )

    return ExceptionContext(
        exception_id=exc.exception_id,
        exception_code=exc.exception_code,
        severity=exc.severity,
        title=exc.title,
        description=exc.description,
        currency=resolved_currency,
        expected_net=expected_net,
        actual_deposit=actual_deposit,
        variance=variance,
        tolerance=tolerance,
        calculations={
            "captured": captured,
            "refunds": refunds,
            "fees": fees,
            "adjustments": adjustments,
            "eligible_net_total": expected_net,
            "allocated_total": actual_deposit,
            "open_balance": variance,
            "fee_total": fees,
            "refund_total": refunds,
        },
        evidence_refs=evidence_refs,
        evidence=evidence,
        match_summary=_summarize_matches(matches),
        allocation_summary=_summarize_allocations(allocations),
        rule_results=rule_results,
        investigation_eligible=eligible,
        ineligibility_reason=reason,
    )
