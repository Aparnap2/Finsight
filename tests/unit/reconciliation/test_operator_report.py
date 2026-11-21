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
import shlex
from pathlib import Path
from typing import Any

import pytest

from finance.reconciliation import operator_report
from finance.reconciliation.operator_report import (
    OperatorInputError,
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
    assert record["operator_command"] == "python -m finance.reconciliation.operator_report"
    assert record["exit_code"] == 0
    assert record["verdict"] == "pass"
    assert record["scenario_statuses"] == {
        "ambiguous": 1,
        "exception": 1,
        "pending_evidence": 2,
        "reconciled": 5,
    }
    assert len(record["module_sha256"]) == 64
    assert record["command"][:3] == [
        "python",
        "-m",
        "finance.reconciliation.operator_report",
    ]
    assert record["command"][-2:] == ["--source-commit", "ebbe8d8"]
    document = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert document["fixture"]["command"] == shlex.join(record["command"])
    assert record["fixture"]["cases_sha256"] == hashlib.sha256(_CASES.read_bytes()).hexdigest()
    assert len(record["fixture"]["operator_expected_sha256"]) == 64


def test_missing_expectation_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(OperatorInputError, match="operator expectations not found"):
        build_operator_run(_CASES, tmp_path / "absent.json")


def test_default_build_records_the_documented_command() -> None:
    run = build_operator_run()
    assert run.passed is True
    assert run.document["fixture"]["command"] == (
        "python -m finance.reconciliation.operator_report"
    )


def test_default_invocation_prints_markdown(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# Operator reconciliation report")
    assert "Verdict: **PASS**" in out
    assert "python -m finance.reconciliation.operator_report" in out


def test_default_invocation_ignores_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main([]) == 0
    assert "Verdict: **PASS**" in capsys.readouterr().out


def test_missing_default_fixture_reports_an_incomplete_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(operator_report, "_DEFAULT_CASES", tmp_path / "absent.json")
    assert main([]) == 2
    err = capsys.readouterr().err
    assert "default cases fixture is missing" in err
    assert "checkout is incomplete" in err
    assert "absent.json" in err


def test_explicit_missing_fixture_never_falls_back(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "absent.json"
    assert main(["--cases", str(missing)]) == 2
    err = capsys.readouterr().err
    assert "cases fixture not found" in err
    assert str(missing) in err


def test_empty_fixture_fails_clearly(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    empty = tmp_path / "empty.json"
    empty.write_text("", encoding="utf-8")
    assert main(["--cases", str(empty)]) == 2
    assert "cases fixture is empty" in capsys.readouterr().err


def test_invalid_json_fails_clearly(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert main(["--cases", str(broken)]) == 2
    assert "is not valid JSON" in capsys.readouterr().err


def test_directory_instead_of_file_fails_clearly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--cases", str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "is a directory" in err
    assert str(tmp_path) in err


def test_empty_argument_fails_instead_of_reverting_to_default(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--cases", ""]) == 2
    assert "is a directory" in capsys.readouterr().err


def test_non_object_json_fails_clearly(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    array = tmp_path / "array.json"
    array.write_text("[1, 2, 3]", encoding="utf-8")
    assert main(["--cases", str(array)]) == 2
    assert "JSON object at the top level" in capsys.readouterr().err


def test_wrong_top_level_structure_fails_clearly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps({"scenarios": []}), encoding="utf-8")
    assert main(["--cases", str(wrong)]) == 2
    assert "must be a non-empty JSON object" in capsys.readouterr().err


def test_expected_override_is_honored(tmp_path: Path) -> None:
    override = tmp_path / "operator_expected.json"
    override.write_bytes(_EXPECTED.read_bytes())
    report = tmp_path / "report.json"
    assert main(["--expected", str(override), "--json", str(report)]) == 0
    document = json.loads(report.read_text(encoding="utf-8"))
    assert (
        document["fixture"]["operator_expected_sha256"]
        == hashlib.sha256(override.read_bytes()).hexdigest()
    )


def test_mixed_overrides_keep_the_other_defaults(tmp_path: Path) -> None:
    cases_override = tmp_path / "cases.json"
    cases_override.write_bytes(_CASES.read_bytes())
    report = tmp_path / "report.json"
    assert main(["--cases", str(cases_override), "--json", str(report)]) == 0
    document = json.loads(report.read_text(encoding="utf-8"))
    assert (
        document["fixture"]["cases_sha256"]
        == hashlib.sha256(cases_override.read_bytes()).hexdigest()
    )
    assert (
        document["fixture"]["operator_expected_sha256"]
        == hashlib.sha256(_EXPECTED.read_bytes()).hexdigest()
    )


def test_pairwise_override_is_honored(tmp_path: Path) -> None:
    override = tmp_path / "expected.json"
    override.write_bytes(_PAIRWISE.read_bytes())
    assert main(["--pairwise-expected", str(override)]) == 0


def test_difference_reasons_are_evidence_based() -> None:
    rows = _rows(_run())
    assert rows["s1_exact_match"]["difference_reason"] is None
    assert rows["s2_fee_explained"]["difference_reason"] == "Fee"
    assert rows["s3_many_to_one"]["difference_reason"] == "Fee"
    assert rows["s4a_refund_folded"]["difference_reason"] == "Refund + fee"
    assert rows["s6_duplicate"]["difference_reason"] == "Unexplained"
    assert rows["s7_ambiguous_allocation"]["difference_reason"] is None


def test_ambiguous_note_explains_the_open_value() -> None:
    row = _rows(_run())["s7_ambiguous_allocation"]
    text = " ".join(row["limitations"])
    assert "1940.00" in text
    assert "970.00" in text
    assert "not a liability" in text


def test_markdown_summary_carries_the_reason_column() -> None:
    markdown = _run().markdown
    assert (
        "| Scenario | Status | Outcome | Classification | Allocated | Open | "
        "Unallocated | Difference | Reason |" in markdown
    )
    assert (
        "| `s2_fee_explained` | Reconciled | MATCHED | — | 971.00 | 0.00 | 0.00 | -29.00 | Fee |"
        in markdown
    )
    assert "**open balance** — charge value that no deposit has matched yet" in markdown
