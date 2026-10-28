"""Risk-based pull-request verification planner, evidence evaluator, and reporter.

The module is deliberately stdlib-only: it runs in the smallest CI job and is
fully exercised offline. It never calls GitHub itself. Callers pass the JSON
produced by ``gh api`` (pull request, check-runs, reviews) as files.

The three responsibilities are intentionally separate so the workflow can fail
closed at each boundary:

* ``plan`` classifies changed paths, enforces the declared diff scope, and guards
  the verification policy against silent weakening.
* ``evidence`` evaluates the required checks and human approvals at the exact
  head commit and writes a machine-readable evidence bundle.
* ``report`` renders the exception-only pull-request comment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from fnmatch import fnmatchcase
from pathlib import Path

SCHEMA_VERSION = 1
POLICY_PATH = ".github/verification-policy.json"
POLICY_CHANGE_LABEL = "policy-change"
NEEDS_HUMAN_REVIEW_LABEL = "needs-human-review"
REPORT_MARKER = "<!-- pr-verification-report -->"
SCOPE_START = "<!-- verification-scope:start -->"
SCOPE_END = "<!-- verification-scope:end -->"

RISK_CLASSES: tuple[str, ...] = (
    "docs",
    "repo-hygiene",
    "tests-only",
    "apps-web",
    "finance-domain",
    "execution",
    "dependencies",
    "migrations",
    "ci-infra",
    "security-authz",
    "unknown",
)

# Branch-protection contexts that must remain reachable from the policy. This
# is the anti-weakening invariant: a policy edit may tune which risk class needs
# a check, but it may not erase a protected check from the policy entirely.
PROTECTED_CHECKS: tuple[str, ...] = (
    "lint / typecheck / unit+contract",
    "postgres-gated integration",
    "ministack S3 contract (LocalStack)",
    "deterministic golden-dataset eval gate",
    "GitGuardian Security Checks",
)

CLASS_RANK: dict[str, int] = {name: index for index, name in enumerate(RISK_CLASSES)}


class VerificationError(Exception):
    """Base error for malformed inputs or violated verification invariants."""


class PolicyError(VerificationError):
    """The verification policy is missing, malformed, or weakened."""


class ScopeError(VerificationError):
    """The pull request does not declare a valid machine-readable diff scope."""


@dataclass(frozen=True)
class ClassPolicy:
    """Verification requirements for one risk class."""

    severity: int
    extra_checks: tuple[str, ...]
    review_required: bool
    human_approvals: tuple[str, ...]


@dataclass(frozen=True)
class PathRule:
    """Ordered path rule mapping a path pattern to a risk class."""

    class_name: str
    patterns: tuple[str, ...]


@dataclass(frozen=True)
class PathDowngrade:
    """A declared, reviewable exception to the path-classification ratchet.

    Moving a path to a lower-risk class is legitimate when the path's risk
    genuinely drops (for example, a hook that no longer gates a build), but it
    must be recorded here so the change appears in the policy diff instead of
    happening silently.
    """

    pattern: str
    from_class: str
    to_class: str
    reason: str


@dataclass(frozen=True)
class Policy:
    """Validated verification policy."""

    schema_version: int
    policy_path: str
    digest: str
    baseline_checks: tuple[str, ...]
    classes: dict[str, ClassPolicy]
    path_rules: tuple[PathRule, ...]
    acknowledged_path_downgrades: tuple[PathDowngrade, ...] = ()


@dataclass(frozen=True)
class Classification:
    """Risk classification for a set of changed files."""

    risk: str
    per_file: tuple[tuple[str, str], ...]
    secondary_classes: tuple[str, ...]
    unknown_paths: tuple[str, ...]
    changed_files: tuple[str, ...]


@dataclass(frozen=True)
class ScopeValidation:
    """Result of comparing declared scope with actual changed files."""

    declared: tuple[str, ...] | None
    errors: tuple[str, ...]
    advisories: tuple[str, ...]


@dataclass(frozen=True)
class PolicyGuard:
    """Result of the policy self-weakening guard."""

    changed: bool
    allowed: bool
    errors: tuple[str, ...]


@dataclass(frozen=True)
class Plan:
    """Complete verification plan for one pull request or merge-group run."""

    schema_version: int
    event: str
    repository: str
    pr_number: int
    base_sha: str
    head_sha: str
    policy_path: str
    policy_digest: str
    proposed_policy_digest: str | None
    policy_existed_on_base: bool
    policy_changed: bool
    risk: str
    secondary_classes: tuple[str, ...]
    per_file: tuple[tuple[str, str], ...]
    unknown_paths: tuple[str, ...]
    changed_files: tuple[str, ...]
    declared_scope: tuple[str, ...] | None
    scope_errors: tuple[str, ...]
    scope_advisories: tuple[str, ...]
    required_checks: tuple[str, ...]
    review_required: bool
    human_approvals: tuple[str, ...]
    status: str
    errors: tuple[str, ...]
    advisories: tuple[str, ...]


@dataclass(frozen=True)
class CheckObservation:
    """One observed check-run for the head commit."""

    name: str
    status: str
    conclusion: str
    details_url: str


@dataclass(frozen=True)
class CheckEvaluation:
    """Required-check evaluation outcome."""

    missing: tuple[str, ...]
    pending: tuple[str, ...]
    failed: tuple[str, ...]

    @property
    def ok(self) -> bool:
        """Return true when every required check completed successfully."""
        return not (self.missing or self.pending or self.failed)


@dataclass(frozen=True)
class Review:
    """One pull-request review at a specific commit."""

    state: str
    commit_id: str
    author: str


@dataclass(frozen=True)
class ApprovalEvaluation:
    """Human-approval evaluation outcome at the head commit."""

    required: int
    approved_by: tuple[str, ...]
    changes_requested_by: tuple[str, ...]

    @property
    def ok(self) -> bool:
        """Return true when approvals are sufficient and nothing is blocked."""
        return not self.changes_requested_by and len(self.approved_by) >= self.required


@dataclass(frozen=True)
class Evidence:
    """Machine-readable verification evidence bundle."""

    schema_version: int
    generated_at: str
    event: str
    repository: str
    pr_number: int
    base_sha: str
    head_sha: str
    risk: str
    secondary_classes: tuple[str, ...]
    changed_files: tuple[str, ...]
    declared_scope: tuple[str, ...] | None
    required_checks: tuple[str, ...]
    checks: tuple[CheckObservation, ...]
    missing_checks: tuple[str, ...]
    pending_checks: tuple[str, ...]
    failed_checks: tuple[str, ...]
    approvals_required: int
    approved_by: tuple[str, ...]
    changes_requested_by: tuple[str, ...]
    review_required: bool
    human_approvals: tuple[str, ...]
    needs_human_review: bool
    plan_status: str
    verdict: str
    exceptions: tuple[str, ...]
    advisories: tuple[str, ...]
    policy_digest: str


def _as_dict(value: object, where: str) -> dict[str, object]:
    """Return a string-keyed object or raise a verification error."""
    if not isinstance(value, dict):
        raise VerificationError(f"{where}: expected a JSON object")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise VerificationError(f"{where}: object keys must be strings")
        result[key] = item
    return result


def _as_list(value: object, where: str) -> list[object]:
    """Return a JSON array (or internal tuple) as a list or raise."""
    if not isinstance(value, (list, tuple)):
        raise VerificationError(f"{where}: expected a JSON array")
    return list(value)


def _as_str(value: object, where: str) -> str:
    """Return a non-empty string or raise a verification error."""
    if not isinstance(value, str):
        raise VerificationError(f"{where}: expected a string")
    return value


def _as_int(value: object, where: str) -> int:
    """Return an integer, rejecting booleans, or raise a verification error."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise VerificationError(f"{where}: expected an integer")
    return value


