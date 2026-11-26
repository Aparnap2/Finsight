"""Golden-dataset reproducibility test for the committed operator evidence.

``docs/evidence/operator-run/`` is the frozen demonstration of the three-source
workflow. Before this test, the only way to check that the committed artifacts
still matched the code was to regenerate them by hand and eyeball the diff.

This test re-runs the documented command with the same relative output paths in
a temporary working directory and asserts all three artifacts are byte-identical
to the committed ones. Any drift in classification, allocation, rendering, or
evidence shape therefore fails here before it reaches the evidence bundle.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from finance.reconciliation import operator_report

_REPO_ROOT = Path(__file__).resolve().parents[3]
_EVIDENCE_DIR = Path("docs") / "evidence" / "operator-run"
_ARTIFACTS = ("report.md", "report.json", "run.json")


def _regenerate(workdir: Path, source_commit: str) -> None:
    """Run the documented CLI into ``workdir`` with the committed argv."""
    argv = [
        "--markdown",
        str(_EVIDENCE_DIR / "report.md"),
        "--json",
        str(_EVIDENCE_DIR / "report.json"),
        "--evidence",
        str(_EVIDENCE_DIR / "run.json"),
        "--source-commit",
        source_commit,
    ]
    assert operator_report.main(argv) == 0


def _committed_record() -> dict[str, object]:
    payload = json.loads((_REPO_ROOT / _EVIDENCE_DIR / "run.json").read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_committed_evidence_is_byte_reproducible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fresh run must reproduce the committed bundle exactly."""
    record = _committed_record()
    assert record["exit_code"] == 0
    assert record["verdict"] == "pass"
    source_commit = str(record["source_commit"])

    monkeypatch.chdir(tmp_path)
    _regenerate(tmp_path, source_commit)

    for name in _ARTIFACTS:
        regenerated = (tmp_path / _EVIDENCE_DIR / name).read_bytes()
        committed = (_REPO_ROOT / _EVIDENCE_DIR / name).read_bytes()
        assert regenerated == committed, (
            f"{name} drifted from the committed evidence. Regenerate the bundle "
            "(`python -m finance.reconciliation.operator_report` with the documented "
            "paths) and explain the diff in the commit message."
        )


def test_two_runs_produce_identical_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The bundle must not depend on run order, cwd, or wall-clock state."""
    source_commit = str(_committed_record()["source_commit"])
    outputs: list[dict[str, bytes]] = []

    for attempt in ("first", "second"):
        workdir = tmp_path / attempt
        workdir.mkdir()
        monkeypatch.chdir(workdir)
        _regenerate(workdir, source_commit)
        outputs.append({name: (workdir / _EVIDENCE_DIR / name).read_bytes() for name in _ARTIFACTS})

    assert outputs[0] == outputs[1]
