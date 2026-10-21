"""Unit tests for scripts/test_accounting.py (APA-94 G1).

Contract:

- FAIL (exit 2) when the accounting report is missing, unreadable, or
  malformed — an unmeasured run cannot be certified.
- FAIL (exit 2) on a collection error — a module that failed to import is a
  broken suite, not a skip.
- FAIL (exit 2) when collected tests are unaccounted for — an unexplained
  omission.
- FAIL (exit 2) when a skip reason is not declared in the manifest.
- FAIL (exit 2) when a file the manifest expects was never collected.
- FAIL (exit 2) when more tests were deselected than the allowance.
- PASS (exit 0) when the split is fully explained, echoing the counts.

Scope note: the gate reads the accounting report produced by
``tests/accounting_plugin.py``; it does not see pytest's own exit status.
That complementary check belongs to the workflow's ``pipefail``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

GATE = Path(__file__).resolve().parents[3] / "scripts" / "test_accounting.py"

_REPORT: dict[str, Any] = {
    "collected": 10,
    "deselected": 0,
    "outcomes": {"passed": 9, "skipped": 1},
    "skipped_reasons": {
        "tests/a.py::test_env": "Skipped: integration database not usable",
    },
    "collection_errors": [],
    "collected_nodeids": [
        "tests/a.py::test_env",
        "tests/b.py::test_one",
        "tests/b.py::test_two",
    ],
    "executed_nodeids": ["tests/a.py::test_env", "tests/b.py::test_one"],
}

_MANIFEST: dict[str, Any] = {
    "skip_reasons": ["integration database not usable"],
    "expected_files": ["tests/b.py"],
    "deselect_allowance": 0,
}


def _write(tmp_path: Path, payload: dict[str, Any], name: str) -> Path:
    """Write a JSON payload and return its path."""
    path = tmp_path / name
    path.write_text(json.dumps(payload))
    return path


def _run(
    report: str,
    *args: str,
    tmp_path: Path,
) -> subprocess.CompletedProcess[str]:
    """Run the gate against a report file (isolated per test)."""
    return subprocess.run(
        [sys.executable, str(GATE), report, *args],
        capture_output=True,
        text=True,
        check=False,
    )


class TestAccountingGate:
    def test_healthy_run_passes(self, tmp_path: Path) -> None:
        report = _write(tmp_path, _REPORT, "accounting.json")
        manifest = _write(tmp_path, _MANIFEST, "manifest.json")
        proc = _run(str(report), "--manifest", str(manifest), tmp_path=tmp_path)
        assert proc.returncode == 0, proc.stdout
        assert "collected=10" in proc.stdout
        assert "executed=10" in proc.stdout

    def test_missing_report_fails(self, tmp_path: Path) -> None:
        proc = _run(str(tmp_path / "absent.json"), tmp_path=tmp_path)
        assert proc.returncode == 2
        assert "NO_REPORT" in proc.stdout

    def test_malformed_report_fails(self, tmp_path: Path) -> None:
        path = tmp_path / "accounting.json"
        path.write_text("{not json")
        proc = _run(str(path), tmp_path=tmp_path)
        assert proc.returncode == 2
        assert "NO_REPORT" in proc.stdout

    def test_collection_error_fails(self, tmp_path: Path) -> None:
        payload = dict(_REPORT)
        payload["collection_errors"] = ["tests/broken.py: ImportError: No module named 'x'"]
        report = _write(tmp_path, payload, "accounting.json")
        manifest = _write(tmp_path, _MANIFEST, "manifest.json")
        proc = _run(str(report), "--manifest", str(manifest), tmp_path=tmp_path)
        assert proc.returncode == 2
        assert "COLLECTION_ERROR" in proc.stdout

    def test_unexecuted_tests_fail(self, tmp_path: Path) -> None:
        payload = dict(_REPORT)
        # 12 collected but only 10 accounted for.
        payload["collected"] = 12
        report = _write(tmp_path, payload, "accounting.json")
        manifest = _write(tmp_path, _MANIFEST, "manifest.json")
        proc = _run(str(report), "--manifest", str(manifest), tmp_path=tmp_path)
        assert proc.returncode == 2
        assert "UNEXECUTED_TESTS" in proc.stdout

    def test_undeclared_skip_reason_fails(self, tmp_path: Path) -> None:
        payload = dict(_REPORT)
        payload["skipped_reasons"] = {"tests/a.py::test_env": "Skipped: brand new reason"}
        report = _write(tmp_path, payload, "accounting.json")
        manifest = _write(tmp_path, _MANIFEST, "manifest.json")
        proc = _run(str(report), "--manifest", str(manifest), tmp_path=tmp_path)
        assert proc.returncode == 2
        assert "UNDECLARED_SKIP" in proc.stdout

    def test_skip_without_reason_fails(self, tmp_path: Path) -> None:
        payload = dict(_REPORT)
        payload["skipped_reasons"] = {"tests/a.py::test_env": ""}
        report = _write(tmp_path, payload, "accounting.json")
        manifest = _write(tmp_path, _MANIFEST, "manifest.json")
        proc = _run(str(report), "--manifest", str(manifest), tmp_path=tmp_path)
        assert proc.returncode == 2
        assert "UNDECLARED_SKIP" in proc.stdout

    def test_missing_expected_file_fails(self, tmp_path: Path) -> None:
        manifest_payload = dict(_MANIFEST)
        manifest_payload["expected_files"] = ["tests/never_collected.py"]
        report = _write(tmp_path, _REPORT, "accounting.json")
        manifest = _write(tmp_path, manifest_payload, "manifest.json")
        proc = _run(str(report), "--manifest", str(manifest), tmp_path=tmp_path)
        assert proc.returncode == 2
        assert "UNDECLARED_FILE" in proc.stdout

    def test_deselect_budget_exceeded_fails(self, tmp_path: Path) -> None:
        payload = dict(_REPORT)
        payload["deselected"] = 5
        report = _write(tmp_path, payload, "accounting.json")
        manifest = _write(tmp_path, _MANIFEST, "manifest.json")
        proc = _run(str(report), "--manifest", str(manifest), tmp_path=tmp_path)
        assert proc.returncode == 2
        assert "DESELECT_BUDGET_EXCEEDED" in proc.stdout

    def test_multi_job_manifest_requires_job_selection(self, tmp_path: Path) -> None:
        manifest_payload = {"jobs": {"unit": _MANIFEST, "integration": _MANIFEST}}
        report = _write(tmp_path, _REPORT, "accounting.json")
        manifest = _write(tmp_path, manifest_payload, "manifest.json")
        proc = _run(str(report), "--manifest", str(manifest), tmp_path=tmp_path)
        assert proc.returncode == 2
        assert "--job" in proc.stdout

    def test_job_selection_evaluates_only_that_job(self, tmp_path: Path) -> None:
        manifest_payload = {
            "jobs": {
                "unit": _MANIFEST,
                "integration": {"skip_reasons": ["something else entirely"]},
            }
        }
        report = _write(tmp_path, _REPORT, "accounting.json")
        manifest = _write(tmp_path, manifest_payload, "manifest.json")
        proc = _run(str(report), "--manifest", str(manifest), "--job", "unit", tmp_path=tmp_path)
        assert proc.returncode == 0, proc.stdout

    def test_unknown_job_fails(self, tmp_path: Path) -> None:
        manifest_payload = {"jobs": {"unit": _MANIFEST}}
        report = _write(tmp_path, _REPORT, "accounting.json")
        manifest = _write(tmp_path, manifest_payload, "manifest.json")
        proc = _run(str(report), "--manifest", str(manifest), "--job", "nope", tmp_path=tmp_path)
        assert proc.returncode == 2
        assert "NO_REPORT" in proc.stdout

    def test_summary_is_written(self, tmp_path: Path) -> None:
        report = _write(tmp_path, _REPORT, "accounting.json")
        manifest = _write(tmp_path, _MANIFEST, "manifest.json")
        summary = tmp_path / "summary.json"
        proc = _run(
            str(report),
            "--manifest",
            str(manifest),
            "--summary",
            str(summary),
            tmp_path=tmp_path,
        )
        assert proc.returncode == 0, proc.stdout
        payload = json.loads(summary.read_text())
        assert payload["collected"] == 10
        assert payload["skipped"] == 1
        assert payload["passed"] == 9