def _as_bool(value: object, where: str) -> bool:
    """Return a boolean or raise a verification error."""
    if not isinstance(value, bool):
        raise VerificationError(f"{where}: expected a boolean")
    return value


def _as_str_list(value: object, where: str) -> tuple[str, ...]:
    """Return a tuple of strings from a JSON array."""
    items = _as_list(value, where)
    result: list[str] = []
    for index, item in enumerate(items):
        result.append(_as_str(item, f"{where}[{index}]"))
    return tuple(result)


def _normalize_path(path: str, where: str) -> str:
    """Normalize a repository-relative path and reject traversal/absolute paths."""
    candidate = path.strip().replace("\\", "/")
    if candidate.startswith("./"):
        candidate = candidate[2:]
    candidate = candidate.rstrip("/")
    if not candidate:
        raise VerificationError(f"{where}: empty path")
    if candidate.startswith("/"):
        raise VerificationError(f"{where}: absolute path is not allowed: {candidate}")
    parts = candidate.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise VerificationError(f"{where}: invalid path segment: {candidate}")
    return candidate


def _path_matches(path: str, pattern: str) -> bool:
    """Match a path against a directory prefix or a shell-style glob."""
    if any(char in pattern for char in "*?["):
        return fnmatchcase(path, pattern)
    prefix = pattern.rstrip("/")
    return path == prefix or path.startswith(f"{prefix}/")


def _as_class_policy(name: str, value: object) -> ClassPolicy:
    """Validate and build one class policy."""
    data = _as_dict(value, f"classes.{name}")
    severity = _as_int(data.get("severity"), f"classes.{name}.severity")
    if severity < 0 or severity > 6:
        raise PolicyError(f"classes.{name}.severity must be between 0 and 6")
    extra_checks = _as_str_list(data.get("extra_checks", []), f"classes.{name}.extra_checks")
    review_required = _as_bool(data.get("review_required"), f"classes.{name}.review_required")
    human_approvals = _as_str_list(
        data.get("human_approvals", []), f"classes.{name}.human_approvals"
    )
    return ClassPolicy(
        severity=severity,
        extra_checks=extra_checks,
        review_required=review_required,
        human_approvals=human_approvals,
    )


def _as_path_downgrades(value: object) -> tuple[PathDowngrade, ...]:
    """Validate the optional acknowledged path-downgrade declarations."""
    if value is None:
        return ()
    items = _as_list(value, "acknowledged_path_downgrades")
    result: list[PathDowngrade] = []
    for index, item in enumerate(items):
        where = f"acknowledged_path_downgrades[{index}]"
        data = _as_dict(item, where)
        result.append(
            PathDowngrade(
                pattern=_as_str(data.get("pattern"), f"{where}.pattern"),
                from_class=_as_str(data.get("from"), f"{where}.from"),
                to_class=_as_str(data.get("to"), f"{where}.to"),
                reason=_as_str(data.get("reason"), f"{where}.reason"),
            )
        )
    return tuple(result)


def _validate_protected_checks(policy: Policy) -> None:
    """Fail if the policy erases any branch-protection check from its universe."""
    universe = set(policy.baseline_checks)
    for class_policy in policy.classes.values():
        universe.update(class_policy.extra_checks)
    missing = [check for check in PROTECTED_CHECKS if check not in universe]
    if missing:
        joined = ", ".join(missing)
        raise PolicyError(f"policy removed protected checks: {joined}")


