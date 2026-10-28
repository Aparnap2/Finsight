"""Contract tests for the risk-based pull-request verification script.

The tests are offline and stdlib-only. They cover the fail-closed boundaries that
matter for review quality: risk classification, declared diff scope, policy
weakening, required-check evaluation, head-commit approvals, and the
exception-only report.
"""

from __future__ import annotations

import fnmatch
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


def _run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run the verification CLI as a subprocess."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
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


def test_build_evidence_missing_approval_is_a_label_not_a_failure(
    verification: ModuleType,
) -> None:
    """A missing approval is a merge boundary, not a technical gate failure.

    Branch protection enforces required approvals at merge time. Treating the
    shortfall as a verification failure would leave every review-required change
    red on a repository with zero required approvals, and would conflate "gates
    passed" with "mergeable".
    """
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
    assert blocked.verdict == "pass"
    assert not blocked.exceptions
    assert blocked.needs_human_review
    assert any("human approval incomplete" in item for item in blocked.advisories)
    assert not any("human approval required" in item for item in blocked.exceptions)

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
    assert not approved.needs_human_review


def test_build_evidence_changes_requested_still_fails(verification: ModuleType) -> None:
    """An affirmative objection blocks the verdict even when gates are green."""
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
    evidence = verification.build_evidence(
        plan,
        checks,
        (
            verification.Review(state="APPROVED", commit_id="head", author="bob"),
            verification.Review(state="CHANGES_REQUESTED", commit_id="head", author="carol"),
        ),
        event="pull_request",
        head_sha="head",
        author="author",
        generated_at="2026-10-24T00:00:00+00:00",
    )
    assert evidence.verdict == "fail"
    assert any("changes requested" in item for item in evidence.exceptions)
    assert evidence.needs_human_review


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


HYGIENE_PATHS = (".gitignore", ".gitattributes", ".editorconfig")


def _legacy_policy_payload(payload: dict[str, object] | None = None) -> dict[str, object]:
    """Return the policy as it looked before ``repo-hygiene`` existed.

    The ratchet compares a pull request's policy against ``main``; these tests
    need the pre-downgrade baseline rather than the already-migrated file.
    """
    base = payload if payload is not None else _policy_payload()
    classes = _classes(base)
    classes.pop("repo-hygiene")
    rules: list[dict[str, object]] = []
    for rule in cast(list[dict[str, object]], base["path_rules"]):
        if rule.get("class") == "repo-hygiene":
            continue
        if rule.get("class") == "ci-infra":
            rule = dict(rule)
            rule["patterns"] = [*cast(list[str], rule["patterns"]), *HYGIENE_PATHS]
        rules.append(rule)
    base["path_rules"] = rules
    base.pop("acknowledged_path_downgrades", None)
    return base


def test_repo_hygiene_is_auto_and_low_risk(verification: ModuleType, policy: object) -> None:
    """Ignore/attribute/editor files are hygiene, not pipeline infrastructure."""
    classes = cast(Any, policy).classes
    for path in HYGIENE_PATHS:
        name = verification.classify_path(path, policy)
        assert name == "repo-hygiene"
        assert not classes[name].review_required
    plan = _plan(
        verification,
        policy,
        [".gitignore"],
        _scope_body(".gitignore"),
    )
    assert plan.risk == "repo-hygiene"
    assert plan.status == "pass"
    assert "GitGuardian Security Checks" in plan.required_checks


def test_repo_hygiene_keeps_secret_scan_and_baseline(
    verification: ModuleType, policy: object
) -> None:
    """The low-risk class still runs the baseline gates and the secret scan."""
    plan = _plan(verification, policy, [".gitignore"], _scope_body(".gitignore"))
    assert "lint / typecheck / unit+contract" in plan.required_checks
    assert "GitGuardian Security Checks" in plan.required_checks
    assert "postgres-gated integration" not in plan.required_checks


def test_repo_hygiene_never_wins_a_mixed_diff(verification: ModuleType, policy: object) -> None:
    """A hygiene edit alongside domain code takes the higher-risk class."""
    mixed = _plan(
        verification,
        policy,
        [".gitignore", ".github/workflows/ci.yml"],
        _scope_body(".gitignore", ".github/"),
    )
    assert mixed.risk == "ci-infra"
    assert mixed.status == "review"
    assert mixed.review_required

    execution = _plan(
        verification,
        policy,
        [".gitignore", "finance/execution/executor.py"],
        _scope_body(".gitignore", "finance/"),
    )
    assert execution.risk == "execution"

    domain = _plan(
        verification,
        policy,
        [".gitignore", "finance/kpi/engine.py"],
        _scope_body(".gitignore", "finance/kpi/"),
    )
    assert domain.risk == "finance-domain"


