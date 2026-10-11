"""Workflow supply-chain lock-in (APA-85/R6): SHA pinning + least privilege.

Fails on floating action refs and on jobs without an explicit
permissions block. Helpers are pure functions over workflow text and
covered by negative fixtures, so the guard cannot be bypassed by file
renames (``*.yaml`` included) or malformed references. No network.
"""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[3] / ".github" / "workflows"

# Path segments must not start/end with a dot and must not be ./.. :
# rejects ../repo@sha, owner/..@sha, .hidden/repo@sha.
_SEGMENT = r"(?:[A-Za-z0-9_-](?:[A-Za-z0-9_.-]*[A-Za-z0-9_-])?)"
_PINNED_USES = re.compile(rf"^{_SEGMENT}/{_SEGMENT}@[0-9a-f]{{40}}(?:\s+#\s*\S+)?\s*$")


_USES_LINE = re.compile(r"uses\s*:\s*(.+?)\s*$")


def _strip_comment(line: str) -> str:
    """Remove a trailing # comment (job headers never contain # otherwise)."""
    cut = line.find(" #")
    return line[:cut] if cut != -1 else line


def _unpinned_refs(text: str) -> list[str]:
    """Return non-SHA-pinned uses: refs found in workflow text."""
    offenders: list[str] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        match = _USES_LINE.search(_strip_comment(line))
        if not match:
            continue
        ref = match.group(1).strip()
        if not _PINNED_USES.match(ref):
            offenders.append(f"{lineno}:{ref}")
    return offenders


def _jobs_with_permissions(text: str) -> tuple[set[str], set[str]]:
    """Return (jobs, jobs_with_permissions) parsed from workflow YAML."""
    jobs: set[str] = set()
    with_permissions: set[str] = set()
    current: str | None = None
    in_jobs = False
    depth_jobs = 0
    for line in text.splitlines():
        stripped = _strip_comment(line).strip()
        if re.match(r"^jobs:\s*$", stripped):
            in_jobs = True
            depth_jobs = len(line) - len(line.lstrip())
            continue
        if not in_jobs or not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= depth_jobs and stripped.endswith(":") and " " not in stripped[:-1]:
            in_jobs = stripped == "jobs:"
            current = None
            continue
        if indent == depth_jobs + 2 and stripped.endswith(":"):
            current = stripped[:-1]
            jobs.add(current)
        elif current is not None and indent > depth_jobs + 2:
            if re.match(r"^permissions:\s*", stripped):
                with_permissions.add(current)
    return jobs, with_permissions


def _workflow_files() -> list[Path]:
    """All workflow files, both YAML extensions."""
    return sorted([*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")])


class TestWorkflowSupplyChain:
    def test_all_action_refs_pinned_to_full_sha(self) -> None:
        """Every uses: is owner/repo@40-hex (comment tag allowed)."""
        offenders: list[str] = []
        for workflow in _workflow_files():
            for hit in _unpinned_refs(workflow.read_text(encoding="utf-8")):
                offenders.append(f"{workflow.name}:{hit}")
        assert offenders == []

    def test_every_job_declares_permissions(self) -> None:
        """Least privilege is explicit per job, not inherited-only."""
        missing: list[str] = []
        for workflow in _workflow_files():
            jobs, with_permissions = _jobs_with_permissions(workflow.read_text())
            for job in sorted(jobs - with_permissions):
                missing.append(f"{workflow.name}:{job}")
        assert missing == []

    def test_floating_tag_detected(self) -> None:
        """Negative fixture: @v4 without a SHA must fail the guard."""
        text = "      - uses: actions/checkout@v4\n"
        assert _unpinned_refs(text) != []

    def test_branch_ref_detected(self) -> None:
        """Negative fixture: @main must fail the guard."""
        text = "      - uses: actions/checkout@main\n"
        assert _unpinned_refs(text) != []

    def test_short_sha_detected(self) -> None:
        """Negative fixture: abbreviated SHAs must fail the guard."""
        text = "      - uses: actions/checkout@11d5960\n"
        assert _unpinned_refs(text) != []

    def test_malformed_prefix_detected(self) -> None:
        """Negative fixture: missing owner/repo shape must fail the guard."""
        for bad in (
            "      - uses: checkout@11d5960a326750d5838078e36cf38b85af677262\n",
            "      - uses: @11d5960a326750d5838078e36cf38b85af677262\n",
            "      - uses: actions//checkout@11d5960a326750d5838078e36cf38b85af677262\n",
            "      - uses: ../repo@11d5960a326750d5838078e36cf38b85af677262\n",
            "      - uses: owner/..@11d5960a326750d5838078e36cf38b85af677262\n",
            "      - uses: .hidden/repo@11d5960a326750d5838078e36cf38b85af677262\n",
        ):
            assert _unpinned_refs(bad) != [], bad

    def test_pinned_ref_with_comment_passes(self) -> None:
        """Negative control: full SHA plus readability comment is fine."""
        text = "      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4\n"
        assert _unpinned_refs(text) == []

    def test_job_without_permissions_detected(self) -> None:
        """Negative fixture: a permission-less job must fail the guard."""
        text = "jobs:\n  unit:\n    runs-on: ubuntu-latest\n"
        jobs, with_permissions = _jobs_with_permissions(text)
        assert jobs - with_permissions == {"unit"}

    def test_spaced_uses_detected(self) -> None:
        """Negative fixture: `uses :` with a space must not bypass the scan."""
        text = "      - uses : actions/checkout@v4\n"
        assert _unpinned_refs(text) != []

    def test_commented_job_header_checked(self) -> None:
        """Negative fixture: `unit: # comment` must still be permission-checked."""
        text = "jobs:\n  unit: # job comment\n    runs-on: ubuntu-latest\n"
        jobs, with_permissions = _jobs_with_permissions(text)
        assert jobs - with_permissions == {"unit"}

    def test_job_with_empty_permissions_passes(self) -> None:
        """Negative control: explicit permissions: {} counts as declared."""
        text = "jobs:\n  unit:\n    runs-on: ubuntu-latest\n    permissions: {}\n"
        jobs, with_permissions = _jobs_with_permissions(text)
        assert jobs - with_permissions == set()