def load_policy(path: Path) -> Policy:
    """Load and validate a verification policy from disk."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PolicyError(f"cannot read policy {path}: {exc}") from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PolicyError(f"invalid policy JSON: {exc}") from exc
    root = _as_dict(payload, "policy")
    schema_version = _as_int(root.get("schema_version"), "schema_version")
    if schema_version != SCHEMA_VERSION:
        raise PolicyError(f"unsupported policy schema_version: {schema_version}")
    policy_path = _as_str(root.get("policy_path"), "policy_path")
    if policy_path != POLICY_PATH:
        raise PolicyError(f"policy_path must be {POLICY_PATH}")
    baseline_checks = _as_str_list(root.get("baseline_checks"), "baseline_checks")
    if not baseline_checks:
        raise PolicyError("baseline_checks must not be empty")

    classes_raw = _as_dict(root.get("classes"), "classes")
    missing_classes = [name for name in RISK_CLASSES if name not in classes_raw]
    if missing_classes:
        raise PolicyError(f"policy is missing risk classes: {', '.join(missing_classes)}")
    extra_classes = sorted(set(classes_raw) - set(RISK_CLASSES))
    if extra_classes:
        raise PolicyError(f"policy has unknown risk classes: {', '.join(extra_classes)}")
    classes: dict[str, ClassPolicy] = {}
    for name in RISK_CLASSES:
        classes[name] = _as_class_policy(name, classes_raw[name])

    rules_raw = _as_list(root.get("path_rules"), "path_rules")
    if not rules_raw:
        raise PolicyError("path_rules must not be empty")
    path_rules: list[PathRule] = []
    for index, item in enumerate(rules_raw):
        rule = _as_dict(item, f"path_rules[{index}]")
        class_name = _as_str(rule.get("class"), f"path_rules[{index}].class")
        if class_name not in classes:
            raise PolicyError(f"path_rules[{index}] references unknown class {class_name}")
        patterns = _as_str_list(rule.get("patterns"), f"path_rules[{index}].patterns")
        if not patterns:
            raise PolicyError(f"path_rules[{index}].patterns must not be empty")
        path_rules.append(PathRule(class_name=class_name, patterns=patterns))

    policy = Policy(
        schema_version=schema_version,
        policy_path=policy_path,
        digest=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        baseline_checks=baseline_checks,
        classes=classes,
        path_rules=tuple(path_rules),
        acknowledged_path_downgrades=_as_path_downgrades(root.get("acknowledged_path_downgrades")),
    )
    _validate_protected_checks(policy)
    return policy


def classify_path(path: str, policy: Policy) -> str:
    """Classify one normalized repository path using ordered path rules."""
    for rule in policy.path_rules:
        if any(_path_matches(path, pattern) for pattern in rule.patterns):
            return rule.class_name
    return "unknown"


def classify_paths(paths: Iterable[str], policy: Policy) -> Classification:
    """Classify changed paths and return the highest-risk class."""
    normalized: list[str] = []
    for raw in paths:
        if raw.strip():
            normalized.append(_normalize_path(raw, "changed file"))
    unique = tuple(sorted(set(normalized)))
    if not unique:
        raise VerificationError("no changed files detected")

    per_file: list[tuple[str, str]] = []
    classes: set[str] = set()
    for path in unique:
        class_name = classify_path(path, policy)
        per_file.append((path, class_name))
        classes.add(class_name)

    risk = max(classes, key=lambda name: (policy.classes[name].severity, CLASS_RANK[name]))
    secondary = tuple(sorted(classes - {risk}, key=lambda name: CLASS_RANK[name]))
    unknown = tuple(path for path, class_name in per_file if class_name == "unknown")
    return Classification(
        risk=risk,
        per_file=tuple(per_file),
        secondary_classes=secondary,
        unknown_paths=unknown,
        changed_files=unique,
    )


def parse_scope(body: str) -> tuple[str, ...] | None:
    """Parse the machine-readable scope block from a pull-request body."""
    if not body.strip():
        return None
    if SCOPE_START not in body or SCOPE_END not in body:
        return None
    if body.count(SCOPE_START) != 1 or body.count(SCOPE_END) != 1:
        raise ScopeError("verification scope block must appear exactly once")
    start = body.index(SCOPE_START) + len(SCOPE_START)
    end = body.index(SCOPE_END)
    if end < start:
        raise ScopeError("verification scope markers are out of order")
    block = body[start:end].strip()
    if not block:
        raise ScopeError("verification scope block is empty")
    try:
        payload = json.loads(block)
    except json.JSONDecodeError as exc:
        raise ScopeError(f"verification scope is not valid JSON: {exc}") from exc
    items = _as_list(payload, "verification scope")
    if not items:
        raise ScopeError("verification scope must declare at least one path")
    declared: list[str] = []
    for index, item in enumerate(items):
        raw = _as_str(item, f"verification scope[{index}]")
        normalized = _normalize_path(raw, f"verification scope[{index}]")
        if normalized not in declared:
            declared.append(normalized)
    return tuple(declared)


def validate_scope(declared: tuple[str, ...] | None, changed: Sequence[str]) -> ScopeValidation:
    """Require every changed file to be covered by the declared scope."""
    if declared is None:
        return ScopeValidation(
            declared=None,
            errors=("missing machine-readable verification scope block",),
            advisories=(),
        )
    if not changed:
        return ScopeValidation(
            declared=declared,
            errors=("no changed files detected",),
            advisories=(),
        )
    uncovered = [
        path for path in changed if not any(_path_matches(path, prefix) for prefix in declared)
    ]
    errors: list[str] = []
    if uncovered:
        errors.append("changed files outside declared scope: " + ", ".join(uncovered))
    unused = [
        prefix for prefix in declared if not any(_path_matches(path, prefix) for path in changed)
    ]
    advisories: list[str] = []
    if unused:
        advisories.append("declared scope entries matched no changed files: " + ", ".join(unused))
    return ScopeValidation(declared=declared, errors=tuple(errors), advisories=tuple(advisories))


def evaluate_policy_guard(
    policy: Policy,
    changed: Sequence[str],
    labels: Sequence[str],
    existed_on_base: bool,
) -> PolicyGuard:
    """Require an explicit label when the policy file changes after bootstrap."""
    policy_changed = policy.policy_path in set(changed)
    if not policy_changed:
        return PolicyGuard(changed=False, allowed=True, errors=())
    if not existed_on_base:
        return PolicyGuard(changed=True, allowed=True, errors=())
    normalized_labels = {label.strip().lower() for label in labels}
    if POLICY_CHANGE_LABEL not in normalized_labels:
        return PolicyGuard(
            changed=True,
            allowed=False,
            errors=(f"{policy.policy_path} changed without the '{POLICY_CHANGE_LABEL}' label",),
        )
    return PolicyGuard(changed=True, allowed=True, errors=())


def evaluate_policy_weakening(base: Policy, proposed: Policy) -> tuple[str, ...]:
    """Reject a proposed policy that lowers any class's gates.

    The base policy is authoritative for the current pull request. This guard
    compares the policy carried by the head commit so a policy edit cannot
    quietly drop a check, lower a severity, disable review, or remove the
    human-approval boundary for a future run.
    """
    errors: list[str] = []
    for risk in RISK_CLASSES:
        base_checks = set(required_checks(base, risk))
        proposed_checks = set(required_checks(proposed, risk))
        missing = sorted(base_checks - proposed_checks)
        if missing:
            errors.append(
                f"proposed policy removes required checks for {risk}: {', '.join(missing)}"
            )
        base_class = base.classes[risk]
        proposed_class = proposed.classes[risk]
        if proposed_class.severity < base_class.severity:
            errors.append(
                f"proposed policy lowers severity for {risk}: "
                f"{base_class.severity} -> {proposed_class.severity}"
            )
        if base_class.review_required and not proposed_class.review_required:
            errors.append(f"proposed policy disables review for {risk}")
        if base_class.human_approvals and not proposed_class.human_approvals:
            errors.append(f"proposed policy removes human approvals for {risk}")
    errors.extend(evaluate_path_weakening(base, proposed))
    return tuple(errors)


_PROBE_CHARACTERS = ("p", "a", "z", "0", "9", "A", "_")


def _instantiate_glob(pattern: str) -> str:
    """Instantiate a shell-style glob as one concrete path.

    Each metacharacter is replaced by a literal that satisfies it. Character
    classes are resolved by testing candidate characters against the class with
    the same matcher the ratchet uses, so negation and ranges are honoured. An
    unterminated or unsatisfiable class raises ``PolicyError``: a pattern the
    ratchet cannot probe must fail loudly rather than silently drop out of
    coverage.
    """
    out: list[str] = []
    index = 0
    length = len(pattern)
    while index < length:
        char = pattern[index]
        if char == "*":
            while index < length and pattern[index] == "*":
                index += 1
            out.append("probe")
            continue
        if char == "?":
            out.append("p")
            index += 1
            continue
        if char == "[":
            end = pattern.find("]", index + 1)
            if end == -1:
                raise PolicyError(f"policy pattern {pattern!r} has an unterminated character class")
            class_text = pattern[index : end + 1]
            if len(class_text) == 2:
                raise PolicyError(f"policy pattern {pattern!r} has an empty character class")
            chosen = next(
                (
                    candidate
                    for candidate in _PROBE_CHARACTERS
                    if fnmatchcase(candidate, class_text)
                ),
                None,
            )
            if chosen is None:
                raise PolicyError(f"policy pattern {pattern!r} has no satisfiable character")
            out.append(chosen)
            index = end + 1
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _probe_path(pattern: str) -> str:
    """Derive a concrete path that the given pattern actually matches.

    The ratchet re-classifies every base pattern under the proposed policy, so
    the probe stands in for that pattern. A probe that falls through to a
    different rule would turn the check into a no-op, so the result is verified
    against the pattern and a mismatch raises ``PolicyError``.

    A directory pattern is probed with a file inside it, so a prefix rule and a
    glob rule ending in ``/`` are both exercised the way real files are.
    """
    matchable = pattern.rstrip("/")
    has_glob = any(char in matchable for char in "*?[")
    probe = _instantiate_glob(matchable) if has_glob else matchable
    probe = probe.replace("//", "/").strip("/")
    if not probe or ".." in probe.split("/"):
        raise PolicyError(f"policy pattern {pattern!r} produced an invalid probe path")
    if not _path_matches(probe, matchable):
        raise PolicyError(f"policy pattern {pattern!r} cannot be probed for coverage")
    if pattern.endswith("/"):
        probe = f"{probe}/__probe__.txt"
    return probe


def evaluate_path_weakening(base: Policy, proposed: Policy) -> tuple[str, ...]:
    """Reject a proposed policy that silently lowers any path's risk class.

    Class-level checks cannot see a path moving between rules. For example,
    routing ``.github/`` to ``docs`` keeps every class definition intact while
    removing the gates that path used to require. Each base pattern is
    re-classified under the proposed policy and must not lose severity unless
    the downgrade is declared in ``acknowledged_path_downgrades`` with a reason.
    """
    errors: list[str] = []
    acknowledged = {
        (item.pattern, item.from_class, item.to_class): item.reason
        for item in proposed.acknowledged_path_downgrades
    }
    seen: set[str] = set()
    for rule in base.path_rules:
        for pattern in rule.patterns:
            if pattern in seen:
                continue
            seen.add(pattern)
            probe = _probe_path(pattern)
            base_class = classify_path(probe, base)
            head_class = classify_path(probe, proposed)
            drop = base.classes[base_class].severity - proposed.classes[head_class].severity
            if drop <= 0:
                continue
            if (pattern, base_class, head_class) not in acknowledged:
                errors.append(
                    f"proposed policy lowers classification for {pattern!r}: "
                    f"{base_class} -> {head_class}"
                )
    known_patterns = {pattern for rule in base.path_rules for pattern in rule.patterns}
    for item in proposed.acknowledged_path_downgrades:
        where = f"acknowledged path downgrade {item.pattern!r}"
        if not item.reason.strip():
            errors.append(f"{where} has no reason")
        if item.pattern not in known_patterns:
            errors.append(f"{where} does not name a policy path pattern")
            continue
        if item.from_class not in proposed.classes or item.to_class not in proposed.classes:
            errors.append(f"{where} names an unknown class")
            continue
        if proposed.classes[item.to_class].severity >= proposed.classes[item.from_class].severity:
            errors.append(f"{where} does not describe a real downgrade")
            continue
        actual = classify_path(_probe_path(item.pattern), proposed)
        if actual != item.to_class:
            errors.append(f"{where} declares {item.to_class} but classifies as {actual}")
    return tuple(errors)


def required_checks(policy: Policy, risk: str) -> tuple[str, ...]:
    """Return baseline plus risk-specific checks, preserving declaration order."""
    class_policy = policy.classes[risk]
    ordered: list[str] = []
    for check in (*policy.baseline_checks, *class_policy.extra_checks):
        if check not in ordered:
            ordered.append(check)
    return tuple(ordered)


def _scope_for(
    body: str, changed: tuple[str, ...]
) -> tuple[tuple[str, ...] | None, tuple[str, ...], tuple[str, ...]]:
    """Parse and validate scope, converting malformed declarations into errors."""
    try:
        declared = parse_scope(body)
        validation = validate_scope(declared, changed)
    except ScopeError as exc:
        return None, (str(exc),), ()
    return validation.declared, validation.errors, validation.advisories


def build_plan(
    policy: Policy,
    changed_files: Iterable[str],
    pr_body: str,
    labels: Sequence[str],
    *,
    policy_existed_on_base: bool,
    event: str,
    repository: str,
    pr_number: int,
    base_sha: str,
    head_sha: str,
    proposed_policy: Policy | None = None,
) -> Plan:
    """Build the complete verification plan."""
    classification = classify_paths(changed_files, policy)
    declared, scope_errors, scope_advisories = _scope_for(pr_body, classification.changed_files)
    guard = evaluate_policy_guard(
        policy, classification.changed_files, labels, policy_existed_on_base
    )
    weakening = (
        evaluate_policy_weakening(policy, proposed_policy) if proposed_policy is not None else ()
    )
    class_policy = policy.classes[classification.risk]
    checks = required_checks(policy, classification.risk)

    errors = list(scope_errors) + list(guard.errors) + list(weakening)
    advisories = list(scope_advisories)
    if (
        proposed_policy is not None
        and policy_existed_on_base
        and policy.digest == proposed_policy.digest
        and policy.policy_path in set(classification.changed_files)
    ):
        errors.append(
            f"{policy.policy_path} changed but the base and proposed policies are identical; "
            "the base policy must be read from the base revision"
        )
    if classification.unknown_paths:
        joined = ", ".join(classification.unknown_paths)
        errors.append(f"unclassified changed paths: {joined}; add a path rule")
    if guard.changed and guard.allowed:
        advisories.append(f"{policy.policy_path} changed; policy-change guard satisfied")
    if not checks:
        errors.append("policy resolved zero required checks")

    status = "fail" if errors else ("review" if class_policy.review_required else "pass")
    return Plan(
        schema_version=SCHEMA_VERSION,
        event=event,
        repository=repository,
        pr_number=pr_number,
        base_sha=base_sha,
        head_sha=head_sha,
        policy_path=policy.policy_path,
        policy_digest=policy.digest,
        proposed_policy_digest=None if proposed_policy is None else proposed_policy.digest,
        policy_existed_on_base=policy_existed_on_base,
        policy_changed=guard.changed,
        risk=classification.risk,
        secondary_classes=classification.secondary_classes,
        per_file=classification.per_file,
        unknown_paths=classification.unknown_paths,
        changed_files=classification.changed_files,
        declared_scope=declared,
        scope_errors=scope_errors,
        scope_advisories=scope_advisories,
        required_checks=checks,
        review_required=class_policy.review_required,
        human_approvals=class_policy.human_approvals,
        status=status,
        errors=tuple(errors),
        advisories=tuple(advisories),
    )


def _merge_observation(old: CheckObservation, new: CheckObservation) -> CheckObservation:
    """Fail closed when GitHub reports duplicate check-runs with the same name."""
    if old.status != "completed" and new.status == "completed":
        return new
    if old.status == "completed" and new.status != "completed":
        return old
    if (
        old.status == "completed"
        and new.status == "completed"
        and old.conclusion == "success"
        and new.conclusion != "success"
    ):
        return new
    return old


def load_checks(path: Path) -> dict[str, CheckObservation]:
    """Load JSONL check-runs into a fail-closed name-indexed map."""
    observations: dict[str, CheckObservation] = {}
    if not path.exists():
        return observations
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise VerificationError(f"cannot read checks {path}: {exc}") from exc
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise VerificationError(f"checks line {line_number}: invalid JSON: {exc}") from exc
        data = _as_dict(payload, f"checks line {line_number}")
        conclusion_value = data.get("conclusion")
        details_value = data.get("details_url")
        observation = CheckObservation(
            name=_as_str(data.get("name"), f"checks line {line_number}.name"),
            status=_as_str(data.get("status"), f"checks line {line_number}.status"),
            conclusion=(
                "" if conclusion_value is None else _as_str(conclusion_value, "conclusion")
            ),
            details_url="" if details_value is None else _as_str(details_value, "details_url"),
        )
        existing = observations.get(observation.name)
        observations[observation.name] = (
            observation if existing is None else _merge_observation(existing, observation)
        )
    return observations


def evaluate_checks(
    required: Sequence[str], observations: Mapping[str, CheckObservation]
) -> CheckEvaluation:
    """Evaluate required checks against observed check-runs."""
    missing: list[str] = []
    pending: list[str] = []
    failed: list[str] = []
    for name in required:
        observation = observations.get(name)
        if observation is None:
            missing.append(name)
        elif observation.status != "completed":
            pending.append(name)
        elif observation.conclusion != "success":
            failed.append(name)
    return CheckEvaluation(missing=tuple(missing), pending=tuple(pending), failed=tuple(failed))


def load_reviews(path: Path) -> tuple[Review, ...]:
    """Load JSONL pull-request reviews."""
    if not path.exists():
        return ()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise VerificationError(f"cannot read reviews {path}: {exc}") from exc
    reviews: list[Review] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise VerificationError(f"reviews line {line_number}: invalid JSON: {exc}") from exc
        data = _as_dict(payload, f"reviews line {line_number}")
        author = ""
        user_value = data.get("user")
        if isinstance(user_value, dict):
            login_value = user_value.get("login")
            if isinstance(login_value, str):
                author = login_value
        reviews.append(
            Review(
                state=_as_str(data.get("state"), f"reviews line {line_number}.state"),
                commit_id=_as_str(data.get("commit_id"), f"reviews line {line_number}.commit_id"),
                author=author,
            )
        )
    return tuple(reviews)


def evaluate_approvals(
    reviews: Sequence[Review],
    *,
    head_sha: str,
    author: str,
    required: int,
    enforce: bool,
) -> ApprovalEvaluation:
    """Evaluate non-author approvals at the exact head commit."""
    if not enforce:
        return ApprovalEvaluation(required=0, approved_by=(), changes_requested_by=())
    relevant = [review for review in reviews if review.commit_id == head_sha]
    approved = sorted(
        {
            review.author
            for review in relevant
            if review.state == "APPROVED" and review.author and review.author != author
        }
    )
    changes = sorted(
        {
            review.author
            for review in relevant
            if review.state == "CHANGES_REQUESTED" and review.author and review.author != author
        }
    )
    return ApprovalEvaluation(
        required=required,
        approved_by=tuple(approved),
        changes_requested_by=tuple(changes),
    )


def build_evidence(
    plan: Mapping[str, object],
    checks: Mapping[str, CheckObservation],
    reviews: Sequence[Review],
    *,
    event: str,
    head_sha: str,
    author: str,
    generated_at: str,
) -> Evidence:
    """Evaluate a plan into a fail-closed evidence bundle."""
    risk = _as_str(plan.get("risk", "unknown"), "plan.risk")
    required = _as_str_list(plan.get("required_checks", []), "plan.required_checks")
    plan_status = _as_str(plan.get("status", "fail"), "plan.status")
    plan_errors = _as_str_list(plan.get("errors", []), "plan.errors")
    plan_advisories = _as_str_list(plan.get("advisories", []), "plan.advisories")
    unknown_paths = _as_str_list(plan.get("unknown_paths", []), "plan.unknown_paths")
    review_required = _as_bool(plan.get("review_required", False), "plan.review_required")
    human_approvals = _as_str_list(plan.get("human_approvals", []), "plan.human_approvals")

    check_evaluation = evaluate_checks(required, checks)
    enforce_approvals = event != "merge_group"
    approvals_required = 1 if review_required and enforce_approvals else 0
    approval_evaluation = evaluate_approvals(
        reviews,
        head_sha=head_sha,
        author=author,
        required=approvals_required,
        enforce=enforce_approvals,
    )

    hard_exceptions: list[str] = list(plan_errors)
    hard_exceptions.extend(f"missing required check: {name}" for name in check_evaluation.missing)
    hard_exceptions.extend(f"failed required check: {name}" for name in check_evaluation.failed)
    if unknown_paths:
        hard_exceptions.append("unclassified paths: " + ", ".join(unknown_paths))
    if plan_status == "fail" and not plan_errors:
        hard_exceptions.append("verification plan failed")
    if approval_evaluation.changes_requested_by:
        joined = ", ".join(f"@{name}" for name in approval_evaluation.changes_requested_by)
        hard_exceptions.append(f"changes requested at head commit by: {joined}")

    # A missing approval is a review boundary, not a technical gate outcome.
    # Branch protection enforces required approvals at merge time; duplicating
    # that here would leave every review-required change red on a repository
    # with zero required approvals, and would make a green verification verdict
    # look like a mergeability claim. The shortfall is surfaced instead.
    approval_shortfall = len(approval_evaluation.approved_by) < approvals_required
    needs_human_review = approval_shortfall or bool(approval_evaluation.changes_requested_by)

    pending_exceptions = [f"pending required check: {name}" for name in check_evaluation.pending]
    exceptions = tuple(hard_exceptions + pending_exceptions)
    if hard_exceptions:
        verdict = "fail"
    elif pending_exceptions:
        verdict = "pending"
    else:
        verdict = "pass"

    advisories = list(plan_advisories)
    advisories.extend(f"human approval boundary: {note}" for note in human_approvals)
    if approval_shortfall:
        advisories.append(
            "human approval incomplete: "
            f"{len(approval_evaluation.approved_by)}/{approvals_required} non-author "
            "approvals at the head commit"
        )
    if approvals_required and approval_evaluation.ok:
        joined = ", ".join(f"@{name}" for name in approval_evaluation.approved_by)
        advisories.append(f"human approval satisfied by: {joined}")
    if review_required and not enforce_approvals:
        advisories.append(
            "merge queue run: human approval enforcement is deferred to the pull request run"
        )

    check_rows: list[CheckObservation] = []
    for name in required:
        observation = checks.get(name)
        if observation is None:
            check_rows.append(
                CheckObservation(name=name, status="missing", conclusion="missing", details_url="")
            )
        else:
            check_rows.append(observation)

    return Evidence(
        schema_version=SCHEMA_VERSION,
        generated_at=generated_at,
        event=event,
        repository=_as_str(plan.get("repository", ""), "plan.repository"),
        pr_number=_as_int(plan.get("pr_number", 0), "plan.pr_number"),
        base_sha=_as_str(plan.get("base_sha", ""), "plan.base_sha"),
        head_sha=head_sha,
        risk=risk,
        secondary_classes=_as_str_list(plan.get("secondary_classes", []), "plan.secondary_classes"),
        changed_files=_as_str_list(plan.get("changed_files", []), "plan.changed_files"),
        declared_scope=_optional_str_list(plan.get("declared_scope"), "plan.declared_scope"),
        required_checks=required,
        checks=tuple(check_rows),
        missing_checks=check_evaluation.missing,
        pending_checks=check_evaluation.pending,
        failed_checks=check_evaluation.failed,
        approvals_required=approvals_required,
        approved_by=approval_evaluation.approved_by,
        changes_requested_by=approval_evaluation.changes_requested_by,
        review_required=review_required,
        human_approvals=human_approvals,
        needs_human_review=needs_human_review,
        plan_status=plan_status,
        verdict=verdict,
        exceptions=exceptions,
        advisories=tuple(advisories),
        policy_digest=_as_str(plan.get("policy_digest", ""), "plan.policy_digest"),
    )


def _optional_str_list(value: object, where: str) -> tuple[str, ...] | None:
    """Return a tuple of strings, or None when the value is null/missing."""
    if value is None:
        return None
    return _as_str_list(value, where)


def _report_check_rows(value: object) -> list[tuple[str, str, str]]:
    """Extract report rows from evidence checks."""
    rows: list[tuple[str, str, str]] = []
    for index, item in enumerate(_as_list(value, "evidence.checks")):
        data = _as_dict(item, f"evidence.checks[{index}]")
        rows.append(
            (
                _as_str(data.get("name", ""), f"evidence.checks[{index}].name"),
                _as_str(data.get("status", ""), f"evidence.checks[{index}].status"),
                _as_str(data.get("conclusion", ""), f"evidence.checks[{index}].conclusion"),
            )
        )
    return rows


def render_report(evidence: Mapping[str, object]) -> str:
    """Render the exception-only pull-request report."""
    verdict = _as_str(evidence.get("verdict", "fail"), "evidence.verdict").upper()
    risk = _as_str(evidence.get("risk", "unknown"), "evidence.risk")
    head_sha = _as_str(evidence.get("head_sha", ""), "evidence.head_sha")
    required = _as_str_list(evidence.get("required_checks", []), "evidence.required_checks")
    exceptions = _as_str_list(evidence.get("exceptions", []), "evidence.exceptions")
    advisories = _as_str_list(evidence.get("advisories", []), "evidence.advisories")
    review_required = _as_bool(evidence.get("review_required", False), "evidence.review_required")
    needs_human_review = _as_bool(
        evidence.get("needs_human_review", False), "evidence.needs_human_review"
    )
    human_approvals = _as_str_list(evidence.get("human_approvals", []), "evidence.human_approvals")
    approved_by = _as_str_list(evidence.get("approved_by", []), "evidence.approved_by")
    approvals_required = _as_int(
        evidence.get("approvals_required", 0), "evidence.approvals_required"
    )

    lines = [REPORT_MARKER, "", f"## Verification: {verdict} — risk: `{risk}`", ""]
    lines.append(
        f"**Head:** `{head_sha}` · **Required gates:** {len(required)} · "
        f"**Review:** {'required' if review_required else 'automatic'}"
    )
    lines.append("")

    if verdict == "PASS" and not exceptions:
        lines.append(f"No exceptions. All {len(required)} required gates passed.")
        if review_required:
            lines.extend(["", "### Human approval boundary"])
            lines.extend(f"- {note}" for note in human_approvals)
            joined = ", ".join(f"@{name}" for name in approved_by) or "none"
            lines.append(
                f"- Approvals at head commit: {len(approved_by)}/{approvals_required} ({joined})"
            )
        if needs_human_review:
            missing = max(approvals_required - len(approved_by), 0)
            lines.extend(["", "### Merge gate"])
            lines.append(
                "- This verdict covers the required technical gates only. "
                "It is not a mergeability claim."
            )
            lines.append(
                f"- Missing {missing} of {approvals_required} required non-author "
                "approval(s) at the head commit. This workflow does not read repository "
                "branch protection, so it does not claim the merge will be blocked: the "
                "platform's settings decide that, independently of this verdict."
            )
            lines.append(
                f"- Applied the `{NEEDS_HUMAN_REVIEW_LABEL}` label so the gap is "
                "visible without making the verification verdict red."
            )
        return "\n".join(lines) + "\n"

    lines.append("### Exceptions")
    if exceptions:
        lines.extend(f"- {item}" for item in exceptions)
    else:
        lines.append("- None recorded.")
    lines.append("")

    if review_required:
        lines.append("### Human approval boundary")
        lines.extend(f"- {note}" for note in human_approvals)
        joined = ", ".join(f"@{name}" for name in approved_by) or "none"
        lines.append(
            f"- Approvals at head commit: {len(approved_by)}/{approvals_required} ({joined})"
        )
        lines.append("")

    if needs_human_review:
        lines.append(
            f"The `{NEEDS_HUMAN_REVIEW_LABEL}` label is applied while a required "
            "non-author approval is outstanding."
        )
        lines.append("")

    rows = _report_check_rows(evidence.get("checks", []))
    if rows:
        lines.append("<details><summary>Required checks</summary>")
        lines.append("")
        lines.append("| Check | Status | Conclusion |")
        lines.append("| --- | --- | --- |")
        lines.extend(f"| `{name}` | {status} | {conclusion} |" for name, status, conclusion in rows)
        lines.append("")
        lines.append("</details>")
        lines.append("")

    if advisories:
        lines.append("<details><summary>Advisories</summary>")
        lines.append("")
        lines.extend(f"- {item}" for item in advisories)
        lines.append("")
        lines.append("</details>")
        lines.append("")

    if verdict == "PENDING":
        lines.append("The verification workflow will retry while required checks are pending.")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _read_json_object(path: Path) -> dict[str, object]:
    """Read a JSON object from disk, returning an empty object when absent."""
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise VerificationError(f"cannot read {path}: {exc}") from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise VerificationError(f"invalid JSON in {path}: {exc}") from exc
    return _as_dict(payload, str(path))


def _read_lines(path: Path) -> tuple[str, ...]:
    """Read newline-separated paths, ignoring blank lines."""
    if not path.exists():
        raise VerificationError(f"changed files file not found: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise VerificationError(f"cannot read {path}: {exc}") from exc
    return tuple(line.strip() for line in text.splitlines() if line.strip())


def _write_text(path: Path, content: str) -> None:
    """Write text, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _pr_metadata(pr: Mapping[str, object]) -> tuple[str, tuple[str, ...], str, int]:
    """Extract body, labels, author, and number from a pull-request payload."""
    body_value = pr.get("body")
    body = "" if body_value is None else _as_str(body_value, "pr.body")
    labels: list[str] = []
    labels_value = pr.get("labels")
    if isinstance(labels_value, list):
        for item in labels_value:
            if isinstance(item, dict):
                name_value = item.get("name")
                if isinstance(name_value, str):
                    labels.append(name_value)
    author = ""
    user_value = pr.get("user")
    if isinstance(user_value, dict):
        login_value = user_value.get("login")
        if isinstance(login_value, str):
            author = login_value
    number_value = pr.get("number")
    number = (
        number_value if isinstance(number_value, int) and not isinstance(number_value, bool) else 0
    )
    return body, tuple(labels), author, number


