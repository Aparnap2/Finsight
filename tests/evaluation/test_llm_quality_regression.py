"""Deterministic LLM quality regression: golden suite over scripted outputs.

FakeLLM/Replay-style scripted outputs only — no network, no credentials, no
live calls. Quality scores measure output quality (extraction, reasoning,
contradiction handling, refusal, scope, grounding, calibration, injection
resistance) and NEVER gate execution; the ``agents/evaluation/harness``
verdict recorded per case is an observational safety floor only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.eval_support.llm_quality_runner import load_dataset, run_suite

GOLDEN_PATH = Path("tests/fixtures/eval_golden/llm_quality_golden.json")
REPO_ROOT = Path(".")
SAFETY_TASK_TYPES = frozenset({"refusal", "injection"})


def _report(tmp_path: Path) -> dict[str, Any]:
    """Run the suite and persist the regression report under tmp_path."""
    dataset = load_dataset(REPO_ROOT / GOLDEN_PATH)
    report = run_suite(dataset, repo_root=REPO_ROOT)
    out = tmp_path / "llm_quality_regression.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def _rows_by_case(report: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    """Index report rows as {case_id: {variant: row}}."""
    indexed: dict[str, dict[str, dict[str, Any]]] = {}
    for row in report["cases"]:
        indexed.setdefault(row["case_id"], {})[row["variant"]] = row
    return indexed


def test_report_schema(tmp_path: Path) -> None:
    """Assert the regression report carries all required keys."""
    report = _report(tmp_path)
    assert {"model", "provider", "provenance", "cases", "summary"} <= set(report)
    assert {"runner", "dataset", "dataset_cases"} <= set(report["provenance"])
    assert {"total", "passed", "failed", "mean_score"} <= set(report["summary"])
    required_row = {
        "case_id",
        "task_type",
        "variant",
        "typed_ok",
        "score",
        "threshold",
        "passed",
        "p7_ok",
        "safety_verdict",
        "fake_calls",
    }
    for row in report["cases"]:
        assert required_row <= set(row), f"row missing keys: {row['case_id']}"
        assert row["fake_calls"] == 1


def test_golden_suite_green_on_valid_outputs(tmp_path: Path) -> None:
    """Assert every scripted-valid output passes its quality bar."""
    report = _report(tmp_path)
    by_case = _rows_by_case(report)
    assert len(by_case) >= 12, "golden set must hold at least 12 cases"
    failures = [case_id for case_id, variants in by_case.items() if not variants["valid"]["passed"]]
    assert failures == [], f"valid variants must all pass: {failures}"


def test_degraded_variants_score_below_bar(tmp_path: Path) -> None:
    """Assert degraded outputs score below valid ones and FAIL their bars."""
    report = _report(tmp_path)
    by_case = _rows_by_case(report)
    for case_id, variants in by_case.items():
        valid = variants["valid"]
        degraded = variants["degraded"]
        assert degraded["score"] < valid["score"], f"{case_id}: bar does not bite"
        assert degraded["passed"] is False, f"{case_id}: degraded must fail its bar"


def test_quality_regression_never_alters_safety(tmp_path: Path) -> None:
    """Assert harness safety verdicts are unchanged on safety-relevant cases."""
    dataset = load_dataset(REPO_ROOT / GOLDEN_PATH)
    safety_ids = {c["id"] for c in dataset["cases"] if c["task_type"] in SAFETY_TASK_TYPES}
    assert len(safety_ids) >= 4, "need refusal + injection safety coverage"
    report = _report(tmp_path)
    by_case = _rows_by_case(report)
    for case_id in sorted(safety_ids):
        valid = by_case[case_id]["valid"]
        degraded = by_case[case_id]["degraded"]
        assert valid["safety_verdict"] in ("CONTAINED", "REJECTED")
        assert degraded["safety_verdict"] == valid["safety_verdict"]
        for refs in (valid["evidence_refs"], degraded["evidence_refs"]):
            assert "ev-forged-999" not in refs
            assert set(refs) <= {"ev-ledger-001"}


def test_injection_cases_reference_security_fixtures() -> None:
    """Assert injection cases reuse security payloads by reference (no copy)."""
    dataset = load_dataset(REPO_ROOT / GOLDEN_PATH)
    injection = [c for c in dataset["cases"] if c["task_type"] == "injection"]
    assert len(injection) >= 2
    for case in injection:
        ref = case.get("security_fixture_ref")
        assert ref is not None, f"{case['id']}: injection must reference a fixture"
        assert (REPO_ROOT / ref).exists(), f"{case['id']}: missing {ref}"
