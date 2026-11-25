#!/usr/bin/env python
"""CP5 — measured efficiency comparison: prior flow vs. prepared-context flow.

Measurement-only. No metrics stack, no new dependencies. Reproducible:
run with ``python scripts/cp5_benchmark.py`` and inspect
``docs/evidence/cp5/report.json`` + ``report.md``.

Method:
- Four representative cases: eligible, incomplete-evidence, integrity-failure,
  duplicate/review.
- Old (prior) flow: build an InvestigationContext from exception fields and
  call BoundedInvestigation.investigate(context) with NO diagnostic and NO
  eligibility gate. Every case reaches the LLM.
- New (prepared) flow: build an ExceptionDiagnostic, run determine_eligibility;
  only ELIGIBLE cases call investigate(context, diagnostic=...). Others are
  gated (no LLM call).
- A counting FakeLLM records generate_structured calls and prompt chars.
- Token estimate = prompt_chars // 4 (standard ~4 chars/token approximation).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from finance.reconciliation.context import (  # noqa: E402
    ExceptionContext,
    ExceptionDiagnostic,
    RuleResult,
    RuleStatus,
)
from finance.reconciliation.diagnostics import determine_eligibility  # noqa: E402
from finance.reconciliation.investigation import (  # noqa: E402
    BoundedInvestigation,
    InvestigationContext,
)
from shared.llm.fake import FakeLLM  # noqa: E402

OUT_DIR = REPO_ROOT / "docs" / "evidence" / "cp5"


def _make_context(
    evidence_refs: list[str],
    *,
    match_summary: str = "INV-1 vs ch_1: 1000.00 vs 1000.00",
    allocation_summary: str = "dep_1: allocated 971.00",
) -> InvestigationContext:
    return InvestigationContext(
        exception_id="exc-1",
        exception_code="I-FEE-DRIFT",
        title="Fee mismatch",
        description="Stripe fee 29.00 but bank shows 0.00",
        evidence_refs=evidence_refs,
        match_summary=match_summary,
        allocation_summary=allocation_summary,
    )


def _make_exception_context(evidence_refs: list[str]) -> ExceptionContext:
    return ExceptionContext(
        exception_id="exc-1",
        exception_code="I-FEE-DRIFT",
        severity="HIGH",
        title="Fee mismatch",
        description="Stripe fee 29.00 but bank shows 0.00",
        currency="USD",
        expected_net="971.00",
        actual_deposit="960.00",
        variance="11.00",
        tolerance="5.00",
        calculations={
            "captured": "1000.00",
            "fees": "29.00",
            "refunds": "0.00",
            "adjustments": "0.00",
        },
        evidence_refs=evidence_refs,
        evidence=[{"type": "stripe_transaction", "record_id": "ch_1"}] if evidence_refs else [],
        investigation_eligible=bool(evidence_refs),
    )


def _make_diagnostic(
    *,
    evidence_refs: list[str],
    rule_results: list[RuleResult],
) -> ExceptionDiagnostic:
    ctx = _make_exception_context(evidence_refs)
    return ExceptionDiagnostic(
        run_id="run-1",
        exception_id="exc-1",
        tenant_id="t-1",
        snapshot_id="snap-1",
        engine_version="1.0.0",
        context=ctx,
        rule_results=rule_results,
        query_count=4,
    )


CASES: list[dict[str, Any]] = [
    {
        "name": "eligible_fee_discrepancy",
        "evidence_refs": ["evt_1", "dep_1"],
        "expected_eligibility": "ELIGIBLE",
        "expected_abstained": False,
        "rule_results": [
            RuleResult(rule_id="EVIDENCE_COMPLETENESS", status=RuleStatus.PASS),
            RuleResult(rule_id="RUN_MATCH_INTEGRITY", status=RuleStatus.PASS),
            RuleResult(rule_id="CALCULATION_CONSISTENCY", status=RuleStatus.PASS),
            RuleResult(rule_id="DUPLICATE_DETECTION", status=RuleStatus.PASS),
            RuleResult(rule_id="PAYOUT_VARIANCE", status=RuleStatus.FAIL),
        ],
    },
    {
        "name": "incomplete_evidence",
        "evidence_refs": [],
        "expected_eligibility": "INELIGIBLE",
        "expected_abstained": True,
        "rule_results": [
            RuleResult(rule_id="EVIDENCE_COMPLETENESS", status=RuleStatus.FAIL),
            RuleResult(rule_id="RUN_MATCH_INTEGRITY", status=RuleStatus.NOT_APPLICABLE),
            RuleResult(rule_id="CALCULATION_CONSISTENCY", status=RuleStatus.NOT_APPLICABLE),
            RuleResult(rule_id="DUPLICATE_DETECTION", status=RuleStatus.PASS),
        ],
    },
    {
        "name": "integrity_failure",
        "evidence_refs": ["evt_1", "dep_1"],
        "expected_eligibility": "BLOCKED",
        "expected_abstained": True,
        "rule_results": [
            RuleResult(rule_id="EVIDENCE_COMPLETENESS", status=RuleStatus.PASS),
            RuleResult(rule_id="RUN_MATCH_INTEGRITY", status=RuleStatus.PASS),
            RuleResult(rule_id="CALCULATION_CONSISTENCY", status=RuleStatus.FAIL),
            RuleResult(rule_id="DUPLICATE_DETECTION", status=RuleStatus.PASS),
        ],
    },
    {
        "name": "duplicate_review",
        "evidence_refs": ["evt_1", "dep_1"],
        "expected_eligibility": "REVIEW_REQUIRED",
        "expected_abstained": False,
        "rule_results": [
            RuleResult(rule_id="EVIDENCE_COMPLETENESS", status=RuleStatus.PASS),
            RuleResult(rule_id="RUN_MATCH_INTEGRITY", status=RuleStatus.PASS),
            RuleResult(rule_id="CALCULATION_CONSISTENCY", status=RuleStatus.PASS),
            RuleResult(rule_id="DUPLICATE_DETECTION", status=RuleStatus.FAIL),
        ],
    },
]

SCRIPTED_FINDING = {
    "InvestigationFinding": {
        "claim": "Fee discrepancy due to timing.",
        "evidence_refs": ["evt_1", "dep_1"],
        "confidence": "medium",
        "abstained": False,
    }
}


def run_case(case: dict[str, Any]) -> dict[str, Any]:
    evidence_refs = case["evidence_refs"]
    inv_context = _make_context(evidence_refs)
    diagnostic = _make_diagnostic(evidence_refs=evidence_refs, rule_results=case["rule_results"])
    eligibility = determine_eligibility(diagnostic)

    # Old flow: no gate, no diagnostic. Every case reaches the LLM.
    old_provider = FakeLLM(scripted=SCRIPTED_FINDING, model="fake-old")
    old_inv = BoundedInvestigation(old_provider)
    old_start = time.perf_counter()
    old_finding = old_inv.investigate(inv_context)
    old_latency_ms = (time.perf_counter() - old_start) * 1000.0
    old_calls = len(old_provider.journal)
    old_prompt_chars = sum(j.input_chars for j in old_provider.journal)
    old_evidence_refs = list(old_finding.evidence_refs or [])

    # New flow: gate first.
    new_provider = FakeLLM(scripted=SCRIPTED_FINDING, model="fake-new")
    new_inv = BoundedInvestigation(new_provider)
    gated = eligibility.status.value in ("INELIGIBLE", "BLOCKED")
    new_start = time.perf_counter()
    if gated:
        new_finding = None
        new_calls = 0
        new_prompt_chars = 0
    else:
        new_finding = new_inv.investigate(inv_context, diagnostic=diagnostic)
        new_calls = len(new_provider.journal)
        new_prompt_chars = sum(j.input_chars for j in new_provider.journal)
    new_latency_ms = (time.perf_counter() - new_start) * 1000.0

    # Correctness: evidence refs must be subset of supplied evidence (no hallucination).
    supplied = set(evidence_refs)
    old_ok = set(old_evidence_refs).issubset(supplied) if old_evidence_refs else True
    new_ok = (
        set(new_finding.evidence_refs).issubset(supplied)
        if (new_finding is not None and new_finding.evidence_refs)
        else True
    )

    return {
        "case": case["name"],
        "expected_eligibility": case["expected_eligibility"],
        "actual_eligibility": eligibility.status.value,
        "eligibility_match": eligibility.status.value == case["expected_eligibility"],
        "old_flow": {
            "llm_calls": old_calls,
            "tool_calls": 0,
            "prompt_chars": old_prompt_chars,
            "prompt_tokens_est": old_prompt_chars // 4,
            "latency_ms": round(old_latency_ms, 3),
            "abstained": old_finding.abstained,
            "confidence": old_finding.confidence,
            "evidence_refs": old_evidence_refs,
            "evidence_subset_ok": old_ok,
            "gated": False,
        },
        "new_flow": {
            "llm_calls": new_calls,
            "tool_calls": 0,
            "prompt_chars": new_prompt_chars,
            "prompt_tokens_est": new_prompt_chars // 4,
            "latency_ms": round(new_latency_ms, 3),
            "abstained": (new_finding.abstained if new_finding else None),
            "confidence": (new_finding.confidence if new_finding else None),
            "evidence_refs": (list(new_finding.evidence_refs) if new_finding else []),
            "evidence_subset_ok": new_ok,
            "gated": gated,
        },
        "delta_llm_calls": new_calls - old_calls,
        "delta_prompt_tokens_est": (new_prompt_chars // 4) - (old_prompt_chars // 4),
    }


def main() -> None:
    results = [run_case(c) for c in CASES]

    # Aggregate.
    old_total_calls = sum(r["old_flow"]["llm_calls"] for r in results)
    new_total_calls = sum(r["new_flow"]["llm_calls"] for r in results)
    gated_count = sum(1 for r in results if r["new_flow"]["gated"])

    report = {
        "schema_version": "1.0",
        "benchmark": "cp5_context_preparation_efficiency",
        "method": "in-memory representative cases; FakeLLM scripted provider; "
        "token estimate = prompt_chars // 4",
        "baseline_note": "Old flow = pre-CP4 route pattern (no diagnostic, no "
        "eligibility gate). Reproduced locally from the pre-CP4 "
        "code pattern; not from a captured historical run.",
        "cases": results,
        "aggregate": {
            "cases_total": len(results),
            "old_total_llm_calls": old_total_calls,
            "new_total_llm_calls": new_total_calls,
            "llm_calls_saved": old_total_calls - new_total_calls,
            "gated_cases": gated_count,
            "all_eligibility_match": all(r["eligibility_match"] for r in results),
            "all_evidence_subset_ok_old": all(r["old_flow"]["evidence_subset_ok"] for r in results),
            "all_evidence_subset_ok_new": all(
                r["new_flow"]["evidence_subset_ok"] for r in results if not r["new_flow"]["gated"]
            ),
        },
        "honesty_note": "Both flows use a single generate_structured call "
        "(BoundedInvestigation is single-call). The prepared-context "
        "gain is NOT a reduction in LLM call count within the "
        "investigator; it is (a) gating ineligible/blocked cases "
        "before any LLM call, (b) richer evidence in the prompt, "
        "and (c) eliminating external context-gathering. Tool calls "
        "are 0 in both flows because the investigator does not use "
        "tools. No metrics stack was added.",
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    # Markdown summary.
    lines = [
        "# CP5 — Measured Efficiency: Prior Flow vs. Prepared-Context Flow",
        "",
        f"Cases: {len(results)}. Old total LLM calls: {old_total_calls}. "
        f"New total LLM calls: {new_total_calls}. Gated (no LLM call): {gated_count}.",
        "",
        "| Case | Eligibility | Old | New | Old tok | New tok | Gated |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r['case']} | {r['actual_eligibility']} | "
            f"{r['old_flow']['llm_calls']} | {r['new_flow']['llm_calls']} | "
            f"{r['old_flow']['prompt_tokens_est']} | {r['new_flow']['prompt_tokens_est']} | "
            f"{'yes' if r['new_flow']['gated'] else 'no'} |"
        )
    lines += [
        "",
        "## Honesty note",
        report["honesty_note"],
        "",
        "## Baseline limitation",
        "Old flow reproduced from the pre-CP4 code pattern (InvestigationContext "
        "built from exception row, no diagnostic, no gate). No captured historical "
        "run exists; baseline is a faithful local reproduction, not a measured "
        "production observation.",
    ]
    (OUT_DIR / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(report["aggregate"], indent=2))


if __name__ == "__main__":
    main()