def _cmd_plan(args: argparse.Namespace) -> int:
    """Execute the ``plan`` command."""
    policy = load_policy(Path(str(args.policy)))
    proposed_policy = load_policy(Path(str(args.head_policy))) if args.head_policy else None
    changed = _read_lines(Path(str(args.changed_files)))
    pr = _read_json_object(Path(str(args.pr_json)))
    body, labels, _author, number = _pr_metadata(pr)
    pr_number = int(args.pr_number) or number
    plan = build_plan(
        policy,
        changed,
        body,
        labels,
        policy_existed_on_base=str(args.policy_existed_on_base) == "true",
        event=str(args.event),
        repository=str(args.repository),
        pr_number=pr_number,
        base_sha=str(args.base_sha),
        head_sha=str(args.head_sha),
        proposed_policy=proposed_policy,
    )
    _write_text(Path(str(args.out)), json.dumps(asdict(plan), indent=2, sort_keys=True) + "\n")
    sys.stdout.write(
        f"risk={plan.risk} status={plan.status} required={len(plan.required_checks)}\n"
    )
    for error in plan.errors:
        sys.stderr.write(f"ERROR: {error}\n")
    return 0 if plan.status in {"pass", "review"} else 1


def _cmd_evidence(args: argparse.Namespace) -> int:
    """Execute the ``evidence`` command."""
    plan = _read_json_object(Path(str(args.plan)))
    if not plan:
        plan = {
            "status": "fail",
            "risk": "unknown",
            "errors": ["plan artifact is missing or unreadable"],
            "required_checks": [],
            "review_required": True,
            "human_approvals": [],
        }
    checks = load_checks(Path(str(args.checks)))
    reviews = load_reviews(Path(str(args.reviews)))
    author = str(args.author)
    if not author:
        pr = _read_json_object(Path(str(args.pr_json))) if args.pr_json else {}
        _body, _labels, author, _number = _pr_metadata(pr)
    evidence = build_evidence(
        plan,
        checks,
        reviews,
        event=str(args.event),
        head_sha=str(args.head_sha),
        author=author,
        generated_at=datetime.now(UTC).isoformat(),
    )
    _write_text(
        Path(str(args.out)),
        json.dumps(asdict(evidence), indent=2, sort_keys=True) + "\n",
    )
    _write_text(Path(str(args.report)), render_report(asdict(evidence)))
    sys.stderr.write(
        f"verdict={evidence.verdict} missing={len(evidence.missing_checks)} "
        f"pending={len(evidence.pending_checks)} failed={len(evidence.failed_checks)}\n"
    )
    if evidence.verdict == "pass":
        return 0
    if evidence.verdict == "pending":
        return 3
    return 1


