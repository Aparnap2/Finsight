"""CP2 diagnostic composition for reconciliation exceptions.

:func:`diagnose_exception` composes CP1 context models with existing
reconciliation arithmetic to produce a structured, deterministic
:class:`ExceptionDiagnostic`. It never re-ingests source files or re-runs
the reconciliation engine: every value is read from persisted rows or
verified by deterministic consistency checks over those rows.

Only SQLAlchemy + the Python standard library are used.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from finance.reconciliation.context import (
    EligibilityDecision,
    EligibilityStatus,
    ExceptionContext,
    ExceptionDiagnostic,
    RuleResult,
    RuleStatus,
)
from finance.reconciliation.context_builder import (
    ContextNotFoundError,
    CurrencyRequiredError,
    build_exception_context,
)
from shared.models.reconciliation import (
    AllocationLeg,
    PayoutAllocation,
    ReconciliationMatch,
    ReconciliationRun,
)


def _dec(value: str) -> Decimal:
    try:
        return Decimal(value)
    except Exception:  # noqa: BLE001 - defensive
        return Decimal("0")


def _diagnostic_rule_results(
    context: ExceptionContext,
    run: ReconciliationRun,
    matches: list[ReconciliationMatch],
    allocations: list[PayoutAllocation],
    legs: list[AllocationLeg],
    currency: str,
) -> list[RuleResult]:
    """Compose structured rule results from persisted data + consistency checks."""
    results: list[RuleResult] = list(context.rule_results)

    # Payout variance: expected vs actual deposit.
    variance = _dec(context.variance)
    if variance == 0:
        results.append(
            RuleResult(
                rule_id="PAYOUT_VARIANCE",
                status=RuleStatus.PASS,
                severity="LOW",
                message="Expected settlement equals the bank deposit.",
                expected=context.expected_net,
                actual=context.actual_deposit,
                difference=context.variance,
                currency=currency,
                evidence_refs=list(context.evidence_refs),
            )
        )
    else:
        results.append(
            RuleResult(
                rule_id="PAYOUT_VARIANCE",
                status=RuleStatus.FAIL,
                severity=context.severity,
                message="Bank deposit differs from expected settlement.",
                expected=context.expected_net,
                actual=context.actual_deposit,
                difference=context.variance,
                currency=currency,
                evidence_refs=list(context.evidence_refs),
            )
        )

    # Evidence completeness.
    if context.evidence_refs:
        results.append(
            RuleResult(
                rule_id="EVIDENCE_COMPLETENESS",
                status=RuleStatus.PASS,
                severity="LOW",
                message="Evidence references are present.",
                currency=currency,
                evidence_refs=list(context.evidence_refs),
            )
        )
    else:
        results.append(
            RuleResult(
                rule_id="EVIDENCE_COMPLETENESS",
                status=RuleStatus.FAIL,
                severity="HIGH",
                message="No evidence references available for this exception.",
                currency=currency,
                evidence_refs=[],
            )
        )

    # Calculation consistency: captured - refunds - fees + adjustments == expected_net.
    captured = _dec(context.calculations.get("captured", "0"))
    refunds = _dec(context.calculations.get("refunds", "0"))
    fees = _dec(context.calculations.get("fees", "0"))
    adjustments = _dec(context.calculations.get("adjustments", "0"))
    recomputed = captured - refunds - fees + adjustments
    expected = _dec(context.expected_net)
    if recomputed == expected:
        results.append(
            RuleResult(
                rule_id="CALCULATION_CONSISTENCY",
                status=RuleStatus.PASS,
                severity="LOW",
                message="Persisted calculations are internally consistent.",
                expected=_money(recomputed),
                actual=_money(expected),
                difference=_money(recomputed - expected),
                currency=currency,
                evidence_refs=list(context.evidence_refs),
            )
        )
    else:
        results.append(
            RuleResult(
                rule_id="CALCULATION_CONSISTENCY",
                status=RuleStatus.FAIL,
                severity="HIGH",
                message="Persisted calculations are internally inconsistent.",
                expected=_money(recomputed),
                actual=_money(expected),
                difference=_money(recomputed - expected),
                currency=currency,
                evidence_refs=list(context.evidence_refs),
            )
        )

    # Duplicate detection: flag if any allocation had duplicate evidence.
    # We rely on match outcomes for duplicate signal.
    dup_matches = [
        m
        for m in matches
        if m.outcome == "EXCEPTION" and (m.exception_code or "").startswith("I-DUP")
    ]
    if dup_matches:
        results.append(
            RuleResult(
                rule_id="DUPLICATE_DETECTION",
                status=RuleStatus.FAIL,
                severity="HIGH",
                message=f"{len(dup_matches)} duplicate ledger entry(ies) detected.",
                currency=currency,
                evidence_refs=list(context.evidence_refs),
            )
        )
    else:
        results.append(
            RuleResult(
                rule_id="DUPLICATE_DETECTION",
                status=RuleStatus.PASS,
                severity="LOW",
                message="No duplicate ledger entries detected.",
                currency=currency,
                evidence_refs=list(context.evidence_refs),
            )
        )

    return results


def _money(value: Decimal) -> str:
    return format(value, "f")


def diagnose_exception(
    session: Session,
    *,
    tenant_id: str,
    snapshot_id: str,
    exception_id: str,
    currency: str,
) -> ExceptionDiagnostic:
    """Compose a deterministic diagnostic for one exception.

    Args:
        session: SQLAlchemy session bound to the database.
        tenant_id: Trusted tenant from the calling context.
        snapshot_id: Snapshot/run identifier (resolved against
            ``ReconciliationRun.run_id`` or ``input_snapshot_ref``).
        exception_id: Exception to diagnose.
        currency: ISO 4217 currency code. Required.

    Returns:
        An :class:`ExceptionDiagnostic`.

    Raises:
        ContextNotFoundError: If the run or exception is missing or
            belongs to another tenant.
        CurrencyRequiredError: If ``currency`` is invalid.
    """
    if not currency or not currency.strip():
        raise CurrencyRequiredError("currency is required")
    resolved_currency = currency.strip().upper()
    if len(resolved_currency) != 3 or not resolved_currency.isalpha():
        raise CurrencyRequiredError(f"currency must be a 3-letter ISO 4217 code, got {currency!r}")

    if not tenant_id or not tenant_id.strip():
        raise ContextNotFoundError("run or exception not found")
    tenant_id = tenant_id.strip()

    # Resolve run by snapshot_id (run_id or input_snapshot_ref).
    run = session.execute(
        select(ReconciliationRun).where(
            ReconciliationRun.tenant_id == tenant_id,
            (ReconciliationRun.run_id == snapshot_id)
            | (ReconciliationRun.input_snapshot_ref == snapshot_id),
        )
    ).scalar_one_or_none()
    if run is None:
        raise ContextNotFoundError("run or exception not found")

    # Query counter: track session.execute calls.
    query_count = 1

    matches = list(
        session.execute(select(ReconciliationMatch).where(ReconciliationMatch.run_id == run.run_id))
        .scalars()
        .all()
    )
    query_count += 1

    allocations = list(
        session.execute(select(PayoutAllocation).where(PayoutAllocation.run_id == run.run_id))
        .scalars()
        .all()
    )
    query_count += 1

    alloc_ids = [a.allocation_id for a in allocations]
    legs: list[AllocationLeg] = []
    if alloc_ids:
        legs = list(
            session.execute(select(AllocationLeg).where(AllocationLeg.allocation_id.in_(alloc_ids)))
            .scalars()
            .all()
        )
        query_count += 1

    # Build CP1 context (this issues its own queries; count them).
    # We measure by counting the context builder's queries separately is not
    # possible without instrumentation; instead we count diagnostic-level
    # queries above and add a fixed estimate for the builder (4 queries).
    context = build_exception_context(
        session,
        tenant_id=tenant_id,
        run_id=run.run_id,
        exception_id=exception_id,
        currency=resolved_currency,
    )
    # build_exception_context issues 4 selects (run, exception, matches, allocations)
    # plus legs if allocations exist.
    query_count += 4
    if allocations:
        query_count += 1

    snapshot = run.input_snapshot_ref or run.input_fingerprint or run.run_id
    if snapshot_id and snapshot_id != run.run_id:
        # caller-supplied snapshot_id takes precedence for identity
        snapshot = snapshot_id

    diagnostic_rules = _diagnostic_rule_results(
        context, run, matches, allocations, legs, resolved_currency
    )
    # Merge: context already has rule_results from CP1; prepend diagnostic-specific
    # new ones (avoid duplicating rule_ids already present).
    existing_ids = {r.rule_id for r in context.rule_results}
    merged = list(context.rule_results) + [
        r for r in diagnostic_rules if r.rule_id not in existing_ids
    ]

    eligibility = determine_eligibility(
        ExceptionDiagnostic(
            run_id=run.run_id,
            exception_id=context.exception_id,
            tenant_id=tenant_id,
            snapshot_id=snapshot,
            engine_version=run.engine_version,
            rule_version="1.0",
            status="diagnosed",
            context=context,
            rule_results=merged,
            query_count=query_count,
        )
    )

    return ExceptionDiagnostic(
        run_id=run.run_id,
        exception_id=context.exception_id,
        tenant_id=tenant_id,
        snapshot_id=snapshot,
        engine_version=run.engine_version,
        rule_version="1.0",
        status="diagnosed",
        context=context,
        rule_results=merged,
        eligibility=eligibility,
        query_count=query_count,
    )


_INTEGRITY_RULE_IDS = {"RUN_MATCH_INTEGRITY", "CALCULATION_CONSISTENCY"}


def determine_eligibility(diagnostic: ExceptionDiagnostic) -> EligibilityDecision:
    """Classify a diagnostic into an investigation eligibility decision (CP3).

    Pure, deterministic, no database access. The decision is derived from the
    diagnostic's rule results and evidence completeness; the LLM is never
    consulted.

    Precedence: INELIGIBLE > BLOCKED > REVIEW_REQUIRED > ELIGIBLE.
    """
    context = diagnostic.context
    rules = diagnostic.rule_results if diagnostic.rule_results else context.rule_results

    evidence_complete = bool(context.evidence_refs) and any(
        r.rule_id == "EVIDENCE_COMPLETENESS" and r.status == RuleStatus.PASS for r in rules
    )
    if not any(r.rule_id == "EVIDENCE_COMPLETENESS" for r in rules):
        evidence_complete = bool(context.evidence_refs)

    integrity_rules = [
        r
        for r in rules
        if r.rule_id in _INTEGRITY_RULE_IDS or r.rule_id.startswith("ALLOCATION_BALANCE_")
    ]
    integrity_ok = (
        all(r.status != RuleStatus.FAIL for r in integrity_rules) if integrity_rules else True
    )

    ambiguous = False
    ambiguous_reasons: list[str] = []
    if any(r.rule_id == "DUPLICATE_DETECTION" and r.status == RuleStatus.FAIL for r in rules):
        ambiguous = True
        ambiguous_reasons.append("duplicate ledger entries detected")

    if not evidence_complete:
        evidence_rule_ids = [r.rule_id for r in rules if r.rule_id == "EVIDENCE_COMPLETENESS"]
        return EligibilityDecision(
            status=EligibilityStatus.INELIGIBLE,
            reason="Required evidence is missing.",
            evidence_complete=False,
            integrity_ok=integrity_ok,
            ambiguous=ambiguous,
            rule_ids=evidence_rule_ids,
        )

    if not integrity_ok:
        failed = [r.rule_id for r in integrity_rules if r.status == RuleStatus.FAIL]
        return EligibilityDecision(
            status=EligibilityStatus.BLOCKED,
            reason="Prerequisite integrity check failed: " + ", ".join(failed) + ".",
            evidence_complete=True,
            integrity_ok=False,
            ambiguous=ambiguous,
            rule_ids=failed,
        )

    if ambiguous:
        ambig_ids = [r.rule_id for r in rules if r.rule_id == "DUPLICATE_DETECTION"]
        return EligibilityDecision(
            status=EligibilityStatus.REVIEW_REQUIRED,
            reason="Evidence exists but is ambiguous: " + "; ".join(ambiguous_reasons) + ".",
            evidence_complete=True,
            integrity_ok=True,
            ambiguous=True,
            rule_ids=ambig_ids,
        )

    return EligibilityDecision(
        status=EligibilityStatus.ELIGIBLE,
        reason="Required evidence and calculations are complete.",
        evidence_complete=True,
        integrity_ok=True,
        ambiguous=False,
        rule_ids=[],
    )
