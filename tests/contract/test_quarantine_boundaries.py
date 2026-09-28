"""Contract: quarantine boundaries for dead finance modules (tests, not deletions).

``finance.llm.*`` and ``finance.approval.decision`` / ``finance.approval.authorization``
are unreachable from the executable path; the canonical replacements are
``shared.llm.*`` and ``finance.approvals.*``. These AST import-graph tests pin
the quarantine perimeter so no new dependents can appear. Deletions are
forbidden here because currently-green unit tests still import the dead code.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

QUARANTINED_LLM = "finance.llm"
DEAD_DECISION = "finance.approval.decision"
DEAD_AUTHORIZATION = "finance.approval.authorization"
DEAD_APPROVAL_SUBMODULES = (QUARANTINED_LLM, DEAD_DECISION, DEAD_AUTHORIZATION)

# Only pre-existing dependents allowed to import finance.llm.*.
ALLOWED_LLM_TEST_USERS = frozenset(
    {
        "tests/llm/test_providers.py",
        "tests/unit/test_finance/test_llm_runtime.py",
    }
)


def _imported_modules(path: Path) -> set[str]:
    """Return absolute module names imported via Import/ImportFrom nodes."""
    tree = ast.parse(path.read_bytes(), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
    return names


def _matches(name: str, banned: str) -> bool:
    """Match a banned module or any of its submodules."""
    return name == banned or name.startswith(banned + ".")


def _scan(
    root: Path,
    banned: tuple[str, ...],
    *,
    exclude_dirs: tuple[Path, ...] = (),
    exclude_files: frozenset[str] = frozenset(),
) -> list[str]:
    """Scan *.py under root for banned imports; return violation descriptions."""
    violations: list[str] = []
    for py in sorted(root.rglob("*.py")):
        rel = py.relative_to(REPO_ROOT).as_posix()
        if rel in exclude_files:
            continue
        if any(py.is_relative_to(d) for d in exclude_dirs):
            continue
        for name in sorted(_imported_modules(py)):
            for ban in banned:
                if _matches(name, ban):
                    violations.append(f"{rel} imports {name} (banned: {ban})")
    return violations


def test_apps_may_not_import_quarantined_modules() -> None:
    """Apps layer must use finance.approvals.* / shared.llm.*, never the dead code."""
    violations = _scan(REPO_ROOT / "apps", DEAD_APPROVAL_SUBMODULES)
    assert violations == [], "\n".join(violations)


def test_finance_may_not_import_quarantined_llm() -> None:
    """Only finance/llm/ itself may import finance.llm.* (internal imports)."""
    violations = _scan(
        REPO_ROOT / "finance",
        (QUARANTINED_LLM,),
        exclude_dirs=(REPO_ROOT / "finance" / "llm",),
    )
    assert violations == [], "\n".join(violations)


def test_agents_may_not_import_quarantined_modules() -> None:
    """Agents layer has no legacy exclusion: no agents/legacy* package exists."""
    assert not (REPO_ROOT / "agents" / "legacy").exists()
    assert not list((REPO_ROOT / "agents").glob("legacy*"))
    violations = _scan(REPO_ROOT / "agents", DEAD_APPROVAL_SUBMODULES)
    assert violations == [], "\n".join(violations)


def test_tests_llm_perimeter_pinned() -> None:
    """Only the two pre-existing test files may import finance.llm.*."""
    violations = _scan(
        REPO_ROOT / "tests",
        (QUARANTINED_LLM,),
        exclude_dirs=(REPO_ROOT / "tests" / "llm",),
        exclude_files=ALLOWED_LLM_TEST_USERS,
    )
    assert violations == [], "\n".join(violations)


def test_canonical_approval_service_wired() -> None:
    """Positive control: live routes use authoritative finance.approvals.service."""
    service = importlib.import_module("finance.approvals.service")
    assert hasattr(service, "ApprovalService")
    route_imports = _imported_modules(REPO_ROOT / "apps" / "api" / "execution_routes.py")
    assert "finance.approvals.service" in route_imports


def test_canonical_llm_provider_wired() -> None:
    """Positive control: agents use canonical shared.llm providers."""
    fake = importlib.import_module("shared.llm.fake")
    assert hasattr(fake, "FakeLLM")
    planner_imports = _imported_modules(REPO_ROOT / "agents" / "investigation" / "planner.py")
    assert any(name.startswith("shared.llm") for name in planner_imports)


def test_refusals_exception_chain_intact() -> None:
    """Positive control: refusals enum stays importable via legacy record chain."""
    refusals = importlib.import_module("finance.approval.refusals")
    assert hasattr(refusals, "ApprovalRefused") and hasattr(refusals, "RefusalCode")
    record_imports = _imported_modules(REPO_ROOT / "finance" / "legacy_execution" / "record.py")
    assert "finance.approval.refusals" in record_imports
    handoff_imports = _imported_modules(REPO_ROOT / "finance" / "legacy_execution" / "handoff.py")
    assert "finance.legacy_execution.record" in handoff_imports