def _cmd_report(args: argparse.Namespace) -> int:
    """Execute the ``report`` command."""
    evidence = _read_json_object(Path(str(args.evidence)))
    if not evidence:
        plan = _read_json_object(Path(str(args.plan)))
        evidence = {
            "verdict": "fail",
            "risk": plan.get("risk", "unknown"),
            "required_checks": plan.get("required_checks", []),
            "exceptions": ["evidence bundle was not produced"],
            "advisories": [],
            "checks": [],
            "review_required": False,
            "human_approvals": [],
            "approved_by": [],
            "approvals_required": 0,
            "head_sha": plan.get("head_sha", ""),
        }
    _write_text(Path(str(args.out)), render_report(evidence))
    return 0


def _cmd_comment_payload(args: argparse.Namespace) -> int:
    """Execute the ``comment-payload`` command."""
    report = Path(str(args.report)).read_text(encoding="utf-8")
    payload = {"body": report}
    _write_text(Path(str(args.out)), json.dumps(payload) + "\n")
    return 0


def _cmd_label(args: argparse.Namespace) -> int:
    """Write the human-review label to apply, or an empty file when none is due."""
    evidence = _read_json_object(Path(str(args.evidence)))
    if not evidence:
        # Fail closed: without evidence we cannot prove approvals were recorded,
        # so route the pull request to a human instead of staying silent.
        _write_text(Path(str(args.out)), f"{NEEDS_HUMAN_REVIEW_LABEL}\n")
        return 0
    needs = _as_bool(evidence.get("needs_human_review", False), "evidence.needs_human_review")
    _write_text(Path(str(args.out)), f"{NEEDS_HUMAN_REVIEW_LABEL}\n" if needs else "")
    return 0


