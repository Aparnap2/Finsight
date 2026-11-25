"""Deterministic E2E run verifier (CP6).

Consumes an :class:`E2ERunReport` and independently defined golden expected
values. Returns a verdict: VERIFIED / FAILED / INCOMPLETE. The viewer never
calculates or modifies this verdict.

Rules:
- Missing evidence never counts as passing.
- A failed or missing stage prevents VERIFIED.
- Expected vs actual mismatch → FAILED.
- Missing required fields → INCOMPLETE.
- Provider/trace evidence must be present for live staging runs.
"""

from __future__ import annotations

from typing import Any

from finance.verification.evidence import (
    E2ERunReport,
    RunVerdict,
    StageStatus,
)


def verify_run(report: E2ERunReport, golden: dict[str, Any] | None = None) -> RunVerdict:
    """Verify an E2E run report against golden expected values.

    Returns VERIFIED only if every required stage passed, every scenario
    matched its golden expected values, and all required evidence is present.
    """
    # 1. Required run-level fields.
    if not report.run_id or not report.commit_sha or not report.timestamp:
        return RunVerdict.INCOMPLETE

    # 2. All stages must have passed (no FAILED, no NOT_RUN for required stages).
    required_stages = {"import", "validate", "reconcile", "persist", "context", "investigate", "decide", "audit", "export"}
    stage_map = {s.stage.lower(): s for s in report.stages}
    for stage_name in required_stages:
        st = stage_map.get(stage_name)
        if st is None:
            return RunVerdict.INCOMPLETE
        if st.status in (StageStatus.FAILED, StageStatus.NOT_RUN, StageStatus.SKIPPED):
            # SKIPPED is allowed only for investigate when eligibility gates it
            if stage_name == "investigate" and st.status == StageStatus.SKIPPED:
                continue
            return RunVerdict.FAILED if st.status == StageStatus.FAILED else RunVerdict.INCOMPLETE

    # 3. Financial invariants must all be true.
    for _key, val in report.financial_invariants.items():
        if val is not True:
            return RunVerdict.FAILED

    # 4. Scenarios must match golden expected values.
    if golden is not None:
        golden_scenarios = golden.get("scenarios", {})
        for sr in report.scenarios:
            gs = golden_scenarios.get(sr.scenario_id)
            if gs is None:
                return RunVerdict.FAILED  # unknown scenario
            expected = gs.get("expected", {})
            # Check reconciliation expected values.
            exp_recon = expected.get("reconciliation", {})
            for key, exp_val in exp_recon.items():
                actual_val = sr.actual.get(key)
                if actual_val is None:
                    # Try from mismatches list
                    if key in sr.mismatches:
                        return RunVerdict.FAILED
                    # Missing actual for an expected key → incomplete
                    return RunVerdict.INCOMPLETE
                if str(actual_val) != str(exp_val):
                    return RunVerdict.FAILED
            # Mismatches list must be empty.
            if sr.mismatches:
                return RunVerdict.FAILED
            if sr.verdict != RunVerdict.VERIFIED:
                if sr.verdict == RunVerdict.FAILED:
                    return RunVerdict.FAILED
                return RunVerdict.INCOMPLETE

    # 5. Provider evidence required for live staging (environment != ci).
    if report.environment != "ci":
        if report.provider is None or not report.provider.request_id:
            return RunVerdict.INCOMPLETE
        if not report.provider.success:
            return RunVerdict.FAILED

    # 6. Trace evidence required for live staging.
    if report.environment != "ci":
        if report.trace is None or not report.trace.trace_id:
            return RunVerdict.INCOMPLETE
        if not report.trace.exported:
            return RunVerdict.INCOMPLETE

    # 7. Overall verdict must be VERIFIED.
    if report.overall_verdict != RunVerdict.VERIFIED:
        return report.overall_verdict

    return RunVerdict.VERIFIED
