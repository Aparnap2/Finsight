"""Contract tests for the risk-based pull-request verification script.

The tests are offline and stdlib-only. They cover the fail-closed boundaries that
matter for review quality: risk classification, declared diff scope, policy
weakening, required-check evaluation, head-commit approvals, and the
exception-only report.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "pr_verification.py"
POLICY = ROOT / ".github" / "verification-policy.json"


def _load_module() -> ModuleType:
    """Load the verification script as a module without requiring a package."""
    spec = importlib.util.spec_from_file_location("pr_verification", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def verification() -> ModuleType:
    """Return a freshly loaded verification module."""
    return _load_module()


@pytest.fixture()
def policy(verification: ModuleType) -> object:
    """Return the repository policy loaded through the production loader."""
    return verification.load_policy(POLICY)


def _policy_payload() -> dict[str, object]:
    """Return the repository policy as a mutable JSON object."""
    return cast(dict[str, object], json.loads(POLICY.read_text(encoding="utf-8")))


def _write_policy(tmp_path: Path, payload: dict[str, object]) -> Path:
    """Write a policy payload to a temporary file."""
    path = tmp_path / "verification-policy.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _classes(payload: dict[str, object]) -> dict[str, dict[str, object]]:
    """Return the policy classes as a typed mapping."""
    raw = payload.get("classes")
    assert isinstance(raw, dict)
    result: dict[str, dict[str, object]] = {}
    for name, value in raw.items():
        assert isinstance(name, str)
        assert isinstance(value, dict)
        result[name] = cast(dict[str, object], value)
    return result


def _scope_body(*paths: str) -> str:
    """Build a pull-request body containing a valid scope block."""
    start = "<!-- verification-scope:start -->"
    end = "<!-- verification-scope:end -->"
    return f"{start}\n{json.dumps(list(paths))}\n{end}"


def _plan(
    verification: ModuleType,
    policy: object,
    changed: list[str],
    body: str,
    *,
    labels: tuple[str, ...] = (),
    existed: bool = True,
    proposed_policy: Any = None,
) -> Any:
    """Build a plan with stable test metadata."""
    return verification.build_plan(
        policy,
        changed,
        body,
        list(labels),
        policy_existed_on_base=existed,
        event="pull_request",
        repository="owner/repo",
        pr_number=1,
        base_sha="base",
        head_sha="head",
        proposed_policy=proposed_policy,
    )


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the verification CLI as a subprocess."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _minimal_plan(**overrides: object) -> dict[str, object]:
    """Return a minimal plan payload for evidence tests."""
    plan: dict[str, object] = {
        "status": "pass",
        "risk": "docs",
        "required_checks": ["lint / typecheck / unit+contract"],
        "review_required": False,
        "human_approvals": [],
        "changed_files": ["docs/readme.md"],
        "declared_scope": ["docs"],
        "errors": [],
        "advisories": [],
        "unknown_paths": [],
        "secondary_classes": [],
        "repository": "owner/repo",
        "pr_number": 1,
        "base_sha": "base",
        "head_sha": "head",
        "policy_digest": "digest",
    }
    plan.update(overrides)
    return plan


def _observation(verification: ModuleType, name: str, status: str, conclusion: str) -> object:
    """Build a check observation."""
    return verification.CheckObservation(
        name=name, status=status, conclusion=conclusion, details_url=""
    )


def test_policy_loads_and_keeps_protected_checks(verification: ModuleType) -> None:
    """The checked-in policy must retain every branch-protection context."""
    loaded = verification.load_policy(POLICY)
    universe = set(loaded.baseline_checks)
    for class_policy in loaded.classes.values():
        universe.update(class_policy.extra_checks)
    assert set(verification.PROTECTED_CHECKS) <= universe


def test_policy_rejects_missing_protected_check(verification: ModuleType, tmp_path: Path) -> None:
    """Removing a protected check from every class must fail closed."""
    payload = _policy_payload()
    payload["baseline_checks"] = ["lint / typecheck / unit+contract"]
    for class_policy in _classes(payload).values():
        class_policy["extra_checks"] = []
    with pytest.raises(verification.PolicyError, match="protected checks"):
        verification.load_policy(_write_policy(tmp_path, payload))


def test_policy_rejects_missing_risk_class(verification: ModuleType, tmp_path: Path) -> None:
    """Every documented risk class must be present in the policy."""
    payload = _policy_payload()
    raw = payload["classes"]
    assert isinstance(raw, dict)
    raw.pop("security-authz")
    with pytest.raises(verification.PolicyError, match="missing risk classes"):
        verification.load_policy(_write_policy(tmp_path, payload))


def test_policy_rejects_unknown_risk_class(verification: ModuleType, tmp_path: Path) -> None:
    """A typo in a class name must not be silently ignored."""
    payload = _policy_payload()
    raw = payload["classes"]
    assert isinstance(raw, dict)
    raw["surprise"] = {
        "severity": 1,
        "extra_checks": [],
        "review_required": False,
        "human_approvals": [],
    }
    with pytest.raises(verification.PolicyError, match="unknown risk classes"):
        verification.load_policy(_write_policy(tmp_path, payload))


def test_policy_rejects_absolute_policy_path(verification: ModuleType, tmp_path: Path) -> None:
    """The policy cannot relocate the guarded path."""
    payload = _policy_payload()
    payload["policy_path"] = "/tmp/elsewhere.json"
    with pytest.raises(verification.PolicyError, match="policy_path"):
        verification.load_policy(_write_policy(tmp_path, payload))


def test_classify_path_precedence(verification: ModuleType, policy: object) -> None:
    """Path rules must resolve the documented risk classes in order."""
    assert verification.classify_path("docs/auth.md", policy) == "docs"
    assert verification.classify_path("tests/unit/test_auth.py", policy) == "tests-only"
    assert verification.classify_path("shared/auth/tokens.py", policy) == "security-authz"
    assert verification.classify_path("pyproject.toml", policy) == "dependencies"
    assert verification.classify_path(".github/workflows/ci.yml", policy) == "ci-infra"
    assert verification.classify_path("finance/variance.py", policy) == "finance-domain"
    assert verification.classify_path("apps/web/page.tsx", policy) == "apps-web"
    assert verification.classify_path("random.txt", policy) == "unknown"


def test_security_paths_outrank_execution_and_migrations(
    verification: ModuleType, policy: object
) -> None:
    """Auth-adjacent files are never downgraded by a broader path rule."""
    assert verification.classify_path("finance/execution/auth.py", policy) == "security-authz"
    assert verification.classify_path("alembic/versions/0001_tenant_scope.py", policy) == (
        "security-authz"
    )
    assert verification.classify_path("scripts/permission_check.py", policy) == "security-authz"


def test_classify_mixed_paths_uses_highest_risk(verification: ModuleType, policy: object) -> None:
    """A mixed pull request takes the highest-severity class."""
    classification = verification.classify_paths(
        ["docs/readme.md", "shared/auth/tokens.py", "tests/unit/test_auth.py"],
        policy,
    )
    assert classification.risk == "security-authz"
    assert "docs" in classification.secondary_classes
    assert "tests-only" in classification.secondary_classes


def test_classify_unknown_paths_are_reported(verification: ModuleType, policy: object) -> None:
    """Unknown paths are reported explicitly, not guessed into a class."""
    classification = verification.classify_paths(["random.txt"], policy)
    assert classification.risk == "unknown"
    assert classification.unknown_paths == ("random.txt",)


def test_parse_scope_round_trip(verification: ModuleType) -> None:
    """A valid scope block is parsed and normalized."""
    body = _scope_body("finance/", "tests/unit/finance/")
    assert verification.parse_scope(body) == ("finance", "tests/unit/finance")


def test_parse_scope_missing_returns_none(verification: ModuleType) -> None:
    """A body without a scope block is distinguishable from a malformed one."""
    assert verification.parse_scope("Just a normal pull request.") is None


def test_parse_scope_malformed_raises(verification: ModuleType) -> None:
    """Malformed JSON in the scope block is a hard error."""
    start = "<!-- verification-scope:start -->"
    end = "<!-- verification-scope:end -->"
    body = f"{start}\nnot-json\n{end}"
    with pytest.raises(verification.ScopeError, match="not valid JSON"):
        verification.parse_scope(body)


def test_parse_scope_rejects_traversal(verification: ModuleType) -> None:
    """Scope entries cannot escape the repository."""
    body = _scope_body("../outside")
    with pytest.raises(verification.VerificationError, match="invalid path segment"):
        verification.parse_scope(body)


def test_validate_scope_uncovered_file_is_error(verification: ModuleType) -> None:
    """Every changed file must be covered by the declared scope."""
    result = verification.validate_scope(("docs",), ["docs/readme.md", "finance/x.py"])
    assert result.errors
    assert "finance/x.py" in result.errors[0]


def test_validate_scope_unused_entry_is_advisory(verification: ModuleType) -> None:
    """An unused declaration is a warning, not a merge blocker."""
    result = verification.validate_scope(("docs", "tests"), ["docs/readme.md"])
    assert not result.errors
    assert result.advisories
    assert "tests" in result.advisories[0]


def test_validate_scope_exact_file(verification: ModuleType) -> None:
    """A scope entry can name one file."""
    result = verification.validate_scope(("pyproject.toml",), ["pyproject.toml"])
    assert not result.errors


def test_policy_guard_blocks_unlabelled_change(verification: ModuleType, policy: object) -> None:
    """Changing the policy requires the explicit policy-change label."""
    guard = verification.evaluate_policy_guard(
        policy, [".github/verification-policy.json"], [], True
    )
    assert guard.changed
    assert not guard.allowed
    assert guard.errors


def test_policy_guard_allows_labelled_change(verification: ModuleType, policy: object) -> None:
    """The policy-change label satisfies the guard."""
    guard = verification.evaluate_policy_guard(
        policy, [".github/verification-policy.json"], ["Policy-Change"], True
    )
    assert guard.changed
    assert guard.allowed


def test_policy_guard_allows_bootstrap(verification: ModuleType, policy: object) -> None:
    """The initial policy addition is allowed without a label."""
    guard = verification.evaluate_policy_guard(
        policy, [".github/verification-policy.json"], [], False
    )
    assert guard.changed
    assert guard.allowed
    assert not guard.errors


def test_policy_weakening_rejects_removed_check(
    verification: ModuleType, policy: object, tmp_path: Path
) -> None:
    """A proposed policy cannot drop a class check that is still protected elsewhere."""
    payload = _policy_payload()
    security = _classes(payload)["security-authz"]
    security["extra_checks"] = [
        check
        for check in cast(list[str], security["extra_checks"])
        if check != "GitGuardian Security Checks"
    ]
    proposed = verification.load_policy(_write_policy(tmp_path, payload))
    errors = verification.evaluate_policy_weakening(policy, proposed)
    assert any("GitGuardian Security Checks" in error for error in errors)


def test_policy_weakening_rejects_lower_severity(
    verification: ModuleType, policy: object, tmp_path: Path
) -> None:
    """A proposed policy cannot downgrade a risk class."""
    payload = _policy_payload()
    _classes(payload)["security-authz"]["severity"] = 4
    proposed = verification.load_policy(_write_policy(tmp_path, payload))
    errors = verification.evaluate_policy_weakening(policy, proposed)
    assert any("lowers severity for security-authz" in error for error in errors)


def test_policy_weakening_rejects_disabled_review(
    verification: ModuleType, policy: object, tmp_path: Path
) -> None:
    """A proposed policy cannot turn off review for a review-required class."""
    payload = _policy_payload()
    _classes(payload)["security-authz"]["review_required"] = False
    proposed = verification.load_policy(_write_policy(tmp_path, payload))
    errors = verification.evaluate_policy_weakening(policy, proposed)
    assert any("disables review for security-authz" in error for error in errors)


def test_policy_weakening_rejects_removed_approvals(
    verification: ModuleType, policy: object, tmp_path: Path
) -> None:
    """A proposed policy cannot erase the human-approval boundary."""
    payload = _policy_payload()
    _classes(payload)["security-authz"]["human_approvals"] = []
    proposed = verification.load_policy(_write_policy(tmp_path, payload))
    errors = verification.evaluate_policy_weakening(policy, proposed)
    assert any("removes human approvals for security-authz" in error for error in errors)


def test_build_plan_fails_on_weakened_proposed_policy(
    verification: ModuleType, policy: object, tmp_path: Path
) -> None:
    """The plan fails closed before a weakened policy can merge."""
    payload = _policy_payload()
    _classes(payload)["security-authz"]["severity"] = 4
    proposed = verification.load_policy(_write_policy(tmp_path, payload))
    plan = _plan(
        verification,
        policy,
        ["shared/auth/tokens.py"],
        _scope_body("shared/"),
        proposed_policy=proposed,
    )
    assert plan.status == "fail"
    assert any("proposed policy" in error for error in plan.errors)


def test_required_checks_for_docs_is_baseline_only(
    verification: ModuleType, policy: object
) -> None:
    """Low-risk docs changes do not pull in the heavy gates."""
    checks = verification.required_checks(policy, "docs")
    assert checks == ("lint / typecheck / unit+contract",)


def test_required_checks_for_security_includes_all(
    verification: ModuleType, policy: object
) -> None:
    """Security changes require the full protected-check set."""
    checks = verification.required_checks(policy, "security-authz")
    assert set(verification.PROTECTED_CHECKS) <= set(checks)


def test_build_plan_fails_without_scope(verification: ModuleType, policy: object) -> None:
    """A missing scope declaration blocks the plan."""
    plan = _plan(verification, policy, ["docs/readme.md"], "")
    assert plan.status == "fail"
    assert "missing machine-readable verification scope block" in plan.errors


def test_build_plan_docs_passes(verification: ModuleType, policy: object) -> None:
    """A docs-only change with a valid scope passes."""
    plan = _plan(verification, policy, ["docs/readme.md"], _scope_body("docs/"))
    assert plan.status == "pass"
    assert plan.risk == "docs"
    assert not plan.errors


def test_build_plan_security_requires_review(verification: ModuleType, policy: object) -> None:
    """Security-sensitive changes require a human approval boundary."""
    plan = _plan(verification, policy, ["shared/auth/tokens.py"], _scope_body("shared/auth/"))
    assert plan.status == "review"
    assert plan.review_required
    assert plan.human_approvals


def test_build_plan_unknown_path_fails(verification: ModuleType, policy: object) -> None:
    """Unclassified paths fail closed instead of being guessed."""
    plan = _plan(verification, policy, ["random.txt"], _scope_body("random.txt"))
    assert plan.status == "fail"
    assert any("unclassified changed paths" in error for error in plan.errors)


def test_build_plan_policy_change_requires_label(verification: ModuleType, policy: object) -> None:
    """A policy edit without the label fails the plan."""
    changed = [".github/verification-policy.json"]
    plan = _plan(verification, policy, changed, _scope_body(".github/"))
    assert plan.status == "fail"
    assert plan.policy_changed
    assert any("policy-change" in error for error in plan.errors)


def test_build_plan_policy_change_with_label(verification: ModuleType, policy: object) -> None:
    """A labelled policy edit passes the guard but still needs CI review."""
    changed = [".github/verification-policy.json"]
    plan = _plan(
        verification,
        policy,
        changed,
        _scope_body(".github/"),
        labels=("policy-change",),
    )
    assert plan.status == "review"
    assert plan.policy_changed
    assert not plan.errors


def test_build_plan_bootstrap_policy_addition(verification: ModuleType, policy: object) -> None:
    """The initial policy addition is allowed without a label."""
    changed = [".github/verification-policy.json"]
    plan = _plan(verification, policy, changed, _scope_body(".github/"), existed=False)
    assert plan.status == "review"
    assert plan.policy_changed
    assert not plan.errors


def test_evaluate_checks_reports_every_state(verification: ModuleType) -> None:
    """Missing, pending, failed, and successful checks are distinct."""
    observations = {
        "a": _observation(verification, "a", "completed", "success"),
        "b": _observation(verification, "b", "in_progress", ""),
        "c": _observation(verification, "c", "completed", "failure"),
    }
    result = verification.evaluate_checks(["a", "b", "c", "d"], observations)
    assert result.missing == ("d",)
    assert result.pending == ("b",)
    assert result.failed == ("c",)
    assert not result.ok


def test_load_checks_fails_closed_on_duplicates(verification: ModuleType, tmp_path: Path) -> None:
    """A later failing duplicate check-run overrides an earlier success."""
    path = tmp_path / "checks.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "name": "a",
                        "status": "completed",
                        "conclusion": "success",
                        "details_url": "",
                    }
                ),
                json.dumps(
                    {
                        "name": "a",
                        "status": "completed",
                        "conclusion": "failure",
                        "details_url": "",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    observations = verification.load_checks(path)
    assert observations["a"].conclusion == "failure"


def test_evaluate_approvals_ignores_stale_and_self(
    verification: ModuleType,
) -> None:
    """Only non-author approvals at the exact head commit count."""
    reviews = (
        verification.Review(state="APPROVED", commit_id="old", author="alice"),
        verification.Review(state="APPROVED", commit_id="head", author="bob"),
        verification.Review(state="APPROVED", commit_id="head", author="author"),
    )
    result = verification.evaluate_approvals(
        reviews, head_sha="head", author="author", required=1, enforce=True
    )
    assert result.approved_by == ("bob",)
    assert result.ok


def test_evaluate_approvals_changes_requested_blocks(
    verification: ModuleType,
) -> None:
    """A changes-requested review blocks even with an approval."""
    reviews = (
        verification.Review(state="APPROVED", commit_id="head", author="bob"),
        verification.Review(state="CHANGES_REQUESTED", commit_id="head", author="carol"),
    )
    result = verification.evaluate_approvals(
        reviews, head_sha="head", author="author", required=1, enforce=True
    )
    assert result.changes_requested_by == ("carol",)
    assert not result.ok


def test_evaluate_approvals_merge_group_is_deferred(
    verification: ModuleType,
) -> None:
    """Merge-queue runs defer human approval to the pull-request run."""
    result = verification.evaluate_approvals(
        (), head_sha="head", author="author", required=1, enforce=False
    )
    assert result.required == 0
    assert result.ok


def test_build_evidence_pass(verification: ModuleType) -> None:
    """A successful check set produces a pass verdict."""
    evidence = verification.build_evidence(
        _minimal_plan(),
        {
            "lint / typecheck / unit+contract": _observation(
                verification, "lint / typecheck / unit+contract", "completed", "success"
            )
        },
        (),
        event="pull_request",
        head_sha="head",
        author="author",
        generated_at="2026-10-24T00:00:00+00:00",
    )
    assert evidence.verdict == "pass"
    assert not evidence.exceptions


def test_build_evidence_pending(verification: ModuleType) -> None:
    """A pending check produces the retryable pending verdict."""
    evidence = verification.build_evidence(
        _minimal_plan(),
        {
            "lint / typecheck / unit+contract": _observation(
                verification, "lint / typecheck / unit+contract", "in_progress", ""
            )
        },
        (),
        event="pull_request",
        head_sha="head",
        author="author",
        generated_at="2026-10-24T00:00:00+00:00",
    )
    assert evidence.verdict == "pending"
    assert evidence.pending_checks


def test_build_evidence_failed(verification: ModuleType) -> None:
    """A failed check produces a fail verdict."""
    evidence = verification.build_evidence(
        _minimal_plan(),
        {
            "lint / typecheck / unit+contract": _observation(
                verification, "lint / typecheck / unit+contract", "completed", "failure"
            )
        },
        (),
        event="pull_request",
        head_sha="head",
        author="author",
        generated_at="2026-10-24T00:00:00+00:00",
    )
    assert evidence.verdict == "fail"
    assert evidence.failed_checks


def test_build_evidence_requires_head_approval(verification: ModuleType) -> None:
    """Review-required plans fail until a non-author approves the head commit."""
    plan = _minimal_plan(
        status="review",
        risk="security-authz",
        review_required=True,
        human_approvals=["security review"],
    )
    checks = {
        "lint / typecheck / unit+contract": _observation(
            verification, "lint / typecheck / unit+contract", "completed", "success"
        )
    }
    blocked = verification.build_evidence(
        plan,
        checks,
        (),
        event="pull_request",
        head_sha="head",
        author="author",
        generated_at="2026-10-24T00:00:00+00:00",
    )
    assert blocked.verdict == "fail"
    assert any("human approval required" in item for item in blocked.exceptions)

    approved = verification.build_evidence(
        plan,
        checks,
        (verification.Review(state="APPROVED", commit_id="head", author="bob"),),
        event="pull_request",
        head_sha="head",
        author="author",
        generated_at="2026-10-24T00:00:00+00:00",
    )
    assert approved.verdict == "pass"
    assert approved.approved_by == ("bob",)


def test_report_pass_is_exception_only(verification: ModuleType) -> None:
    """A clean pass does not dump the full check table into the comment."""
    report = verification.render_report(
        {
            "verdict": "pass",
            "risk": "docs",
            "head_sha": "head",
            "required_checks": ["lint / typecheck / unit+contract"],
            "exceptions": [],
            "advisories": [],
            "review_required": False,
            "human_approvals": [],
            "approved_by": [],
            "approvals_required": 0,
            "checks": [],
        }
    )
    assert "No exceptions" in report
    assert "Required checks" not in report


def test_report_lists_exception(verification: ModuleType) -> None:
    """A failure report names the exception and the check row."""
    report = verification.render_report(
        {
            "verdict": "fail",
            "risk": "docs",
            "head_sha": "head",
            "required_checks": ["lint / typecheck / unit+contract"],
            "exceptions": ["missing required check: lint / typecheck / unit+contract"],
            "advisories": [],
            "review_required": False,
            "human_approvals": [],
            "approved_by": [],
            "approvals_required": 0,
            "checks": [
                {
                    "name": "lint / typecheck / unit+contract",
                    "status": "missing",
                    "conclusion": "missing",
                }
            ],
        }
    )
    assert "missing required check" in report
    assert "| `lint / typecheck / unit+contract` | missing |" in report


def test_cli_plan_writes_plan(tmp_path: Path) -> None:
    """The plan command writes a machine-readable plan."""
    changed = tmp_path / "changed.txt"
    changed.write_text("docs/readme.md\n", encoding="utf-8")
    pr = tmp_path / "pr.json"
    pr.write_text(
        json.dumps(
            {
                "number": 7,
                "body": _scope_body("docs/"),
                "labels": [],
                "user": {"login": "author"},
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "plan.json"
    result = _run_cli(
        "plan",
        "--changed-files",
        str(changed),
        "--pr-json",
        str(pr),
        "--out",
        str(out),
        "--base-sha",
        "base",
        "--head-sha",
        "head",
        "--pr-number",
        "7",
    )
    assert result.returncode == 0, result.stderr
    plan = json.loads(out.read_text(encoding="utf-8"))
    assert plan["risk"] == "docs"
    assert plan["status"] == "pass"


def test_cli_plan_fails_without_scope(tmp_path: Path) -> None:
    """The plan command exits non-zero when scope is missing."""
    changed = tmp_path / "changed.txt"
    changed.write_text("docs/readme.md\n", encoding="utf-8")
    pr = tmp_path / "pr.json"
    pr.write_text(json.dumps({"number": 7, "body": ""}), encoding="utf-8")
    out = tmp_path / "plan.json"
    result = _run_cli(
        "plan",
        "--changed-files",
        str(changed),
        "--pr-json",
        str(pr),
        "--out",
        str(out),
        "--base-sha",
        "base",
        "--head-sha",
        "head",
    )
    assert result.returncode == 1
    plan = json.loads(out.read_text(encoding="utf-8"))
    assert plan["status"] == "fail"


def test_cli_evidence_pending_returns_three(tmp_path: Path) -> None:
    """The evidence command returns 3 so the workflow can retry."""
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(_minimal_plan()), encoding="utf-8")
    checks_path = tmp_path / "checks.jsonl"
    checks_path.write_text(
        json.dumps(
            {
                "name": "lint / typecheck / unit+contract",
                "status": "in_progress",
                "conclusion": None,
                "details_url": "",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    reviews_path = tmp_path / "reviews.jsonl"
    reviews_path.write_text("", encoding="utf-8")
    out = tmp_path / "evidence.json"
    report = tmp_path / "report.md"
    result = _run_cli(
        "evidence",
        "--plan",
        str(plan_path),
        "--checks",
        str(checks_path),
        "--reviews",
        str(reviews_path),
        "--head-sha",
        "head",
        "--out",
        str(out),
        "--report",
        str(report),
    )
    assert result.returncode == 3
    assert "PENDING" in report.read_text(encoding="utf-8")


def test_cli_comment_payload(tmp_path: Path) -> None:
    """The comment payload is valid JSON with the report body."""
    report = tmp_path / "report.md"
    report.write_text("<!-- pr-verification-report -->\nhello\n", encoding="utf-8")
    out = tmp_path / "comment.json"
    result = _run_cli("comment-payload", "--report", str(report), "--out", str(out))
    assert result.returncode == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["body"].startswith("<!-- pr-verification-report -->")


def test_cli_pr_number_from_ref() -> None:
    """The merge-group ref parser extracts the pull request number."""
    result = _run_cli(
        "pr-number-from-ref",
        "--ref",
        "refs/heads/gh-readonly-queue/main/pr-42-abc123",
    )
    assert result.returncode == 0
    assert result.stdout == "42"