def test_ci_paths_are_still_infrastructure(verification: ModuleType, policy: object) -> None:
    """Workflow and tooling paths did not move with the dotfiles."""
    for path in (".github/workflows/ci.yml", "scripts/pr_verification.py", "conftest.py"):
        assert verification.classify_path(path, policy) == "ci-infra"


_ACCOUNTING_POLICY_INPUTS = (
    "docs/testing/test-accounting.json",
    "tests/accounting_plugin.py",
)


def test_accounting_policy_inputs_require_infrastructure_review(
    verification: ModuleType, policy: object
) -> None:
    """The gate's manifest and its evidence producer are policy, not prose.

    `scripts/test_accounting.py` reads every acceptance expectation from
    `docs/testing/test-accounting.json` and every measurement from
    `tests/accounting_plugin.py`. Classifying either as `docs` or `tests-only`
    would let a zero-review edit change what the gate can detect.
    """
    typed = cast(Any, policy)
    infra = typed.classes["ci-infra"]
    assert infra.severity == 4
    assert infra.review_required is True
    expected = verification.required_checks(policy, "ci-infra")
    assert len(expected) == 5
    for path in _ACCOUNTING_POLICY_INPUTS:
        risk = verification.classify_path(path, policy)
        assert risk == "ci-infra"
        assert verification.required_checks(policy, risk) == expected


def test_manifest_only_change_is_planned_as_infrastructure(
    verification: ModuleType, policy: object
) -> None:
    """A manifest-only diff must not land as a one-gate docs change."""
    changed = ["docs/testing/test-accounting.json"]
    plan = _plan(verification, policy, changed, _scope_body(*changed))
    assert plan.risk == "ci-infra"
    assert plan.review_required is True
    assert set(plan.required_checks) == set(verification.required_checks(policy, "ci-infra"))


def test_path_ratchet_rejects_rerouting_accounting_policy(
    verification: ModuleType, policy: object, tmp_path: Path
) -> None:
    """Moving the manifest or plugin back to a weaker class must fail the ratchet."""
    payload = _policy_payload()
    rules = cast(list[dict[str, object]], payload["path_rules"])
    protected = set(_ACCOUNTING_POLICY_INPUTS)
    for rule in rules:
        if rule["class"] == "ci-infra":
            rule["patterns"] = [
                pattern for pattern in cast(list[str], rule["patterns"]) if pattern not in protected
            ]
    payload["path_rules"] = [rule for rule in rules if cast(list[str], rule["patterns"])]
    proposed = verification.load_policy(_write_policy(tmp_path, payload))
    errors = verification.evaluate_path_weakening(policy, proposed)
    for path in _ACCOUNTING_POLICY_INPUTS:
        assert any(f"lowers classification for {path!r}" in error for error in errors), errors


def test_path_ratchet_rejects_unacknowledged_downgrade(
    verification: ModuleType, policy: object, tmp_path: Path
) -> None:
    """Moving a path to a lower class fails unless the downgrade is declared."""
    payload = _policy_payload()
    payload.pop("acknowledged_path_downgrades")
    proposed = verification.load_policy(_write_policy(tmp_path, payload))
    errors = verification.evaluate_policy_weakening(
        verification.load_policy(_write_policy(tmp_path, _legacy_policy_payload())), proposed
    )
    assert any("lowers classification for '.gitignore'" in error for error in errors)


def test_path_ratchet_accepts_acknowledged_downgrade(
    verification: ModuleType, policy: object, tmp_path: Path
) -> None:
    """A declared downgrade with a reason is allowed and matches the policy."""
    legacy = verification.load_policy(_write_policy(tmp_path, _legacy_policy_payload()))
    assert verification.evaluate_policy_weakening(legacy, policy) == ()


def test_path_ratchet_rejects_rerouted_infrastructure(
    verification: ModuleType, policy: object, tmp_path: Path
) -> None:
    """Re-routing .github/ into a low-risk class cannot hide behind class checks."""
    payload = _policy_payload()
    rules = cast(list[dict[str, object]], payload["path_rules"])
    for rule in rules:
        if rule["class"] == "ci-infra":
            rule["patterns"] = [p for p in cast(list[str], rule["patterns"]) if p != ".github/"]
        if rule["class"] == "docs":
            rule["patterns"] = [*cast(list[str], rule["patterns"]), ".github/"]
    proposed = verification.load_policy(_write_policy(tmp_path, payload))
    errors = verification.evaluate_policy_weakening(policy, proposed)
    assert any("lowers classification for '.github/'" in error for error in errors)


