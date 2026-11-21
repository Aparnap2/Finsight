"""Emit the machine-readable reconciliation contract report.

The contract has three layers:

* the executable tests (``tests/unit/reconciliation/``) prove behaviour;
* the operator report (``finance.reconciliation.operator_report``) proves the
  frozen fixture still produces the recorded result;
* this script records *what was verified* for one commit in one environment:
  scenario id, expected versus actual status/outcome/code/amounts, invariant
  totals, commit SHA, and interpreter.

The output is deterministic apart from the environment fields, so two runs on
the same commit differ only in the interpreter block. It never imports the
engine: it runs the documented CLI as a subprocess into a temporary directory,
so the report describes what an operator would actually execute.

Usage::

    python scripts/reconciliation_contract_report.py               # print
    python scripts/reconciliation_contract_report.py --out report.json
    python scripts/reconciliation_contract_report.py --check       # exit 1 on drift

Exit codes: ``0`` verified, ``1`` the run failed or a scenario diverged,
``2`` the report could not be produced.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = Path("tests") / "fixtures" / "reconciliation" / "triangle"
FIXTURE_FILES = ("cases.json", "expected.json", "operator_expected.json")
OPERATOR_MODULE = "finance.reconciliation.operator_report"
_SCENARIO_FIELDS = ("status", "outcome", "allocated_total", "open_balance", "unallocated_deposit")


class ReportError(Exception):
    """Raised when the contract report cannot be produced."""


def _digest(path: Path) -> str:
    """Return the sha256 of a file, or an empty string when it is absent."""
    if not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _commit() -> str | None:
    """Return the checked-out commit, or ``None`` outside a git checkout."""
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    sha = completed.stdout.strip()
    return sha if completed.returncode == 0 and sha else None


def _read_object(path: Path) -> dict[str, Any]:
    """Read a JSON object, failing loudly on anything else."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReportError(f"cannot read {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReportError(f"{path} must contain a JSON object")
    return payload


def _run_operator(workdir: Path) -> int:
    """Run the documented operator command into ``workdir``; return its exit code."""
    argv = [
        sys.executable,
        "-m",
        OPERATOR_MODULE,
        "--markdown",
        str(workdir / "report.md"),
        "--json",
        str(workdir / "report.json"),
        "--evidence",
        str(workdir / "run.json"),
    ]
    try:
        completed = subprocess.run(
            argv, cwd=ROOT, capture_output=True, text=True, check=False, timeout=300
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ReportError(f"cannot run {OPERATOR_MODULE}: {exc}") from exc
    if completed.returncode not in (0, 1):
        raise ReportError(
            f"{OPERATOR_MODULE} exited {completed.returncode}: {completed.stderr.strip()[:400]}"
        )
    return completed.returncode


def _actual(report: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    """Index the operator report by scenario id."""
    scenarios = report.get("scenarios")
    if not isinstance(scenarios, list):
        raise ReportError("operator report has no scenario list")
    indexed: dict[str, Mapping[str, Any]] = {}
    for row in scenarios:
        if not isinstance(row, Mapping):
            raise ReportError("operator report scenario is not an object")
        scenario_id = row.get("scenario")
        if not isinstance(scenario_id, str):
            raise ReportError("operator report scenario has no id")
        indexed[scenario_id] = row
    return indexed


def _compare(
    scenario_id: str,
    expected: Mapping[str, Any],
    actual: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare one scenario's expected values with the operator report."""
    amounts = actual.get("amounts")
    amount_map: Mapping[str, Any] = amounts if isinstance(amounts, Mapping) else {}
    actual_values: dict[str, Any] = {
        "status": actual.get("status"),
        "outcome": actual.get("outcome"),
        "allocated_total": amount_map.get("allocated_total"),
        "open_balance": amount_map.get("open_balance"),
        "unallocated_deposit": amount_map.get("unallocated_deposit"),
    }
    classification = actual.get("classification")
    if isinstance(classification, Mapping):
        actual_values["exception_code"] = classification.get("exception_code")
    else:
        actual_values["exception_code"] = None

    fields: dict[str, Any] = {}
    not_compared: list[str] = []
    for name in _SCENARIO_FIELDS:
        if name not in expected:
            # A scenario with no deposit does not declare money fields; there
            # is nothing to compare, which is not a mismatch.
            not_compared.append(name)
            continue
        want = expected.get(name)
        got = actual_values.get(name)
        fields[name] = {"expected": want, "actual": got, "match": want == got}
    want_code = expected.get("exception_code")
    got_code = actual_values.get("exception_code")
    fields["exception_code"] = {
        "expected": want_code,
        "actual": got_code,
        "match": want_code == got_code,
    }
    return {
        "id": scenario_id,
        "match": all(field["match"] for field in fields.values()),
        "not_compared": not_compared,
        "fields": fields,
    }


def build_report() -> dict[str, Any]:
    """Run the operator command and assemble the contract record."""
    expectations_path = ROOT / FIXTURE_DIR / "operator_expected.json"
    expectations = _read_object(expectations_path)
    expected_rows = expectations.get("scenarios")
    if not isinstance(expected_rows, Mapping):
        raise ReportError(f"{expectations_path} has no scenario map")

    with tempfile.TemporaryDirectory(prefix="finsight-contract-") as raw:
        workdir = Path(raw)
        exit_code = _run_operator(workdir)
        report = _read_object(workdir / "report.json")
        evidence = _read_object(workdir / "run.json")

    evidence_verdict = evidence.get("verdict")
    evidence_exit = evidence.get("exit_code")
    actual_rows = _actual(report)
    expected_map: Mapping[str, Any] = expected_rows
    missing = sorted(set(expected_map) - set(actual_rows))
    unexpected = sorted(set(actual_rows) - set(expected_map))
    scenarios = [
        _compare(scenario_id, expected_map[scenario_id], actual_rows[scenario_id])
        for scenario_id in sorted(expected_map)
        if scenario_id in actual_rows
    ]

    checks = report.get("checks")
    check_map: Mapping[str, Any] = checks if isinstance(checks, Mapping) else {}
    failures = report.get("failures")
    failure_list = failures if isinstance(failures, list) else []

    verified = (
        exit_code == 0
        and evidence_verdict == "pass"
        and evidence_exit == exit_code
        and not missing
        and not unexpected
        and not failure_list
        and all(row["match"] for row in scenarios)
        and check_map.get("failed") == 0
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "commit": _commit(),
        "environment": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
        },
        "fixture": {
            "name": expectations.get("fixture"),
            "version": expectations.get("version"),
            "digests": {name: _digest(ROOT / FIXTURE_DIR / name) for name in FIXTURE_FILES},
        },
        "command": [f"python -m {OPERATOR_MODULE}"],
        "exit_code": exit_code,
        "evidence": {
            "verdict": evidence_verdict,
            "exit_code": evidence_exit,
            "module_sha256": evidence.get("module_sha256"),
            "scenario_statuses": evidence.get("scenario_statuses"),
        },
        "verdict": "pass" if verified else "fail",
        "checks": {
            "total": check_map.get("total"),
            "passed": check_map.get("passed"),
            "failed": check_map.get("failed"),
        },
        "scenarios": scenarios,
        "missing_scenarios": missing,
        "unexpected_scenarios": unexpected,
        "failures": failure_list,
    }


def _render(payload: Mapping[str, Any]) -> str:
    """Render the report deterministically."""
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _stable(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return the parts of a report that do not depend on commit or machine.

    ``--check`` compares this projection so a saved report can be re-verified
    on another machine or after a docs-only commit.
    """
    return {
        "schema_version": payload.get("schema_version"),
        "fixture": payload.get("fixture"),
        "exit_code": payload.get("exit_code"),
        "evidence": payload.get("evidence"),
        "verdict": payload.get("verdict"),
        "checks": payload.get("checks"),
        "scenarios": payload.get("scenarios"),
        "missing_scenarios": payload.get("missing_scenarios"),
        "unexpected_scenarios": payload.get("unexpected_scenarios"),
        "failures": payload.get("failures"),
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Print or write the contract report; return a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None, help="write the report to PATH")
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare with --out and exit 1 when the committed report drifted",
    )
    args = parser.parse_args(argv)

    try:
        payload = build_report()
    except ReportError as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return 2

    rendered = _render(payload)
    if args.out is not None:
        if args.check:
            if not args.out.exists():
                sys.stderr.write(f"ERROR: contract report missing: {args.out}\n")
                return 1
            try:
                committed = json.loads(args.out.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                sys.stderr.write(f"ERROR: cannot read {args.out}: {exc}\n")
                return 1
            if not isinstance(committed, dict):
                sys.stderr.write(f"ERROR: {args.out} is not a JSON object\n")
                return 1
            if _stable(committed) != _stable(payload):
                sys.stderr.write(f"ERROR: contract report drifted: {args.out}\n")
                return 1
        else:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(rendered, encoding="utf-8")
    elif args.check:
        sys.stderr.write("ERROR: --check requires --out\n")
        return 2
    else:
        sys.stdout.write(rendered)

    failed = [row["id"] for row in payload["scenarios"] if not row["match"]]
    if failed:
        sys.stderr.write(f"scenario mismatch: {', '.join(failed)}\n")
    sys.stderr.write(
        f"contract: {payload['verdict']} — {len(payload['scenarios'])} scenarios, "
        f"{payload['checks']['passed']}/{payload['checks']['total']} checks\n"
    )
    return 0 if payload["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
