"""Risk-based PR verification workflow contract.

Locks in the additive shape of ``verification.yml``: the three jobs, the
read-only default permissions, the pinned actions, the merge-queue trigger,
and the fail-closed stale-base check. No network or YAML dependency required.
"""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "verification.yml"
REPORT_MARKER = "<!-- pr-verification-report -->"
PINNED_ACTION = re.compile(r"uses:\s*[^@\s]+@[0-9a-f]{40}\b")


def _text() -> str:
    """Return the workflow source."""
    return WORKFLOW.read_text(encoding="utf-8")


class TestVerificationWorkflowShape:
    def test_triggers_cover_pull_request_and_merge_group(self) -> None:
        """Both entry points are present."""
        text = _text()
        assert "pull_request:" in text
        assert "merge_group:" in text

    def test_four_jobs_are_present(self) -> None:
        """Classification, evidence, reporting, and the aggregate gate stay separate."""
        text = _text()
        for job in ("plan:", "evidence:", "report:", "verification:"):
            assert f"\n  {job}" in text

    def test_aggregate_check_has_a_stable_required_context(self) -> None:
        """Branch protection can require one stable job name."""
        text = _text()
        aggregate = text.split("\n  verification:", 1)[1]
        assert "name: PR verification" in aggregate
        assert "needs: [plan, evidence, report]" in aggregate
        assert "PLAN_RESULT: ${{ needs.plan.result }}" in aggregate
        assert "EVIDENCE_RESULT: ${{ needs.evidence.result }}" in aggregate

    def test_every_job_checks_out_the_script(self) -> None:
        """A job that runs the helper must have the repository available."""
        text = _text()
        assert text.count("actions/checkout@") == 3

    def test_default_permissions_are_read_only(self) -> None:
        """The workflow cannot write contents by default."""
        text = _text()
        assert "permissions:\n  contents: read\n" in text
        assert "contents: write" not in text

    def test_report_job_can_write_comments(self) -> None:
        """Only the reporting job receives issue write access."""
        text = _text()
        report_section = text.split("\n  report:", 1)[1]
        assert "issues: write" in report_section
        assert "pull-requests: write" in report_section

    def test_actions_are_pinned_to_commit_shas(self) -> None:
        """No floating action tags are introduced."""
        text = _text()
        uses = [line.strip() for line in text.splitlines() if "uses:" in line]
        assert uses
        for line in uses:
            assert PINNED_ACTION.search(line), line

    def test_merge_group_base_is_reverified(self) -> None:
        """A queued base that moved fails closed."""
        text = _text()
        assert "STALE_BASE" in text
        assert "MERGE_GROUP_BASE_SHA" in text

    def test_deleted_policy_fails_closed(self) -> None:
        """A policy deletion cannot bypass the weakening guard."""
        text = _text()
        assert 'elif [ "${POLICY_EXISTED}" = "true" ]; then' in text
        assert "verification policy was deleted" in text

    def test_evidence_waits_for_required_checks_only(self) -> None:
        """The poll ignores unrelated check-runs, including its own job."""
        text = _text()
        assert 'required = json.load(open("plan.json"))' in text
        assert 'observed.get(name) != "completed"' in text

    def test_sticky_comment_marker_is_shared_with_the_renderer(self) -> None:
        """The workflow and the helper agree on the marker."""
        assert REPORT_MARKER in _text()
        helper = (Path(__file__).resolve().parents[3] / "scripts" / "pr_verification.py").read_text(
            encoding="utf-8"
        )
        assert REPORT_MARKER in helper

    def test_report_job_syncs_the_human_review_label(self) -> None:
        """A green verdict with an outstanding approval stays visible in the list."""
        text = _text()
        report_section = text.split("\n  report:", 1)[1].split("\n  verification:", 1)[0]
        assert "pr_verification.py label" in report_section
        assert "needs-human-review" in report_section
        assert report_section.count("labels/needs-human-review") == 1

    def test_label_sync_skips_fork_pull_requests(self) -> None:
        """Fork runs have a read-only token and must not attempt writes."""
        text = _text()
        report_section = text.split("\n  report:", 1)[1].split("\n  verification:", 1)[0]
        guard = "github.event.pull_request.head.repo.full_name == github.repository"
        assert report_section.count(guard) == 2
