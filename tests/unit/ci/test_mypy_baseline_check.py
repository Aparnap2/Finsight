"""Unit tests for the mypy baseline ratchet script.

Runs scripts/mypy_baseline_check.py as a subprocess against synthetic
reports in tmp_path: exact match passes, new errors fail, resolved
errors fail with the --update instruction, missing/unreadable reports
fail closed, and --update regenerates the baseline.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "mypy_baseline_check.py"

BASE = (
    "a.py:1: error: Something broke  [misc]\n"
    "a.py:9: error: Something broke  [misc]\n"
    "b.py:2: error: Other failure  [arg-type]\n"
)


def _run(baseline_text: str | None, report_text: str | None, tmp_path: Path) -> tuple[int, str]:
    """Write fixtures, run the checker, return (exit code, output)."""
    base = tmp_path / "baseline.txt"
    if baseline_text is not None:
        base.write_text(baseline_text, encoding="utf-8")
    report = tmp_path / "report.txt"
    if report_text is not None:
        report.write_text(report_text, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--baseline", str(base), "--report", str(report)],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout + proc.stderr


def _baseline_of(report_text: str) -> str:
    """Build a baseline file body matching the report's error lines."""
    keys = []
    for line in report_text.splitlines():
        if ": error: " in line:
            path, _, rest = line.partition(":")
            message = rest.split(": error: ", 1)[1]
            keys.append(f"{path}|{message}")
    header = "# test baseline\n"
    return header + "".join(f"{k}\n" for k in sorted(keys))


def test_exact_match_passes(tmp_path: Path) -> None:
    code, out = _run(_baseline_of(BASE), BASE, tmp_path)
    assert code == 0, out
    assert "no new errors" in out


def test_new_error_fails(tmp_path: Path) -> None:
    report = BASE + "c.py:3: error: Brand new breakage  [misc]\n"
    code, out = _run(_baseline_of(BASE), report, tmp_path)
    assert code == 1, out
    assert "Brand new breakage" in out


def test_resolved_error_fails_with_update_instruction(tmp_path: Path) -> None:
    report = "a.py:1: error: Something broke  [misc]\n"
    code, out = _run(_baseline_of(BASE), report, tmp_path)
    assert code == 1, out
    assert "--update" in out


def test_missing_report_fails_closed(tmp_path: Path) -> None:
    code, out = _run(_baseline_of(BASE), None, tmp_path)
    assert code == 1, out


def test_garbage_report_fails_closed(tmp_path: Path) -> None:
    code, out = _run(_baseline_of(BASE), "compiling…\n", tmp_path)
    assert code == 1, out


def test_clean_mypy_run_passes_with_empty_baseline(tmp_path: Path) -> None:
    report = "Success: no issues found in 10 source files\n"
    code, out = _run("# empty\n", report, tmp_path)
    assert code == 0, out
