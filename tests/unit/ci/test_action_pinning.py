"""Workflow supply-chain lock-in (APA-85/R6): SHA pinning + least privilege.

RED until GREEN: fails on floating action refs and on jobs without an
explicit permissions block. No network required.
"""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[3] / ".github" / "workflows"

_PINNED_USES = re.compile(r"^[^@\s]+@[0-9a-f]{40}(?:\s+#\s*\S+)?\s*$")
_JOB_HEADER = re.compile(r"^( {2})(\S[^:]*):\s*$")
_PERMISSIONS_LINE = re.compile(r"^permissions:\s*(\{\})?\s*$")


def _jobs_with_permissions(text: str) -> tuple[set[str], set[str]]:
    """Return (jobs, jobs_with_permissions) parsed from workflow YAML."""
    jobs: set[str] = set()
    with_permissions: set[str] = set()
    current: str | None = None
    in_jobs = False
    depth_jobs = 0
    for line in text.splitlines():
        stripped = line.strip()
        if re.match(r"^jobs:\s*$", line):
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


class TestWorkflowSupplyChain:
    def test_all_action_refs_pinned_to_full_sha(self) -> None:
        """Every uses: is owner/repo@40-hex (comment tag allowed)."""
        offenders: list[str] = []
        for workflow in sorted(WORKFLOWS.glob("*.yml")):
            for lineno, line in enumerate(workflow.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#") or "uses:" not in stripped:
                    continue
                ref = stripped.split("uses:", 1)[1].strip()
                if not _PINNED_USES.match(ref):
                    offenders.append(f"{workflow.name}:{lineno}:{ref}")
        assert offenders == []

    def test_every_job_declares_permissions(self) -> None:
        """Least privilege is explicit per job, not inherited-only."""
        missing: list[str] = []
        for workflow in sorted(WORKFLOWS.glob("*.yml")):
            jobs, with_permissions = _jobs_with_permissions(workflow.read_text())
            for job in sorted(jobs - with_permissions):
                missing.append(f"{workflow.name}:{job}")
        assert missing == []
