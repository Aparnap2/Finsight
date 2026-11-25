"""Unit tests for the E2E run verifier (CP6)."""

from __future__ import annotations

from finance.verification.evidence import (
    E2ERunReport,
    ProviderEvidence,
    RunVerdict,
    ScenarioResult,
    StageEvidence,
    StageStatus,
    TraceEvidence,
)
from finance.verification.verifier import verify_run


def _stage(name: str, status: StageStatus = StageStatus.PASSED) -> StageEvidence:
    return StageEvidence(stage=name, status=status)


def _all_stages() -> list[StageEvidence]:
    names = [
        "import",
        "validate",
        "reconcile",
        "persist",
        "context",
        "investigate",
        "decide",
        "audit",
        "export",
    ]
    return [_stage(n) for n in names]


def _report(**overrides: object) -> E2ERunReport:
    base: dict[str, object] = {
        "run_id": "run-1",
        "commit_sha": "abc123",
        "timestamp": "2026-01-01T00:00:00Z",
        "environment": "ci",
        "overall_verdict": RunVerdict.VERIFIED,
        "stages": _all_stages(),
        "scenarios": [],
        "financial_invariants": {"allocation_balanced": True},
    }
    base.update(overrides)
    return E2ERunReport(**base)  # type: ignore[arg-type]


GOLDEN = {
    "scenarios": {
        "fee_discrepancy": {
            "expected": {
                "reconciliation": {
                    "match_count": 2,
                    "exception_count": 3,
                    "allocated_total": "1461.00",
                }
            }
        }
    }
}


class TestVerifier:
    def test_verified_when_all_pass(self) -> None:
        report = _report(
            scenarios=[
                ScenarioResult(
                    scenario_id="fee_discrepancy",
                    verdict=RunVerdict.VERIFIED,
                    actual={"match_count": 2, "exception_count": 3, "allocated_total": "1461.00"},
                )
            ]
        )
        assert verify_run(report, GOLDEN) == RunVerdict.VERIFIED

    def test_failed_on_stage_failure(self) -> None:
        stages = _all_stages()
        stages[2] = _stage("reconcile", StageStatus.FAILED)
        report = _report(stages=stages)
        assert verify_run(report, GOLDEN) == RunVerdict.FAILED

    def test_incomplete_on_missing_stage(self) -> None:
        stages = _all_stages()[:-1]  # missing export
        report = _report(stages=stages)
        assert verify_run(report, GOLDEN) == RunVerdict.INCOMPLETE

    def test_failed_on_mismatch(self) -> None:
        report = _report(
            scenarios=[
                ScenarioResult(
                    scenario_id="fee_discrepancy",
                    verdict=RunVerdict.VERIFIED,
                    actual={"match_count": 2, "exception_count": 3, "allocated_total": "999.00"},
                    mismatches=[],
                )
            ]
        )
        assert verify_run(report, GOLDEN) == RunVerdict.FAILED

    def test_failed_on_mismatches_list(self) -> None:
        report = _report(
            scenarios=[
                ScenarioResult(
                    scenario_id="fee_discrepancy",
                    verdict=RunVerdict.VERIFIED,
                    actual={"match_count": 2, "exception_count": 3, "allocated_total": "1461.00"},
                    mismatches=["fee_total mismatch"],
                )
            ]
        )
        assert verify_run(report, GOLDEN) == RunVerdict.FAILED

    def test_incomplete_on_missing_run_id(self) -> None:
        report = _report(run_id="")
        assert verify_run(report, GOLDEN) == RunVerdict.INCOMPLETE

    def test_incomplete_on_missing_actual(self) -> None:
        report = _report(
            scenarios=[
                ScenarioResult(
                    scenario_id="fee_discrepancy",
                    verdict=RunVerdict.VERIFIED,
                    actual={},  # missing expected keys
                )
            ]
        )
        assert verify_run(report, GOLDEN) == RunVerdict.INCOMPLETE

    def test_failed_on_false_invariant(self) -> None:
        report = _report(financial_invariants={"allocation_balanced": False})
        assert verify_run(report, GOLDEN) == RunVerdict.FAILED

    def test_incomplete_on_missing_provider_in_staging(self) -> None:
        report = _report(
            environment="staging",
            provider=None,
        )
        assert verify_run(report, GOLDEN) == RunVerdict.INCOMPLETE

    def test_failed_on_provider_failure_in_staging(self) -> None:
        report = _report(
            environment="staging",
            provider=ProviderEvidence(
                provider_name="groq", model="m", request_id="r1", success=False
            ),
            trace=TraceEvidence(trace_id="t1", exported=True),
        )
        assert verify_run(report, GOLDEN) == RunVerdict.FAILED

    def test_incomplete_on_missing_trace_in_staging(self) -> None:
        report = _report(
            environment="staging",
            provider=ProviderEvidence(
                provider_name="groq", model="m", request_id="r1", success=True
            ),
            trace=None,
        )
        assert verify_run(report, GOLDEN) == RunVerdict.INCOMPLETE

    def test_incomplete_on_unexported_trace_in_staging(self) -> None:
        report = _report(
            environment="staging",
            provider=ProviderEvidence(
                provider_name="groq", model="m", request_id="r1", success=True
            ),
            trace=TraceEvidence(trace_id="t1", exported=False),
        )
        assert verify_run(report, GOLDEN) == RunVerdict.INCOMPLETE

    def test_staging_verified_with_full_evidence(self) -> None:
        report = _report(
            environment="staging",
            provider=ProviderEvidence(
                provider_name="groq", model="m", request_id="r1", success=True
            ),
            trace=TraceEvidence(trace_id="t1", exported=True),
            scenarios=[
                ScenarioResult(
                    scenario_id="fee_discrepancy",
                    verdict=RunVerdict.VERIFIED,
                    actual={"match_count": 2, "exception_count": 3, "allocated_total": "1461.00"},
                )
            ],
        )
        assert verify_run(report, GOLDEN) == RunVerdict.VERIFIED

    def test_failed_on_unknown_scenario(self) -> None:
        report = _report(
            scenarios=[
                ScenarioResult(
                    scenario_id="nonexistent_scenario",
                    verdict=RunVerdict.VERIFIED,
                    actual={"match_count": 1},
                )
            ]
        )
        assert verify_run(report, GOLDEN) == RunVerdict.FAILED

    def test_skipped_investigate_allowed_for_gated_case(self) -> None:
        stages = _all_stages()
        stages[5] = _stage("investigate", StageStatus.SKIPPED)  # gated case
        report = _report(stages=stages, scenarios=[])
        # No golden scenarios to check; all stages pass except skipped investigate (allowed)
        assert verify_run(report, GOLDEN) == RunVerdict.VERIFIED

    def test_overall_verdict_not_verified_fails(self) -> None:
        report = _report(overall_verdict=RunVerdict.FAILED)
        assert verify_run(report, GOLDEN) == RunVerdict.FAILED