def test_path_ratchet_rejects_dishonest_acknowledgement(
    verification: ModuleType, policy: object, tmp_path: Path
) -> None:
    """An acknowledgement must name a real pattern, class, and downgrade."""
    payload = _policy_payload()
    payload["acknowledged_path_downgrades"] = [
        {
            "pattern": "nowhere/",
            "from": "ci-infra",
            "to": "repo-hygiene",
            "reason": "invented",
        }
    ]
    proposed = verification.load_policy(_write_policy(tmp_path, payload))
    errors = verification.evaluate_policy_weakening(policy, proposed)
    assert any("does not name a policy path pattern" in error for error in errors)


def _write_pr_json(path: Path, changed: list[str], labels: list[str]) -> Path:
    """Write a pull-request payload whose scope block covers the changed files."""
    payload = {
        "number": 1,
        "user": {"login": "octocat"},
        "labels": [{"name": name} for name in labels],
        "body": _scope_body(*changed),
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _run_plan_cli(
    tmp_path: Path,
    changed: list[str],
    *,
    policy: Path | None,
    head_policy: Path | None,
    labels: list[str] | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke the plan command with the same arguments the workflow passes.

    ``policy=None`` reproduces the pre-fix wiring, where the script fell back to
    the checked-out (head) policy because ``--policy`` was never supplied.
    """
    changed_file = tmp_path / "changed-files.txt"
    changed_file.write_text("\n".join(changed) + "\n", encoding="utf-8")
    pr_json = _write_pr_json(tmp_path / "pr.json", changed, labels or [])
    args = [
        "plan",
        "--changed-files",
        str(changed_file),
        "--pr-json",
        str(pr_json),
        "--out",
        str(tmp_path / "plan.json"),
        "--event",
        "pull_request",
        "--repository",
        "owner/repo",
        "--pr-number",
        "1",
        "--base-sha",
        "base",
        "--head-sha",
        "head",
        "--policy-existed-on-base",
        "true",
    ]
    if policy is not None:
        args += ["--policy", str(policy)]
    if head_policy is not None:
        args += ["--head-policy", str(head_policy)]
    return _run_cli(*args, cwd=cwd)


def test_workflow_reads_the_base_policy_from_the_base_revision() -> None:
    """The plan step must consume a policy materialized from BASE_SHA."""
    workflow = (ROOT / ".github" / "workflows" / "verification.yml").read_text(encoding="utf-8")
    assert 'git show "${BASE_SHA}:.github/verification-policy.json" > base-policy.json' in workflow
    plan_step = workflow.split("- name: Build verification plan", 1)[1].split("- name:", 1)[0]
    assert "--policy base-policy.json" in plan_step
    assert '"${POLICY_ARGS[@]}"' in plan_step


def test_plan_cli_rejects_weakened_path_policy(tmp_path: Path) -> None:
    """A rerouted path is caught through the workflow's real argument wiring."""
    payload = _policy_payload()
    rules = cast(list[dict[str, object]], payload["path_rules"])
    for rule in rules:
        if rule["class"] == "ci-infra":
            rule["patterns"] = [p for p in cast(list[str], rule["patterns"]) if p != ".github/"]
        if rule["class"] == "docs":
            rule["patterns"] = [*cast(list[str], rule["patterns"]), ".github/"]
    head = _write_policy(tmp_path, payload)
    result = _run_plan_cli(
        tmp_path,
        [".github/verification-policy.json", "docs/notes.md"],
        policy=POLICY,
        head_policy=head,
        labels=["policy-change"],
    )
    assert result.returncode == 1, result.stderr
    assert "lowers classification for '.github/': ci-infra -> docs" in result.stderr


def test_plan_cli_rejects_head_policy_as_the_base_policy(tmp_path: Path) -> None:
    """Evaluating the head policy against itself must fail closed, not pass 0 errors."""
    result = _run_plan_cli(
        tmp_path,
        [".github/verification-policy.json"],
        policy=None,
        head_policy=POLICY,
        labels=["policy-change"],
        cwd=ROOT,
    )
    assert result.returncode == 1, result.stdout
    assert "the base policy must be read from the base revision" in result.stderr


def test_plan_cli_accepts_an_unchanged_policy(tmp_path: Path) -> None:
    """A diff that leaves the policy alone still plans cleanly."""
    result = _run_plan_cli(
        tmp_path,
        ["docs/notes.md"],
        policy=POLICY,
        head_policy=POLICY,
    )
    assert result.returncode == 0, result.stderr
    assert "status=" in result.stdout


def test_plan_cli_accepts_a_strengthened_policy(tmp_path: Path) -> None:
    """Adding a required check is a strengthening and must not trip the ratchet."""
    payload = _policy_payload()
    _classes(payload)["docs"]["extra_checks"] = ["postgres-gated integration"]
    head = _write_policy(tmp_path, payload)
    result = _run_plan_cli(
        tmp_path,
        [".github/verification-policy.json", "docs/notes.md"],
        policy=POLICY,
        head_policy=head,
        labels=["policy-change"],
    )
    assert result.returncode == 0, result.stderr
    assert "lowers classification" not in result.stderr


def test_plan_cli_fails_on_an_unusable_policy_pattern(tmp_path: Path) -> None:
    """A pattern the ratchet cannot probe fails visibly instead of shrinking coverage."""
    payload = _policy_payload()
    for rule in cast(list[dict[str, object]], payload["path_rules"]):
        if rule["class"] == "docs":
            rule["patterns"] = [*cast(list[str], rule["patterns"]), "[abc"]
    base = _write_policy(tmp_path, payload)
    result = _run_plan_cli(
        tmp_path,
        [".github/verification-policy.json"],
        policy=base,
        head_policy=POLICY,
        labels=["policy-change"],
    )
    assert result.returncode == 1, result.stdout
    assert "unterminated character class" in result.stderr


def test_probe_paths_match_every_policy_pattern(verification: ModuleType, policy: object) -> None:
    """Every declared pattern must yield a probe that the pattern itself matches."""
    for rule in cast(Any, policy).path_rules:
        for pattern in rule.patterns:
            probe = verification._probe_path(pattern)
            assert verification._path_matches(probe, pattern), (pattern, probe)


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        (".github/", "ci-infra"),
        ("tests/", "tests-only"),
        ("docs/", "docs"),
        ("*Pipfile", "dependencies"),
        ("*/Makefile", "ci-infra"),
        ("*pyproject.toml", "dependencies"),
    ],
)
def test_probe_paths_preserve_prefix_and_glob_classification(
    verification: ModuleType, policy: object, pattern: str, expected: str
) -> None:
    """Prefix and glob rules classify their probes as they do real files."""
    probe = verification._probe_path(pattern)
    assert verification.classify_path(probe, policy) == expected


