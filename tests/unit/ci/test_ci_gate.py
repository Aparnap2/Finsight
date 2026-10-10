"""Unit tests for scripts/ci_gate.py (APA-80 R1).

Contract:

- FAIL (exit 2) when the log has no passing tests (zero passed or no
  summary line at all: collection error, empty run, stub echo).
- FAIL (exit 2) when skips exceed the per-job budget.
- PASS (exit 0) otherwise, echoing counts for the job summary.

Scope note: the gate reads a teed pytest log; it does NOT see pytest's
own process exit status. That complementary check belongs to the
workflow's `pipefail`, which propagates pytest failures (including
exit 5) before this gate ever runs.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

GATE = Path(__file__).resolve().parents[3] / "scripts" / "ci_gate.py"


def _run(log: str, *args: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    """Run the gate against an inline log file (isolated per test).

    ``tmp_path`` is required: there is no shared fallback path, so a
    future caller cannot reintroduce cross-test collisions.
    """
    path = tmp_path / "ci_gate_probe.log"
    path.write_text(log)
    return subprocess.run(
        [sys.executable, str(GATE), str(path), *args],
        capture_output=True,
        text=True,
        check=False,
    )


class TestCiGate:
    def test_healthy_run_passes(self, tmp_path: Path) -> None:
        proc = _run("174 passed, 5 warnings in 11.19s\n", tmp_path=tmp_path)
        assert proc.returncode == 0
        assert "passed=174" in proc.stdout

    def test_zero_passed_fails(self, tmp_path: Path) -> None:
        proc = _run("0 passed, 53 skipped in 2.01s\n", tmp_path=tmp_path)
        assert proc.returncode == 2
        assert "NO_PASSING_TESTS" in proc.stdout

    def test_all_skipped_fails(self, tmp_path: Path) -> None:
        proc = _run("53 skipped in 1.28s\n", tmp_path=tmp_path)
        assert proc.returncode == 2
        assert "NO_PASSING_TESTS" in proc.stdout

    def test_missing_summary_fails(self, tmp_path: Path) -> None:
        proc = _run(
            "collecting ...\nERROR tests/x.py::t - No module named 'boto3'\n",
            tmp_path=tmp_path,
        )
        assert proc.returncode == 2
        assert "NO_SUMMARY" in proc.stdout

    def test_empty_log_fails(self, tmp_path: Path) -> None:
        proc = _run("", tmp_path=tmp_path)
        assert proc.returncode == 2

    def test_over_budget_skips_fail(self, tmp_path: Path) -> None:
        proc = _run("100 passed, 11 skipped in 5s\n", "--max-skips", "10", tmp_path=tmp_path)
        assert proc.returncode == 2
        assert "SKIP_BUDGET_EXCEEDED" in proc.stdout

    def test_within_budget_passes_quietly(self, tmp_path: Path) -> None:
        proc = _run("100 passed, 10 skipped in 5s\n", "--max-skips", "10", tmp_path=tmp_path)
        assert proc.returncode == 0
        assert "SKIP_BUDGET_EXCEEDED" not in proc.stdout

    def test_failed_tests_are_not_the_gate_question(self, tmp_path: Path) -> None:
        # Failures already fail the pytest step itself (pipefail); the
        # gate must still report counts and pass through cleanly.
        proc = _run("1 failed, 173 passed, 5 warnings in 11.64s\n", tmp_path=tmp_path)
        assert proc.returncode == 0
        assert "passed=173" in proc.stdout
        assert "failed=1" in proc.stdout
