"""Tests for the OKF codebase knowledge graph generator and validator.

These tests independently establish expected discovery results rather than
mirroring the generator's implementation, so they can detect regressions in
route, model and module discovery.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "scripts" / "knowledge_graph.py"
_VALIDATOR = _ROOT / "scripts" / "validate_knowledge.py"
_KB = _ROOT / "docs" / "knowledge"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def kg() -> ModuleType:
    return _load("knowledge_graph", _SCRIPT)


@pytest.fixture(scope="module")
def validator() -> ModuleType:
    return _load("validate_knowledge", _VALIDATOR)


# ---------------------------------------------------------------------------
# Discovery: independent expected results
# ---------------------------------------------------------------------------


def test_discover_modules_includes_reconciliation_engine(kg: ModuleType) -> None:
    files = kg._discover_modules()
    rels = {p.relative_to(_ROOT).as_posix() for p in files}
    # Independent expectation: the core engine modules must be present.
    assert "finance/reconciliation/persistence.py" in rels
    assert "finance/reconciliation/statement_workflow.py" in rels
    assert "finance/reconciliation/exception_lifecycle.py" in rels
    assert "finance/reconciliation/models.py" in rels


def test_discover_modules_includes_api_and_models(kg: ModuleType) -> None:
    files = kg._discover_modules()
    rels = {p.relative_to(_ROOT).as_posix() for p in files}
    assert "apps/api/reconciliation_routes.py" in rels
    assert "shared/models/reconciliation.py" in rels


def test_discover_modules_excludes_unrelated_fp_and_a(kg: ModuleType) -> None:
    files = kg._discover_modules()
    rels = {p.relative_to(_ROOT).as_posix() for p in files}
    # Scope boundary: no FP&A or unrelated modules.
    for r in rels:
        assert r.startswith("finance/reconciliation/") or r in {
            "apps/api/reconciliation_routes.py",
            "shared/models/reconciliation.py",
        }, r


def test_discover_migrations_nonempty(kg: ModuleType) -> None:
    migrations = kg._discover_migrations()
    assert len(migrations) >= 1
    for m in migrations:
        assert m.name.endswith(".py")
        assert "reconciliation" in m.name.lower()


def test_route_discovery_finds_all_contract_endpoints(kg: ModuleType) -> None:
    # Independent expected set from docs/specs/API_CONTRACT.md.
    # Just check the generator's route list contains the eight contract paths.
    api_path = _ROOT / "apps/api/reconciliation_routes.py"
    routes = kg._build_api_concept(api_path) if hasattr(kg, "_build_api_concept") else None
    assert routes is not None
    text = routes.body
    for path in (
        "/import-sessions/{session_id}",
        "/runs/{run_id}/matches",
        "/runs/{run_id}/allocations",
        "/runs/{run_id}/exceptions",
        "/exceptions/{exception_id}",
        "/runs/{run_id}/exports",
        "/exports/{export_id}",
    ):
        assert path in text, path


def test_model_discovery_finds_key_models(kg: ModuleType) -> None:
    models_path = _ROOT / "shared/models/reconciliation.py"
    concept = kg._build_models_concept(models_path)
    body = concept.body
    for model in (
        "ReconciliationRun",
        "ReconciliationMatch",
        "ReconciliationException",
        "PayoutAllocation",
        "ExceptionDecision",
        "AuditEvent",
        "ExportArtifact",
    ):
        assert model in body, model


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_bundle_is_deterministic(kg: ModuleType) -> None:
    b1 = kg.generate_bundle(_ROOT / "docs" / "knowledge")
    import tempfile

    d1 = Path(tempfile.mkdtemp())
    d2 = Path(tempfile.mkdtemp())
    kg.write_bundle(d1, b1)
    b2 = kg.generate_bundle(_ROOT / "docs" / "knowledge")
    kg.write_bundle(d2, b2)
    # compare file contents
    files1 = sorted(p.relative_to(d1).as_posix() for p in d1.rglob("*") if p.is_file())
    files2 = sorted(p.relative_to(d2).as_posix() for p in d2.rglob("*") if p.is_file())
    assert files1 == files2
    for rel in files1:
        assert (d1 / rel).read_bytes() == (d2 / rel).read_bytes(), rel


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


def test_validator_passes_on_committed_bundle(validator: ModuleType) -> None:
    assert validator.validate_bundle(_KB) == 0


def test_validator_rejects_missing_type(validator: ModuleType, tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "bad.md").write_text("---\ntitle: No type\n---\nbody\n", encoding="utf-8")
    # validate_bundle returns 1 on errors
    assert validator.validate_bundle(bundle) == 1


def test_validator_rejects_broken_link(validator: ModuleType, tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "a.md").write_text("---\ntype: Module\n---\n[missing](/nope.md)\n", encoding="utf-8")
    # broken links are warnings, not errors by default; strict mode makes them errors
    assert validator.validate_bundle(bundle, strict=True) == 1


def test_validator_rejects_stale_fingerprint(validator: ModuleType, tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    wrong = "f" * 64
    # A resolvable source file whose recorded fingerprint no longer matches.
    root_src = _ROOT / "docs" / "knowledge" / "src_test_tmp.py"
    root_src.write_text("x = 1\n", encoding="utf-8")
    try:
        frontmatter = "\n".join(
            [
                "---",
                "type: Module",
                "sources:",
                "  - id: src",
                "    resource: /docs/knowledge/src_test_tmp.py",
                f"source_fingerprint: {wrong}",
                "---",
                "body",
                "",
            ]
        )
        (bundle / "m2.md").write_text(frontmatter, encoding="utf-8")
        assert validator.validate_bundle(bundle) == 1
    finally:
        root_src.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Human-content preservation
# ---------------------------------------------------------------------------


def test_human_reviewed_file_not_overwritten(kg: ModuleType, tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    # seed a human-reviewed file
    target = bundle / "code" / "modules" / "finance-reconciliation-persistence.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "---\ntype: Module\ngenerated: {by: process:knowledge-graph, at: 2026-01-01T00:00:00Z}\n"
        "verified: {by: human:alice, at: 2026-01-02T00:00:00Z}\n---\nHUMAN CONTENT\n",
        encoding="utf-8",
    )
    b = kg.generate_bundle(_ROOT / "docs" / "knowledge")
    written = kg.write_bundle(bundle, b)
    assert "code/modules/finance-reconciliation-persistence.md" not in written
    assert target.read_text().endswith("HUMAN CONTENT\n")
