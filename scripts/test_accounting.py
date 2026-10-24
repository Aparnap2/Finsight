"""Test accounting gate (APA-94 G1): make the collected/executed split provable.

The suite's *collected* count is not the suite's *executed* count. Tests are
skipped (environment-gated), deselected (marker filters), expected to fail
(xfail), or never collected at all (a file no workflow selects). A green CI
run that does not report this split cannot distinguish "the suite passed"
from "the suite ran less than it appears to".

This gate closes that gap. It reads the accounting report produced by
``tests/accounting_plugin.py`` together with a manifest that declares what
*should* run, and fails the job when the difference between what was
collected and what was executed is **not accounted for** by a declared
reason.

Failure semantics (a skipped test is not a passing test):

- FAIL (exit 2, ``NO_REPORT``) when the accounting report is missing or
  unreadable — an unmeasured run cannot be certified.
- FAIL (exit 2, ``COLLECTION_ERROR``) when the report records a collection
  error — a module that failed to import is a broken suite, not a skip.
- FAIL (exit 2, ``UNEXECUTED_TESTS``) when tests were collected but neither
  passed, failed, skipped, nor xfailed — an unexplained omission.
- FAIL (exit 2, ``UNDECLARED_SKIP``) when a skipped test's reason is not
  covered by the manifest's declared skip reasons — a new skip reason is a
  change in what the suite actually verifies, and must be reviewed.
- FAIL (exit 2, ``UNDECLARED_FILE``) when a test file exists in the
  manifest's declared scope but was not collected by the run — the file was
  expected to execute and did not.
- PASS (exit 0) otherwise, printing the collected/executed split and
  writing a machine-readable summary.

The gate never inspects the working tree itself; the manifest is the
declaration of what *should* run. Keeping the two separate is what makes an
omission detectable at all: a file silently dropped from CI is a difference
between the manifest and reality.

Test failures themselves are NOT this script's question: the pytest step
already fails on those (pipefail). stdlib only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_URL_RE = re.compile(r"https?://\S+")
_NUMBER_RE = re.compile(r"\d+")

#: Outcomes that count as "the test was accounted for".
_ACCOUNTED = frozenset({"passed", "failed", "skipped", "xfailed", "xpassed", "error"})

#: Outcomes that are *not* a successful execution of the test body.
_NOT_EXECUTED = frozenset({"skipped", "xfailed"})


class AccountError(Exception):
    """Raised when the accounting report cannot be read."""


def load_report(path: Path) -> dict[str, Any]:
    """Load the accounting report produced by the pytest plugin.

    Raises:
        AccountError: when the report is missing, unreadable, or malformed.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AccountError(f"NO_REPORT missing accounting report: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise AccountError(f"NO_REPORT unreadable accounting report: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise AccountError(f"NO_REPORT malformed accounting report: {path}")
    return payload


def load_manifest(path: Path) -> dict[str, Any]:
    """Load the accounting manifest (declared reasons and expected files)."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AccountError(f"NO_REPORT missing accounting manifest: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise AccountError(f"NO_REPORT unreadable accounting manifest: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise AccountError(f"NO_REPORT malformed accounting manifest: {path}")
    return payload


def _normalise(reason: str) -> str:
    """Reduce a reason to a comparable phrase.

    Skip reasons embed counts, paths, and URLs. Comparing them verbatim
    would make the manifest brittle, so the leading prose is kept and
    volatile details are stripped.
    """
    text = reason.strip().lower()
    text = _URL_RE.sub("<url>", text)
    text = _NUMBER_RE.sub("<n>", text)
    return text.strip()


def _matches(reason: str, patterns: list[str]) -> bool:
    """Return True when a skip reason matches any declared pattern."""
    normalised = _normalise(reason)
    for pattern in patterns:
        candidate = _normalise(pattern)
        if candidate and (normalised == candidate or candidate in normalised):
            return True
    return False


def _undeclared_skips(
    skipped_reasons: dict[str, str],
    declared: list[str],
) -> list[str]:
    """Return skips whose reason is not covered by the manifest."""
    problems: list[str] = []
    for nodeid, reason in sorted(skipped_reasons.items()):
        if not reason:
            problems.append(f"UNDECLARED_SKIP {nodeid}: skip without a reason")
        elif not _matches(reason, declared):
            problems.append(f"UNDECLARED_SKIP {nodeid}: {reason}")
    return problems


def evaluate(report: dict[str, Any], manifest: dict[str, Any]) -> list[str]:
    """Return the list of gate violations for one run (empty means pass).

    The manifest declares:
    - ``skip_reasons``: phrases that legitimately explain a skip.
    - ``expected_files``: test files that MUST have been collected.
    - ``deselect_allowance``: how many marker-deselected tests are allowed.
    """
    problems: list[str] = []
    declared_reasons = [str(item) for item in manifest.get("skip_reasons", [])]

    for error in report.get("collection_errors", []):
        problems.append(f"COLLECTION_ERROR {error}")

    outcomes = report.get("outcomes", {})
    executed = sum(counts for outcome, counts in outcomes.items() if outcome in _ACCOUNTED)
    collected = int(report.get("collected", 0))
    deselected = int(report.get("deselected", 0))
    if collected > executed:
        problems.append(
            f"UNEXECUTED_TESTS collected={collected} accounted={executed} "
            f"unaccounted={collected - executed}"
        )

    allowance = manifest.get("deselect_allowance")
    if allowance is not None and deselected > int(allowance):
        problems.append(f"DESELECT_BUDGET_EXCEEDED deselected={deselected} budget={allowance}")

    problems.extend(_undeclared_skips(report.get("skipped_reasons", {}), declared_reasons))

    collected_nodeids = set(report.get("collected_nodeids", []))
    for path in manifest.get("expected_files", []):
        if not any(nodeid.startswith(path) for nodeid in collected_nodeids):
            problems.append(f"UNDECLARED_FILE {path}: expected to be collected")

    return problems


def main(argv: list[str] | None = None) -> int:
    """Entry point: evaluate one accounting report against the manifest."""
    parser = argparse.ArgumentParser(
        description="Fail CI runs whose collected/executed split is unexplained."
    )
    parser.add_argument("report", help="Path to the accounting report JSON.")
    parser.add_argument(
        "--manifest",
        default=None,
        help="Path to the accounting manifest (skip reasons, expected files).",
    )
    parser.add_argument(
        "--job",
        default=None,
        help="Job key within the manifest to evaluate (default: the whole manifest).",
    )
    parser.add_argument(
        "--summary",
        default=None,
        help="Path to write the machine-readable accounting summary.",
    )
    args = parser.parse_args(argv)

    try:
        report = load_report(Path(args.report))
    except AccountError as exc:
        print(str(exc))
        return 2

    manifest: dict[str, Any] = {}
    if args.manifest:
        try:
            manifest = load_manifest(Path(args.manifest))
        except AccountError as exc:
            print(str(exc))
            return 2
        if args.job:
            jobs = manifest.get("jobs", {})
            if args.job not in jobs:
                print(f"NO_REPORT unknown job in manifest: {args.job}")
                return 2
            manifest = jobs[args.job]
        elif "jobs" in manifest:
            # A manifest with several jobs and no explicit selection cannot
            # be evaluated: the skip reasons of one job are not the skip
            # reasons of another.
            print("NO_REPORT manifest holds several jobs; pass --job")
            return 2

    outcomes = report.get("outcomes", {})
    collected = int(report.get("collected", 0))
    deselected = int(report.get("deselected", 0))
    executed = sum(counts for outcome, counts in outcomes.items() if outcome in _ACCOUNTED)
    passed = int(outcomes.get("passed", 0))
    failed = int(outcomes.get("failed", 0))
    skipped = int(outcomes.get("skipped", 0))
    xfailed = int(outcomes.get("xfailed", 0))
    xpassed = int(outcomes.get("xpassed", 0))
    errors = int(outcomes.get("error", 0))

    print(
        f"collected={collected} executed={executed} deselected={deselected} "
        f"passed={passed} failed={failed} skipped={skipped} xfailed={xfailed} "
        f"xpassed={xpassed} errors={errors}"
    )

    if args.summary:
        summary = {
            "collected": collected,
            "executed": executed,
            "deselected": deselected,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "xfailed": xfailed,
            "xpassed": xpassed,
            "errors": errors,
            "outcomes": outcomes,
            "skipped_reasons": report.get("skipped_reasons", {}),
            "collection_errors": report.get("collection_errors", []),
        }
        try:
            Path(args.summary).write_text(json.dumps(summary, indent=2), encoding="utf-8")
        except OSError as exc:
            print(f"NO_REPORT cannot write summary: {exc}")
            return 2

    problems = evaluate(report, manifest)
    if problems:
        for problem in problems:
            print(problem)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