@pytest.mark.parametrize(
    "pattern",
    ["[abc]", "[abc].py", "[!p]", "[a-z]/*.cfg", "docs/[0-9]/", "lib/?.so", "*/"],
)
def test_probe_paths_cover_character_classes_and_directory_globs(
    verification: ModuleType, pattern: str
) -> None:
    """A satisfiable pattern yields a probe the rule it came from actually governs."""
    probe = verification._probe_path(pattern)
    matchable = pattern.rstrip("/")
    candidate = probe.rsplit("/", 1)[0] if pattern.endswith("/") else probe
    if any(char in matchable for char in "*?["):
        assert fnmatch.fnmatchcase(candidate, matchable), (pattern, probe)
    else:
        assert verification._path_matches(candidate, matchable), (pattern, probe)
    if pattern.endswith("/"):
        assert probe.endswith("/__probe__.txt")


@pytest.mark.parametrize("pattern", ["[abc", "[!]"])
def test_probe_paths_reject_unusable_globs(verification: ModuleType, pattern: str) -> None:
    """Malformed or unsatisfiable character classes are not silently dropped."""
    with pytest.raises(verification.PolicyError):
        verification._probe_path(pattern)


def test_label_command_requests_review_on_shortfall(
    verification: ModuleType, tmp_path: Path
) -> None:
    """The label decision follows the evidence flag and fails closed when absent."""
    evidence = tmp_path / "evidence.json"
    out = tmp_path / "label.txt"
    evidence.write_text(json.dumps({"verdict": "pass", "needs_human_review": True}), "utf-8")
    assert verification.main(["label", "--evidence", str(evidence), "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8").strip() == "needs-human-review"

    evidence.write_text(json.dumps({"verdict": "pass", "needs_human_review": False}), "utf-8")
    assert verification.main(["label", "--evidence", str(evidence), "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8").strip() == ""

    missing = tmp_path / "absent.json"
    assert verification.main(["label", "--evidence", str(missing), "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8").strip() == "needs-human-review"


def test_report_pass_declares_the_merge_gate(verification: ModuleType) -> None:
    """A green verdict must not read as mergeable when approval is outstanding."""
    report = verification.render_report(
        {
            "verdict": "pass",
            "risk": "ci-infra",
            "head_sha": "head",
            "required_checks": ["lint / typecheck / unit+contract"],
            "exceptions": [],
            "advisories": ["human approval incomplete: 0/1"],
            "review_required": True,
            "human_approvals": ["CI infrastructure review"],
            "approved_by": [],
            "approvals_required": 1,
            "needs_human_review": True,
            "checks": [],
        }
    )
    assert "### Merge gate" in report
    assert "not a mergeability claim" in report
    assert "branch protection" in report.lower()
    assert "will block" not in report.lower()
    assert "needs-human-review" in report


def test_report_clean_pass_has_no_merge_gate(verification: ModuleType) -> None:
    """Without a shortfall the report stays exception-only."""
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
            "needs_human_review": False,
            "checks": [],
        }
    )
    assert "### Merge gate" not in report