def _cmd_pr_number(args: argparse.Namespace) -> int:
    """Execute the ``pr-number-from-ref`` command."""
    match = re.search(r"(?:^|/)pr-(\d+)(?:-|$)", str(args.ref))
    if match is None:
        sys.stderr.write(f"cannot parse pull request number from ref: {args.ref}\n")
        return 1
    sys.stdout.write(match.group(1))
    return 0


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch to a verification command."""
    parser = argparse.ArgumentParser(prog="pr_verification.py")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan", help="classify risk and enforce scope")
    plan_parser.add_argument("--policy", default=POLICY_PATH)
    plan_parser.add_argument("--head-policy", default="")
    plan_parser.add_argument("--changed-files", required=True)
    plan_parser.add_argument("--pr-json", required=True)
    plan_parser.add_argument("--out", required=True)
    plan_parser.add_argument("--event", default="pull_request")
    plan_parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    plan_parser.add_argument("--pr-number", type=int, default=0)
    plan_parser.add_argument("--base-sha", required=True)
    plan_parser.add_argument("--head-sha", required=True)
    plan_parser.add_argument("--policy-existed-on-base", choices=("true", "false"), default="false")
    plan_parser.set_defaults(func=_cmd_plan)

    evidence_parser = subparsers.add_parser("evidence", help="evaluate checks and approvals")
    evidence_parser.add_argument("--plan", required=True)
    evidence_parser.add_argument("--checks", required=True)
    evidence_parser.add_argument("--reviews", required=True)
    evidence_parser.add_argument("--pr-json", default="")
    evidence_parser.add_argument("--event", default="pull_request")
    evidence_parser.add_argument("--head-sha", required=True)
    evidence_parser.add_argument("--author", default="")
    evidence_parser.add_argument("--out", required=True)
    evidence_parser.add_argument("--report", required=True)
    evidence_parser.set_defaults(func=_cmd_evidence)

    report_parser = subparsers.add_parser("report", help="render the exception-only report")
    report_parser.add_argument("--plan", required=True)
    report_parser.add_argument("--evidence", required=True)
    report_parser.add_argument("--out", required=True)
    report_parser.set_defaults(func=_cmd_report)

    payload_parser = subparsers.add_parser("comment-payload", help="build a comment payload")
    payload_parser.add_argument("--report", required=True)
    payload_parser.add_argument("--out", required=True)
    payload_parser.set_defaults(func=_cmd_comment_payload)

    label_parser = subparsers.add_parser("label", help="decide the human-review label")
    label_parser.add_argument("--evidence", required=True)
    label_parser.add_argument("--out", required=True)
    label_parser.set_defaults(func=_cmd_label)

    ref_parser = subparsers.add_parser("pr-number-from-ref", help="parse a merge-group ref")
    ref_parser.add_argument("--ref", required=True)
    ref_parser.set_defaults(func=_cmd_pr_number)

    parsed = parser.parse_args(argv)
    try:
        return int(parsed.func(parsed))
    except VerificationError as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
