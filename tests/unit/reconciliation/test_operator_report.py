"""Tests for the operator-facing three-source evidence run.

``finance.reconciliation.operator_report`` turns the composed workflow into an
operator-readable report and a deterministic, machine-checkable evidence pass.
These tests pin the four statuses, the independent conservation and
duplicate-safety invariants, determinism, input immutability, and the negative
control that makes an incorrect expectation fail loudly.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from finance.reconciliation.operator_report import (
    build_operator_run,
    main,
)

_FIXTURES = (
    Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "reconciliation" / "triangle"
)
_CASES = _FIXTURES / "cases.json"
_EXPECTED = _FIXTURES / "operator_expected.json"
_PAIRWISE = _FIXTURES / "expected.json"

_STATUS_BY_SCENARIO = {
    "s1_exact_match": "reconciled",
    "s2_fee_explained": "reconciled",
    "s3_many_to_one": "reconciled",
    "s4a_refund_folded": "reconciled",
    "s4b_partial_payment": "pending_evidence",
    "s5_delayed": "reconciled",
    "s5b_missing_deposit": "pending_evidence",
    "s6_duplicate": "exception",
    "s7_ambiguous_allocation": "ambiguous",
}


def _run() -> Any:
    return build_operator_run(_CASES, _EXPECTED, pairwise_expected_path=_PAIRWISE)


def _rows(run: Any) -> dict[str, Any]:
    return {row["scenario"]: row for row in run.document["scenarios"]}


def test_every_check_passes_on_the_frozen_fixture() -> None:
    run = _run()
    assert run.failures == ()
    assert run.passed is True
    assert run.document["verdict"] == "pass"


def test_report_covers_every_scenario_once_in_fixture_order() -> None:
    run = _run()
    document = run.document
    cases = json.loads(_CASES.read_text(encoding="utf-8"))
    assert [row["scenario"] for row in document["scenarios"]] == list(cases["scenarios"])
    assert len(document["scenarios"]) == 9


@pytest.mark.parametrize("scenario", sorted(_STATUS_BY_SCENARIO))
def test_scenario_status_matches_the_operator_legend(scenario: str) -> None:
    row = _rows(_run())[scenario]
    assert row["status"] == _STATUS_BY_SCENARIO[scenario]


def test_unresolved_scenarios_are_never_labelled_reconciled() -> None:
    rows = _rows(_run())
    assert rows["s4b_partial_payment"]["classification"]["reason"] == "NO_CANDIDATE"
    assert rows["s4b_partial_payment"]["amounts"]["unallocated_deposit"] == "600.00"
    assert rows["s5b_missing_deposit"]["classification"]["reason"] == "NO_DEPOSIT"
    assert rows["s5b_missing_deposit"]["deposit_results"] == 0
    assert rows["s6_duplicate"]["classification"]["exception_code"] == "I-DUPLICATE"
    assert rows["s6_duplicate"]["amounts"]["open_balance"] == "2.00"
    assert rows["s7_ambiguous_allocation"]["classification"]["reason"] == "AMBIGUOUS"
    assert rows["s7_ambiguous_allocation"]["evidence"]["candidates"] == [
        ["ch_3001", "ch_3002", "ch_3003"],
        ["ch_3004"],
    ]


def test_duplicate_and_drifted_rows_are_accounted_without_double_allocation() -> None:
    row = _rows(_run())["s6_duplicate"]
    assert row["amounts"]["allocated_total"] == "148.00"
    assert row["deposit_results"] == 1
    assert [entry["line_number"] for entry in row["evidence"]["deposits"]] == [2, 4]
    assert [
        [entry["line_number"] for entry in group] for group in row["evidence"]["duplicate_groups"]
    ] == [[2, 3]]
    assert [
        [entry["line_number"] for entry in group] for group in row["evidence"]["drift_groups"]
    ] == [[2, 4]]


def test_markdown_states_status_and_verdict_for_operators() -> None:
    run = _run()
    markdown = run.markdown
    for label in ("Reconciled", "Exception", "Pending evidence", "Ambiguous"):
        assert label in markdown
    assert "Verdict: **PASS**" in markdown
    assert "## `s7_ambiguous_allocation` — Ambiguous" in markdown
    assert "A failed check makes this run exit nonzero" in markdown


def test_report_is_byte_identical_across_runs() -> None:
    first = _run()
    second = _run()
    assert first.document == second.document
    assert first.markdown == second.markdown
    assert json.dumps(first.document, indent=2, sort_keys=True) == json.dumps(
        second.document, indent=2, sort_keys=True
    )


def test_inputs_are_not_mutated_by_the_run() -> None:
    before = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (_CASES, _EXPECTED, _PAIRWISE)
    }
    _run()
    after = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (_CASES, _EXPECTED, _PAIRWISE)
    }
    assert before == after


def test_negative_control_fails_when_an_expectation_is_wrong(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = json.loads(_EXPECTED.read_text(encoding="utf-8"))
    payload["scenarios"]["s6_duplicate"]["allocated_total"] = "149.00"
    mutated = tmp_path / "operator_expected.json"
    mutated.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    markdown = tmp_path / "report.md"
    report = tmp_path / "report.json"
    exit_code = main(
        [
            "--cases",
            str(_CASES),
            "--expected",
            str(mutated),
            "--pairwise-expected",
            str(_PAIRWISE),
            "--markdown",
            str(markdown),
            "--json",
            str(report),
        ]
    )

    assert exit_code == 1
    assert "Verdict: **FAIL**" in markdown.read_text(encoding="utf-8")
    checks = json.loads(report.read_text(encoding="utf-8"))["checks"]
    assert checks["failed"] >= 1
    assert "expected/allocated_total" in capsys.readouterr().err


def test_negative_control_fails_when_a_status_is_wrong(tmp_path: Path) -> None:
    payload = json.loads(_EXPECTED.read_text(encoding="utf-8"))
    payload["scenarios"]["s7_ambiguous_allocation"]["status"] = "reconciled"
    mutated = tmp_path / "operator_expected.json"
    mutated.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    run = build_operator_run(_CASES, mutated, pairwise_expected_path=_PAIRWISE)
    assert run.passed is False
    assert run.document["verdict"] == "fail"
    assert any("expected/status" in f"{check.kind}/{check.name}" for check in run.failures)


def test_evidence_record_binds_commit_inputs_and_outcome(tmp_path: Path) -> None:
    evidence = tmp_path / "run.json"
    exit_code = main(
        [
            "--cases",
            str(_CASES),
            "--expected",
            str(_EXPECTED),
            "--pairwise-expected",
            str(_PAIRWISE),
            "--json",
            str(tmp_path / "report.json"),
            "--evidence",
            str(evidence),
            "--source-commit",
            "ebbe8d8",
        ]
    )

    assert exit_code == 0
    record = json.loads(evidence.read_text(encoding="utf-8"))
    assert record["source_commit"] == "ebbe8d8"
    assert record["exit_code"] == 0
    assert record["verdict"] == "pass"
    assert record["scenario_statuses"] == {
        "ambiguous": 1,
        "exception": 1,
        "pending_evidence": 2,
        "reconciled": 5,
    }
    assert len(record["module_sha256"]) == 64
    assert record["fixture"]["cases_sha256"] == hashlib.sha256(_CASES.read_bytes()).hexdigest()
    assert len(record["fixture"]["operator_expected_sha256"]) == 64


def test_missing_expectation_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        build_operator_run(_CASES, tmp_path / "absent.json")
