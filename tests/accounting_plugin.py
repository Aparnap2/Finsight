"""Pytest accounting hooks: record what was collected, executed, and why not.

Loaded automatically by ``tests/conftest.py`` (which fixes ``sys.path``
before importing this module), so a run needs no ``-p`` flag.

The suite's *collected* count and its *executed* count are different numbers.
This plugin records the difference with enough detail to be checked:

- every collected node id;
- every deselected node id (marker filters) and the reason it was dropped;
- every outcome (passed / failed / skipped / xfailed / xpass / error) with
  the skip reason where one exists;
- collection errors, which are a broken suite rather than a skip.

The report is written only when ``FINSIGHT_TEST_ACCOUNTING_REPORT`` names an
output path, so ordinary local and CI runs are unaffected. ``scripts/
test_accounting.py`` consumes the report and fails the job when the
difference is not explained by a declared reason.

Failure semantics: a skipped test is not a passing test, and a test that is
collected but never accounted for is an omission, not a pass.
"""

import json
import os
from typing import Any

_ACCOUNTING_REPORT_ENV = "FINSIGHT_TEST_ACCOUNTING_REPORT"

#: Node id -> outcome for every test that produced a report.
_OUTCOMES: dict[str, str] = {}

#: Node id -> reason for every skip.
_SKIP_REASONS: dict[str, str] = {}

#: Node ids dropped by marker filters.
_DESELECTED: list[str] = []

#: Node ids that were collected.
_COLLECTED: list[str] = []

#: Collection errors: a module that failed to import.
_COLLECTION_ERRORS: list[str] = []


def _report_path() -> str | None:
    """Return the configured accounting report path, if any."""
    return os.environ.get(_ACCOUNTING_REPORT_ENV) or None


def pytest_collection_finish(session: Any) -> None:
    """Record the selected node ids.

    ``pytest_collection_finish`` runs after every ``modifyitems`` hook, so
    the list it exposes is the set of tests pytest will actually run — the
    marker-filter deselections are already applied.  Counting here rather
    than in ``pytest_collection_modifyitems`` keeps "collected" and
    "deselected" disjoint.
    """
    _COLLECTED.clear()
    for item in session.items:
        _COLLECTED.append(item.nodeid)


def pytest_deselected(items: list[Any]) -> None:
    """Record node ids dropped by a marker filter."""
    for item in items:
        _DESELECTED.append(item.nodeid)


def pytest_collectreport(report: Any) -> None:
    """Record collection errors (a module that failed to import)."""
    if getattr(report, "failed", False):
        _COLLECTION_ERRORS.append(str(report.longrepr))


def pytest_runtest_logreport(report: Any) -> None:
    """Record the outcome of each test phase."""
    outcome = report.outcome
    was_xfail = hasattr(report, "wasxfail")
    if outcome == "skipped" and report.when in ("setup", "call"):
        # A skip can be raised at setup (marker/condition) or at call time
        # (pytest.skip() inside the test body). Both are skips.
        if was_xfail:
            _OUTCOMES[report.nodeid] = "xfailed"
        else:
            _OUTCOMES[report.nodeid] = "skipped"
            _SKIP_REASONS[report.nodeid] = _skip_reason(report)
    elif report.when == "call":
        if was_xfail and outcome == "passed":
            _OUTCOMES[report.nodeid] = "xpassed"
        elif outcome == "failed":
            _OUTCOMES[report.nodeid] = "failed"
        elif outcome == "passed":
            _OUTCOMES[report.nodeid] = "passed"
    elif report.when == "teardown" and outcome == "failed":
        _OUTCOMES[report.nodeid] = "error"


def _skip_reason(report: Any) -> str:
    """Return a skip's reason text (empty when the skip carries none)."""
    longrepr = getattr(report, "longrepr", None)
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        return str(longrepr[2])
    return ""


def pytest_sessionfinish(session: Any, exitstatus: int) -> None:
    """Write the accounting report when a path is configured."""
    path = _report_path()
    if not path:
        return
    counted: dict[str, int] = {}
    for outcome in _OUTCOMES.values():
        counted[outcome] = counted.get(outcome, 0) + 1
    payload = {
        "collected": len(_COLLECTED),
        "deselected": len(_DESELECTED),
        "deselected_nodeids": sorted(_DESELECTED),
        "outcomes": counted,
        "skipped_reasons": _SKIP_REASONS,
        "collection_errors": _COLLECTION_ERRORS,
        "collected_nodeids": sorted(_COLLECTED),
        "executed_nodeids": sorted(_OUTCOMES),
        "exitstatus": int(exitstatus),
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
