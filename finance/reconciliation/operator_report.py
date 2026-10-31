"""Operator-facing evidence for the three-source statement reconciliation.

This module is additive: it calls the existing public entry point
(``run_statement_reconciliation``) and renders its result. It does not
re-implement linking, allocation, or classification, and it never derives an
expected amount from the report it is checking: expected workflow results are
loaded from the checked-in fixture table, while conservation, duplicate-safety,
tenant-scoping, determinism, and immutability checks are computed from the
inputs and the frozen core's own invariants.

Run with::

    python -m finance.reconciliation.operator_report \
        --cases tests/fixtures/reconciliation/triangle/cases.json \
        --expected tests/fixtures/reconciliation/triangle/operator_expected.json \
        --markdown docs/evidence/operator-run/report.md \
        --json docs/evidence/operator-run/report.json \
        --evidence docs/evidence/operator-run/run.json \
        --source-commit "$(git rev-parse HEAD)"

The process exits 0 only when every expected result, cross-check, and
invariant passes. A deliberately wrong ``--expected`` value therefore exits 1.
All fixture data is synthetic; no customer or production financial data is
read, written, or logged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from finance.reconciliation.errors import InvariantViolation
from finance.reconciliation.models import PayoutOutcome, ReconciliationOutcome
from finance.reconciliation.statement_workflow import (
    ReconciliationReport,
    StatementSources,
    run_statement_reconciliation,
    sources_from_export,
)
from finance.reconciliation.tolerances import ReconciliationTolerance

STATUS_LEGEND: Mapping[str, str] = {
    "reconciled": "Reconciled — invoice, processor, and bank evidence agree.",
    "exception": "Exception — investigate before treating this deposit as settled.",
    "pending_evidence": "Pending evidence — the run cannot decide yet; do not book as settled.",
    "ambiguous": "Ambiguous — more than one valid allocation; a human must choose.",
}

_STATUS_BY_OUTCOME: Mapping[str, str] = {
    ReconciliationOutcome.MATCHED.value: "reconciled",
    ReconciliationOutcome.TOLERANCE_MATCHED.value: "reconciled",
    ReconciliationOutcome.EXCEPTION.value: "exception",
    ReconciliationOutcome.PENDING_EVIDENCE.value: "pending_evidence",
    PayoutOutcome.MATCHED.value: "reconciled",
    PayoutOutcome.TOLERANCE_MATCHED.value: "reconciled",
    PayoutOutcome.EXCEPTION.value: "exception",
    PayoutOutcome.PENDING_EVIDENCE.value: "pending_evidence",
    PayoutOutcome.REQUIRES_HUMAN.value: "ambiguous",
}

_STATUS_SEVERITY: Mapping[str, int] = {
    "reconciled": 0,
    "pending_evidence": 1,
    "exception": 2,
    "ambiguous": 3,
}


@dataclass(frozen=True)
class CheckResult:
    """One auditable check performed during the operator run."""

    scenario: str
    kind: str
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class OperatorRun:
    """The rendered operator run plus its machine-checkable verdict."""

    document: Mapping[str, Any]
    markdown: str
    checks: tuple[CheckResult, ...]

    @property
    def failures(self) -> tuple[CheckResult, ...]:
        """Return only failing checks, in stable order."""
        return tuple(check for check in self.checks if not check.passed)

    @property
    def passed(self) -> bool:
        """Return True when every expected result and invariant passed."""
        return not self.failures


def _money(value: Decimal, exponent: int) -> str:
    """Render exact Decimal money without ever rounding."""
    quantum = Decimal(1).scaleb(-exponent)
    if value != value.quantize(quantum):
        raise InvariantViolation(f"{value} does not fit the {exponent}-digit display scale.")
    return format(value.quantize(quantum), "f")


def _outcome_name(value: ReconciliationOutcome | PayoutOutcome | None) -> str | None:
    """Return the JSON name of an outcome enum or None."""
    return None if value is None else value.value


def _scenario_status(
    outcomes: Sequence[str | None],
    *,
    deposits: int,
    invoices: int,
) -> str:
    """Collapse per-deposit outcomes into one operator status.

    An empty deposit set is pending evidence, not a success: the bank leg of
    the triangle is absent and the workflow cannot decide.
    """
    if not outcomes:
        return "pending_evidence"
    statuses = [_STATUS_BY_OUTCOME.get(name or "", "pending_evidence") for name in outcomes]
    return max(statuses, key=lambda status: _STATUS_SEVERITY[status])


def _check(
    scenario: str,
    kind: str,
    name: str,
    passed: bool,
    detail: str,
) -> CheckResult:
    """Build one check result with a deterministic detail string."""
    return CheckResult(scenario=scenario, kind=kind, name=name, passed=passed, detail=detail)


def _read_json(path: Path) -> tuple[dict[str, Any], str]:
    """Read a JSON object and return it with its sha256 digest."""
    raw = path.read_bytes()
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise InvariantViolation(f"{path} must contain a JSON object.")
    return payload, hashlib.sha256(raw).hexdigest()


def _input_snapshot(case: Mapping[str, Any]) -> str:
    """Return a canonical snapshot used to prove inputs are not mutated."""
    return json.dumps(case, sort_keys=True, separators=(",", ":"))


def _expected_money(expected: Mapping[str, Any], key: str) -> Decimal | None:
    """Parse an optional money string from the expectation table."""
    value = expected.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvariantViolation(f"expected {key} must be a decimal string.")
    return Decimal(value)


def _compare_expected(
    scenario: str,
    expected: Mapping[str, Any],
    row: Mapping[str, Any],
) -> list[CheckResult]:
    """Compare one scenario row against the checked-in expectation table."""
    checks: list[CheckResult] = []

    def compare(name: str, actual: object, want: object) -> None:
        checks.append(
            _check(
                scenario,
                "expected",
                name,
                actual == want,
                f"expected {want!r}, observed {actual!r}",
            )
        )

    compare("status", row["status"], expected.get("status"))
    compare("outcome", row["outcome"], expected.get("outcome"))
    classification = row["classification"]
    compare("reason", classification["reason"], expected.get("reason"))
    compare("exception_code", classification["exception_code"], expected.get("exception_code"))
    compare("deposits", row["deposit_results"], expected.get("deposits"))

    amounts = row["amounts"]
    for name in ("allocated_total", "open_balance", "unallocated_deposit"):
        if name in expected:
            compare(name, amounts[name], expected.get(name))
    if "derived_difference" in expected:
        compare("derived_difference", amounts["derived_difference"], expected["derived_difference"])

    if "candidates" in expected:
        compare(
            "candidates",
            [list(candidate) for candidate in row["evidence"]["candidates"]],
            expected["candidates"],
        )
    if "duplicate_groups" in expected:
        compare(
            "duplicate_groups",
            len(row["evidence"]["duplicate_groups"]),
            expected["duplicate_groups"],
        )
    if "drift_groups" in expected:
        compare(
            "drift_groups",
            len(row["evidence"]["drift_groups"]),
            expected["drift_groups"],
        )
    return checks


def _compare_cross_check(
    scenario: str,
    edge: str,
    check_name: str,
    pairwise: Mapping[str, Any] | None,
    row: Mapping[str, Any],
) -> list[CheckResult]:
    """Assert that a workflow edge agrees with the frozen pairwise fixture.

    Only fields present in the pairwise table are compared, so an unsupported
    pairwise check never silently constrains the composed surface.
    """
    if pairwise is None:
        return [
            _check(
                scenario,
                "cross_check",
                f"{edge}:{check_name}",
                False,
                f"pairwise expectation {check_name!r} is missing",
            )
        ]
    if pairwise.get("supported") is False:
        return [
            _check(
                scenario,
                "cross_check",
                f"{edge}:{check_name}",
                False,
                f"cross-check points at unsupported pairwise check {check_name!r}",
            )
        ]

    checks: list[CheckResult] = []
    if edge == "invoice_to_charge":
        links = row["evidence"]["links"]
        if len(links) != 1:
            return [
                _check(
                    scenario,
                    "cross_check",
                    f"{edge}:{check_name}",
                    False,
                    f"cross-check requires exactly one link, found {len(links)}",
                )
            ]
        observed = {
            "outcome": links[0]["outcome"],
            "exception_code": links[0]["exception_code"],
            "difference": links[0]["difference"],
        }
    else:
        observed = {
            "outcome": row["outcome"],
            "exception_code": row["classification"]["exception_code"],
            "reason": row["classification"]["reason"],
        }
        allocation = row["evidence"].get("allocation", {})
        for name in ("allocated_total", "open_balance", "unallocated_deposit"):
            if name in allocation:
                observed[name] = allocation[name]
        if "candidates" in row["evidence"]:
            observed["candidates"] = [list(item) for item in row["evidence"]["candidates"]]

    skip = {"supported", "gap", "surface", "candidates"}
    if edge != "invoice_to_charge":
        skip.add("difference")
    for name, want in pairwise.items():
        if name in skip:
            continue
        if name not in observed:
            continue
        checks.append(
            _check(
                scenario,
                "cross_check",
                f"{edge}:{check_name}:{name}",
                observed[name] == want,
                f"pairwise {want!r}, composed {observed[name]!r}",
            )
        )
    if "candidates" in pairwise:
        checks.append(
            _check(
                scenario,
                "cross_check",
                f"{edge}:{check_name}:candidates",
                observed.get("candidates") == pairwise["candidates"],
                f"pairwise {pairwise['candidates']!r}, composed {observed.get('candidates')!r}",
            )
        )
    return checks


def _scenario_row(
    name: str,
    case: Mapping[str, Any],
    report: ReconciliationReport,
    exponent: int,
) -> dict[str, Any]:
    """Build the operator view of one scenario from the workflow report."""
    invoices = case.get("invoice", ())
    charges = case.get("stripe", ())
    invoice_net = sum((Decimal(str(item["gross"])) for item in invoices), Decimal("0"))
    invoice_net -= sum((Decimal(str(item.get("fee", "0.00"))) for item in invoices), Decimal("0"))
    invoice_net -= sum(
        (Decimal(str(item.get("refund", "0.00"))) for item in invoices), Decimal("0")
    )
    processor_net = sum((Decimal(str(item["gross"])) for item in charges), Decimal("0"))
    processor_net -= sum((Decimal(str(item.get("fee", "0.00"))) for item in charges), Decimal("0"))
    processor_net -= sum(
        (Decimal(str(item.get("refund", "0.00"))) for item in charges), Decimal("0")
    )

    outcomes = [_outcome_name(deposit.allocation.outcome) for deposit in report.deposits]
    status = _scenario_status(outcomes, deposits=len(report.deposits), invoices=len(invoices))

    reasons = sorted(
        {
            deposit.allocation.reason.value
            for deposit in report.deposits
            if deposit.allocation.reason is not None
        }
    )
    if not reasons and not report.deposits and not case.get("bank"):
        reasons = ["NO_DEPOSIT"]
    codes = sorted(
        {
            deposit.allocation.exception_code.value
            for deposit in report.deposits
            if deposit.allocation.exception_code is not None
        }
    )

    deposit_amounts: list[Decimal] = []
    for deposit in report.deposits:
        record = deposit.allocation.deposit
        if record is not None:
            deposit_amounts.append(record.amount)
    allocated = sum(
        (deposit.allocation.allocated_total for deposit in report.deposits), Decimal("0")
    )
    unallocated = sum(
        (deposit.allocation.unallocated_deposit for deposit in report.deposits), Decimal("0")
    )
    open_balance = sum(
        (deposit.allocation.open_balance for deposit in report.deposits), Decimal("0")
    )
    fee_total = sum((deposit.allocation.fee_total for deposit in report.deposits), Decimal("0"))
    refund_total = sum(
        (deposit.allocation.refund_total for deposit in report.deposits), Decimal("0")
    )

    comparisons = [
        deposit.comparison for deposit in report.deposits if deposit.comparison is not None
    ]
    derived = comparisons[0] if len(comparisons) == 1 else None

    deposit_evidence = [
        {
            "deposit_id": evidence.deposit_id,
            "statement_reference": evidence.statement_reference,
            "line_number": evidence.line_number,
            "amount": _money(evidence.amount, exponent),
        }
        for deposit in report.deposits
        for evidence in deposit.evidence
    ]
    candidate_sets = [
        list(candidate.payment_ids)
        for deposit in report.deposits
        for candidate in deposit.allocation.candidates
    ]
    allocation_view: dict[str, Any] = {}
    if len(report.deposits) == 1:
        allocation = report.deposits[0].allocation
        allocation_view = {
            "outcome": allocation.outcome.value,
            "allocated_total": _money(allocation.allocated_total, exponent),
            "open_balance": _money(allocation.open_balance, exponent),
            "unallocated_deposit": _money(allocation.unallocated_deposit, exponent),
        }

    return {
        "scenario": name,
        "description": str(case.get("description", "")),
        "status": status,
        "deposit_results": len(report.deposits),
        "outcome": outcomes[0] if len(outcomes) == 1 else (outcomes or None),
        "classification": {
            "reason": reasons[0] if len(reasons) == 1 else (reasons or None),
            "exception_code": codes[0] if len(codes) == 1 else (codes or None),
        },
        "amounts": {
            "invoice_expected_net": _money(invoice_net, exponent),
            "processor_evidence_net": _money(processor_net, exponent),
            "deposit_recorded": (
                _money(deposit_amounts[0], exponent) if len(deposit_amounts) == 1 else None
            ),
            "allocated_total": _money(allocated, exponent),
            "unallocated_deposit": _money(unallocated, exponent),
            "open_balance": _money(open_balance, exponent),
            "fee_total": _money(fee_total, exponent),
            "refund_total": _money(refund_total, exponent),
            "derived_difference": (
                _money(derived.difference, exponent) if derived is not None else None
            ),
        },
        "evidence": {
            "invoices": [
                {
                    "payment_id": str(item["payment_id"]),
                    "gross": str(item["gross"]),
                    "fee": str(item.get("fee", "0.00")),
                    "refund": str(item.get("refund", "0.00")),
                    "source_reference": item.get("source_reference"),
                }
                for item in invoices
            ],
            "charges": [
                {
                    "payment_id": str(item["payment_id"]),
                    "provider_event_id": str(item["provider_event_id"]),
                    "gross": str(item["gross"]),
                    "fee": str(item.get("fee", "0.00")),
                    "refund": str(item.get("refund", "0.00")),
                    "source_reference": item.get("source_reference"),
                }
                for item in charges
            ],
            "deposits": deposit_evidence,
            "links": [
                {
                    "invoice_id": link.invoice_id,
                    "charge_id": link.charge_id,
                    "difference": _money(link.difference, exponent),
                    "outcome": link.result.outcome.value,
                    "exception_code": link.result.exception_code,
                }
                for link in report.links
            ],
            "candidates": candidate_sets,
            "duplicate_groups": [
                [
                    {
                        "statement_reference": item.statement_reference,
                        "line_number": item.line_number,
                        "amount": _money(item.amount, exponent),
                    }
                    for item in group
                ]
                for group in report.duplicate_groups
            ],
            "drift_groups": [
                [
                    {
                        "statement_reference": item.statement_reference,
                        "line_number": item.line_number,
                        "amount": _money(item.amount, exponent),
                    }
                    for item in group
                ]
                for group in report.drift_groups
            ],
            "allocation": allocation_view,
        },
        "warnings": list(report.warnings),
        "limitations": [],
    }


def _invariants(
    name: str,
    sources: StatementSources,
    report: ReconciliationReport,
    case: Mapping[str, Any],
    exponent: int,
) -> list[CheckResult]:
    """Check conservation, duplicate safety, tenancy, and provenance."""
    checks: list[CheckResult] = []
    tenant = sources.tenant_id
    currency = sources.currency

    checks.append(
        _check(
            name,
            "invariant",
            "tenant_scope",
            report.tenant_id == tenant
            and all(record.tenant_id == tenant for record in sources.invoices)
            and all(record.tenant_id == tenant for record in sources.charges),
            f"report tenant {report.tenant_id!r}, source tenant {tenant!r}",
        )
    )
    checks.append(
        _check(
            name,
            "invariant",
            "currency_scope",
            report.currency == currency
            and all(record.currency == currency for record in sources.invoices)
            and all(record.currency == currency for record in sources.charges),
            f"report currency {report.currency!r}, fixture currency {currency!r}",
        )
    )

    leg_ids: list[str] = []
    for deposit in report.deposits:
        allocation = deposit.allocation
        deposit_id = deposit.deposit_id
        checks.append(
            _check(
                name,
                "invariant",
                f"{deposit_id}:allocation_conservation",
                allocation.allocated_total + allocation.open_balance
                == allocation.eligible_net_total,
                "allocated + open == eligible net "
                f"({allocation.allocated_total} + {allocation.open_balance} "
                f"!= {allocation.eligible_net_total})",
            )
        )

        evidence_amounts = {item.line_number: item.amount for item in deposit.evidence}
        if evidence_amounts:
            selected_amount = evidence_amounts[max(evidence_amounts)]
            checks.append(
                _check(
                    name,
                    "invariant",
                    f"{deposit_id}:deposit_conservation",
                    allocation.allocated_total + allocation.unallocated_deposit == selected_amount,
                    "allocated + unallocated == selected deposit "
                    f"({allocation.allocated_total} + {allocation.unallocated_deposit} "
                    f"!= {selected_amount})",
                )
            )
        checks.append(
            _check(
                name,
                "invariant",
                f"{deposit_id}:deposit_identity",
                allocation.deposit is not None and allocation.deposit.deposit_id == deposit_id,
                f"allocation deposit {allocation.deposit!r} does not match {deposit_id!r}",
            )
        )
        checks.append(
            _check(
                name,
                "invariant",
                f"{deposit_id}:allocation_deposit_present",
                allocation.deposit is not None,
                "allocation is missing its deposit record",
            )
        )

        legs = allocation.legs
        leg_ids.extend(leg.payment_id for leg in legs)
        checks.append(
            _check(
                name,
                "invariant",
                f"{deposit_id}:leg_uniqueness",
                len({leg.payment_id for leg in legs}) == len(legs),
                f"leg ids: {[leg.payment_id for leg in legs]!r}",
            )
        )
        checks.append(
            _check(
                name,
                "invariant",
                f"{deposit_id}:leg_totals",
                sum((leg.allocated for leg in legs), Decimal("0")) == allocation.allocated_total
                and sum((leg.fee for leg in legs), Decimal("0")) == allocation.fee_total
                and sum((leg.refund for leg in legs), Decimal("0")) == allocation.refund_total,
                "leg sums must equal allocation totals",
            )
        )
        checks.append(
            _check(
                name,
                "invariant",
                f"{deposit_id}:leg_caps",
                all(
                    leg.allocated <= leg.net and leg.net == leg.gross - leg.fee - leg.refund
                    for leg in legs
                ),
                "each leg allocated <= net and net == gross - fee - refund",
            )
        )
        checks.append(
            _check(
                name,
                "invariant",
                f"{deposit_id}:non_negative",
                allocation.open_balance >= 0 and allocation.unallocated_deposit >= 0,
                "open balance and unallocated deposit must be non-negative",
            )
        )

        if len(deposit.evidence) > 1:
            checks.append(
                _check(
                    name,
                    "invariant",
                    f"{deposit_id}:duplicate_single_result",
                    sum(1 for item in report.deposits if item.deposit_id == deposit_id) == 1,
                    "a duplicated statement line must yield exactly one allocation result",
                )
            )
            checks.append(
                _check(
                    name,
                    "invariant",
                    f"{deposit_id}:duplicate_not_double_allocated",
                    allocation.allocated_total <= max(item.amount for item in deposit.evidence),
                    "allocated total exceeds the largest duplicate amount",
                )
            )

        comparison = deposit.comparison
        if comparison is not None:
            checks.append(
                _check(
                    name,
                    "invariant",
                    f"{deposit_id}:derived_equation",
                    comparison.difference
                    == comparison.deposit_amount - comparison.invoice_net_total,
                    "derived difference must equal deposit - invoice total",
                )
            )
            checks.append(
                _check(
                    name,
                    "invariant",
                    f"{deposit_id}:derived_sorted",
                    tuple(sorted(comparison.invoice_ids)) == comparison.invoice_ids,
                    f"invoice ids: {comparison.invoice_ids!r}",
                )
            )

    checks.append(
        _check(
            name,
            "invariant",
            "no_leg_reused",
            len(leg_ids) == len(set(leg_ids)),
            f"a charge was allocated to more than one deposit: {sorted(leg_ids)!r}",
        )
    )

    line_numbers = {item.line_number for deposit in report.deposits for item in deposit.evidence}
    for group in (*report.duplicate_groups, *report.drift_groups):
        line_numbers.update(item.line_number for item in group)
    line_numbers.update(row[0] for row in report.rejects)
    accounts_lines = len(line_numbers) + report.skipped_debits
    checks.append(
        _check(
            name,
            "invariant",
            "statement_line_accounting",
            accounts_lines == len(case.get("bank", ())),
            f"accounted {accounts_lines} of {len(case.get('bank', ()))} statement lines",
        )
    )

    for index, row in enumerate(report.rejects):
        checks.append(
            _check(
                name,
                "invariant",
                f"reject_{index}",
                len(row) == 3 and isinstance(row[0], int),
                f"reject row is malformed: {row!r}",
            )
        )

    for link in report.links:
        checks.append(
            _check(
                name,
                "invariant",
                f"link_{link.invoice_id}",
                link.invoice_id != link.charge_id
                and link.difference == link.charge_net - link.invoice_net,
                "link difference must equal charge net - invoice net",
            )
        )

    money_strings = [status for status in _walk_money(report.to_dict())]
    checks.append(
        _check(
            name,
            "invariant",
            "money_scale",
            all(Decimal(value).as_tuple().exponent == -exponent for value in money_strings),
            f"every money value must use the fixture's {exponent}-digit scale",
        )
    )
    return checks


def _walk_money(payload: object) -> list[str]:
    """Collect decimal-looking strings from the JSON-safe report payload."""
    found: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str):
            body = node[1:] if node.startswith("-") else node
            if body.count(".") == 1 and body.replace(".", "").isdigit():
                integer, fraction = body.split(".")
                if integer and len(fraction) >= 2:
                    found.append(node)

    walk(payload)
    return found


def _scenario_limitations(
    name: str,
    case: Mapping[str, Any],
    report: ReconciliationReport,
) -> list[str]:
    """Name the reasons this scenario cannot be read as fully settled."""
    notes: list[str] = []
    if not case.get("bank"):
        notes.append(
            "No bank statement rows are present, so the bank leg is absent; "
            "the scenario is pending evidence, not reconciled."
        )
    for deposit in report.deposits:
        allocation = deposit.allocation
        if allocation.outcome is PayoutOutcome.PENDING_EVIDENCE:
            notes.append(
                f"{deposit.deposit_id}: no candidate charge matched the deposit; "
                "the money is unallocated, not lost."
            )
        if allocation.outcome is PayoutOutcome.REQUIRES_HUMAN:
            note = f"{deposit.deposit_id}: {len(allocation.candidates)} candidate allocations"
            notes.append(note + "; a human must choose one.")
        if allocation.outcome is PayoutOutcome.EXCEPTION and allocation.exception_code:
            notes.append(
                f"{deposit.deposit_id}: {allocation.exception_code.value} recorded for review; "
                "the deposit is not settled."
            )
    if report.drift_groups:
        notes.append(
            "A repeated statement line carried a different amount; the latest line was "
            "reconciled once with duplicate evidence and the difference stays visible."
        )
    if report.duplicate_groups:
        notes.append(
            "Exact duplicate statement lines were reported once and never allocated twice."
        )
    return notes


def _render_markdown(document: Mapping[str, Any]) -> str:
    """Render the operator report as deterministic Markdown."""
    fixture = document["fixture"]
    lines: list[str] = [
        "# Operator reconciliation report — three-source triangle",
        "",
        "Synthetic fixture only. No customer or production financial data is involved.",
        "",
        f"- Fixture: `{fixture['name']}` (version {fixture['version']})",
        f"- Cases sha256: `{fixture['cases_sha256']}`",
        f"- Expected sha256: `{fixture['expected_sha256']}`",
        f"- Operator expectation sha256: `{fixture['operator_expected_sha256']}`",
        f"- Command: `{fixture['command']}`",
        f"- Verdict: **{'PASS' if document['verdict'] == 'pass' else 'FAIL'}**",
        "",
        "## Summary",
        "",
        "| Scenario | Status | Outcome | Classification | Allocated | Open | "
        "Unallocated | Difference |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in document["scenarios"]:
        amounts = row["amounts"]
        classification = row["classification"]
        label = classification["exception_code"] or classification["reason"] or "—"
        lines.append(
            "| `{scenario}` | {status} | {outcome} | {label} | {allocated} | {open} | "
            "{unallocated} | {difference} |".format(
                scenario=row["scenario"],
                status=STATUS_LEGEND[row["status"]].split(" — ")[0],
                outcome=row["outcome"] or "—",
                label=label,
                allocated=amounts["allocated_total"],
                open=amounts["open_balance"],
                unallocated=amounts["unallocated_deposit"],
                difference=amounts["derived_difference"] or "—",
            )
        )
    lines.extend(
        [
            "",
            "Status meanings:",
            "",
        ]
    )
    for status in ("reconciled", "exception", "pending_evidence", "ambiguous"):
        lines.append(f"- **{status}** — {STATUS_LEGEND[status]}")

    for row in document["scenarios"]:
        amounts = row["amounts"]
        classification = row["classification"]
        lines.extend(
            [
                "",
                f"## `{row['scenario']}` — {STATUS_LEGEND[row['status']].split(' — ')[0]}",
                "",
                row["description"],
                "",
                "| Item | Value |",
                "|---|---|",
                f"| Invoice expected (net) | {amounts['invoice_expected_net']} |",
                f"| Processor evidence (net) | {amounts['processor_evidence_net']} |",
                f"| Bank deposit recorded | {amounts['deposit_recorded'] or 'none'} |",
                f"| Allocated | {amounts['allocated_total']} |",
                f"| Unallocated deposit | {amounts['unallocated_deposit']} |",
                f"| Fees | {amounts['fee_total']} |",
                f"| Refunds | {amounts['refund_total']} |",
                f"| Open balance | {amounts['open_balance']} |",
                f"| Derived difference (deposit − invoice) | "
                f"{amounts['derived_difference'] or 'not derivable'} |",
                f"| Outcome | {row['outcome'] or 'no deposit result'} |",
                f"| Classification | "
                f"{classification['exception_code'] or classification['reason'] or 'none'} |",
                "",
                "Evidence:",
                "",
            ]
        )
        for link in row["evidence"]["links"]:
            lines.append(
                f"- Invoice `{link['invoice_id']}` → charge `{link['charge_id']}`: "
                f"difference {link['difference']} ({link['outcome']}"
                f"{', ' + link['exception_code'] if link['exception_code'] else ''})"
            )
        for deposit in row["evidence"]["deposits"]:
            lines.append(
                f"- Deposit `{deposit['deposit_id']}` line {deposit['line_number']} "
                f"({deposit['statement_reference']}): {deposit['amount']}"
            )
        if row["evidence"]["candidates"]:
            for index, candidate in enumerate(row["evidence"]["candidates"], start=1):
                lines.append(
                    f"- Candidate {index}: " + ", ".join(f"`{item}`" for item in candidate)
                )
        for group in row["evidence"]["duplicate_groups"]:
            lines.append(
                "- Exact duplicate lines: "
                + ", ".join(f"line {item['line_number']} ({item['amount']})" for item in group)
            )
        for group in row["evidence"]["drift_groups"]:
            lines.append(
                "- Drifted duplicate lines: "
                + ", ".join(f"line {item['line_number']} ({item['amount']})" for item in group)
            )
        if row["limitations"]:
            lines.extend(["", "Limitations:", ""])
            lines.extend(f"- {note}" for note in row["limitations"])
        if row["warnings"]:
            lines.extend(["", "Warnings:", ""])
            lines.extend(f"- {warning}" for warning in row["warnings"])

    if document["notes"]:
        lines.extend(["", "## Documented surface notes", ""])
        lines.extend(f"- {note}" for note in document["notes"])

    lines.extend(
        [
            "",
            "## Verification",
            "",
            f"- Checks run: {document['checks']['total']}",
            f"- Passed: {document['checks']['passed']}",
            f"- Failed: {document['checks']['failed']}",
            "",
            "A failed check makes this run exit nonzero; no unresolved case is "
            "reported as settled.",
            "",
        ]
    )
    return "\n".join(lines)


def build_operator_run(
    cases_path: Path,
    expected_path: Path,
    *,
    pairwise_expected_path: Path | None = None,
    window_seconds: int | None = None,
    command: str | None = None,
) -> OperatorRun:
    """Run every fixture scenario and produce the operator evidence bundle."""
    cases_document, cases_digest = _read_json(cases_path)
    expected_document, operator_digest = _read_json(expected_path)
    pairwise_path = pairwise_expected_path or cases_path.with_name("expected.json")
    pairwise_document, pairwise_digest = _read_json(pairwise_path)

    if expected_document.get("surface") != "statement_workflow":
        raise InvariantViolation(
            "operator expectations must target the statement_workflow surface."
        )

    tenant_id = str(cases_document["tenant_id"])
    currency = str(cases_document["currency"])
    scenarios: Mapping[str, Any] = cases_document["scenarios"]
    expectations: Mapping[str, Any] = expected_document["scenarios"]
    pairwise_checks: Mapping[str, Any] = pairwise_document["checks"]

    if set(scenarios) != set(expectations):
        missing = sorted(set(scenarios) - set(expectations))
        extra = sorted(set(expectations) - set(scenarios))
        raise InvariantViolation(f"expectation table mismatch; missing={missing!r} extra={extra!r}")

    checks: list[CheckResult] = []
    rows: list[dict[str, Any]] = []
    tolerance = ReconciliationTolerance()

    for name in sorted(scenarios):
        case = scenarios[name]
        before = _input_snapshot(case)
        sources = sources_from_export(
            case,
            tenant_id=tenant_id,
            currency=currency,
            tolerance=tolerance,
            statement_digest=cases_digest,
            window_seconds=window_seconds,
        )
        report = run_statement_reconciliation(sources)
        replay = run_statement_reconciliation(sources)
        after = _input_snapshot(case)

        checks.append(
            _check(
                name,
                "safety",
                "input_immutability",
                before == after,
                "fixture scenario was mutated by the workflow",
            )
        )
        checks.append(
            _check(
                name,
                "safety",
                "deterministic_reprocessing",
                report.fingerprint == replay.fingerprint and report.to_dict() == replay.to_dict(),
                f"fingerprint {report.fingerprint} vs {replay.fingerprint}",
            )
        )
        checks.append(
            _check(
                name,
                "safety",
                "source_integrity",
                hashlib.sha256(cases_path.read_bytes()).hexdigest() == cases_digest,
                "fixture file changed during the run",
            )
        )

        row = _scenario_row(name, case, report, report.exponent)
        row["limitations"] = _scenario_limitations(name, case, report)
        rows.append(row)

        expected = expectations[name]
        checks.extend(_compare_expected(name, expected, row))
        cross_checks = expected.get("cross_check") or {}
        for edge in ("invoice_to_charge", "charge_to_deposit"):
            check_name = cross_checks.get(edge)
            if check_name:
                checks.extend(
                    _compare_cross_check(
                        name,
                        edge,
                        str(check_name),
                        pairwise_checks.get(str(check_name)),
                        row,
                    )
                )
        checks.extend(_invariants(name, sources, report, case, report.exponent))

    failures = [check for check in checks if not check.passed]
    document: dict[str, Any] = {
        "fixture": {
            "name": str(expected_document.get("fixture", "triangle")),
            "version": expected_document.get("version"),
            "tenant_id": tenant_id,
            "currency": currency,
            "cases_sha256": cases_digest,
            "expected_sha256": pairwise_digest,
            "operator_expected_sha256": operator_digest,
            "command": command or "python -m finance.reconciliation.operator_report",
        },
        "verdict": "fail" if failures else "pass",
        "notes": list(expected_document.get("notes", ())),
        "scenarios": rows,
        "checks": {
            "total": len(checks),
            "passed": len(checks) - len(failures),
            "failed": len(failures),
        },
        "failures": [
            {
                "scenario": check.scenario,
                "kind": check.kind,
                "name": check.name,
                "detail": check.detail,
            }
            for check in failures
        ],
    }
    return OperatorRun(document=document, markdown=_render_markdown(document), checks=tuple(checks))


def _write_atomic(path: Path, text: str) -> None:
    """Write deterministic UTF-8 text, creating the parent directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _evidence_record(
    run: OperatorRun,
    *,
    source_commit: str | None,
    module_digest: str,
    argv: Sequence[str],
    exit_code: int,
) -> dict[str, Any]:
    """Build the evidence record tying inputs, code, and outcome together."""
    document = run.document
    statuses: dict[str, int] = {}
    for row in document["scenarios"]:
        statuses[row["status"]] = statuses.get(row["status"], 0) + 1
    return {
        "source_commit": source_commit,
        "module_sha256": module_digest,
        "fixture": document["fixture"],
        "command": list(argv),
        "exit_code": exit_code,
        "verdict": document["verdict"],
        "checks": document["checks"],
        "scenario_statuses": dict(sorted(statuses.items())),
        "failures": document["failures"],
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run the operator evidence pass; return 0 only when everything passes."""
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--pairwise-expected", type=Path, default=None)
    parser.add_argument("--markdown", type=Path, default=None)
    parser.add_argument("--json", type=Path, dest="json_path", default=None)
    parser.add_argument("--evidence", type=Path, default=None)
    parser.add_argument("--source-commit", default=None)
    parser.add_argument("--window-seconds", type=int, default=None)
    args = parser.parse_args(raw_argv)

    invocation = ["python", "-m", "finance.reconciliation.operator_report", *raw_argv]
    command = shlex.join(invocation)
    run = build_operator_run(
        args.cases,
        args.expected,
        pairwise_expected_path=args.pairwise_expected,
        window_seconds=args.window_seconds,
        command=command,
    )

    rendered = json.dumps(run.document, indent=2, sort_keys=True)
    if args.markdown is not None:
        _write_atomic(args.markdown, run.markdown)
    if args.json_path is not None:
        _write_atomic(args.json_path, rendered + "\n")
    if args.markdown is None and args.json_path is None:
        sys.stdout.write(run.markdown)
    if args.evidence is not None:
        module_digest = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        record = _evidence_record(
            run,
            source_commit=args.source_commit,
            module_digest=module_digest,
            argv=invocation,
            exit_code=0 if run.passed else 1,
        )
        _write_atomic(args.evidence, json.dumps(record, indent=2, sort_keys=True) + "\n")

    if not run.passed:
        for failure in run.failures:
            sys.stderr.write(
                f"FAIL {failure.scenario} {failure.kind}/{failure.name}: {failure.detail}\n"
            )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
