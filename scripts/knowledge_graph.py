"""Generate and validate the FinSight codebase knowledge bundle (OKF v0.2).

This is a developer-productivity tool. It produces a deterministic, OKF-compatible
Markdown bundle under ``docs/knowledge/`` that captures the reconciliation
execution path (engine -> API -> persistence) as machine-confirmed concepts.

It is intentionally narrow:
* Only the reconciliation runtime scope is covered (see ``_SCOPE``).
* No LLM, no auto-commits, no scheduled runs.
* Structural relationships come from AST analysis; runtime behaviour is NOT
  inferred from imports and is documented in ``docs/knowledge/coverage.md``.

Usage::

    python scripts/knowledge_graph.py                # regenerate in place
    python scripts/knowledge_graph.py --check        # exit 1 on drift
    python scripts/knowledge_graph.py --out PATH     # write candidate bundle to PATH
    python scripts/knowledge_graph.py --validate    # validate an existing bundle

The OKF format is vendored from the GoogleCloudPlatform/knowledge-catalog
reference (commit 3fcbb9f828c2f23d109c855ee403c3a4c81f3a96), Apache-2.0.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_DIR = "docs/knowledge"
GENERATED_BY = "process:knowledge-graph"
GENERATED_AT = "2026-01-01T00:00:00Z"
STALE_AFTER = "2027-01-01"

# Approved scope (Phase 1-2). Explicitly bounded.
_SCOPE_MODULES = [
    "finance/reconciliation",
]
_SCOPE_FILES = [
    "apps/api/reconciliation_routes.py",
    "shared/models/reconciliation.py",
]
_SCOPE_MIGRATIONS_GLOB = "alembic/versions/*reconciliation*"
_SCOPE_TESTS = [
    "tests/integration/test_reconciliation_http.py",
    "tests/integration/test_reconciliation_contract.py",
    "tests/integration/test_reconciliation_rls.py",
    "tests/integration/test_reconciliation_concurrency.py",
]
_SCOPE_SPECS = [
    "docs/specs/API_CONTRACT.md",
    "docs/specs/DATABASE_SCHEMA.md",
]
_SCOPE_ENTRY = "finance.reconciliation.operator_report"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _module_name_for(path: Path) -> str:
    parts = list(path.relative_to(ROOT).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _first_party_modules() -> dict[str, Path]:
    modules: dict[str, Path] = {}
    for root in ("apps", "agents", "finance", "finplatform", "shared"):
        base = ROOT / root
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            modules[_module_name_for(path)] = path
    return modules


def _imports_of(path: Path, modules: dict[str, Path]) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(
                    alias.name.split(".")[0] + "." + alias.name.split(".")[1]
                    if "." in alias.name
                    else alias.name
                )
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    # Keep only first-party in-scope modules
    result = []
    for name in names:
        # resolve to full module if possible
        if name in modules:
            result.append(name)
        else:
            # try prefix
            for m in modules:
                if (m == name or m.startswith(name + ".")) and m in modules and m not in result:
                    result.append(m)
                    break
    return sorted(set(result))


def _classes_and_functions(path: Path) -> tuple[list[str], list[str]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return [], []
    classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    functions = [
        n.name
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")
    ]
    return sorted(set(classes)), sorted(set(functions))


def _docstring_first_line(path: Path) -> str:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return ""
    ds = ast.get_docstring(tree)
    if not ds:
        return ""
    return ds.strip().splitlines()[0]


def _slug(module_name: str) -> str:
    return module_name.replace(".", "-")


def _is_human_reviewed(path: Path) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    return "human:" in text and "verified:" in text


def _frontmatter(concept: dict[str, Any]) -> str:
    fm = {
        "type": concept["type"],
        "title": concept["title"],
    }
    if concept.get("description"):
        fm["description"] = concept["description"]
    if concept.get("resource"):
        fm["resource"] = concept["resource"]
    if concept.get("tags"):
        fm["tags"] = concept["tags"]
    fm["generated"] = {"by": GENERATED_BY, "at": GENERATED_AT}
    fm["verified"] = {"by": GENERATED_BY, "at": GENERATED_AT}
    fm["status"] = "stable"
    if concept.get("sources"):
        fm["sources"] = concept["sources"]
    if concept.get("source_fingerprint"):
        fm["source_fingerprint"] = concept["source_fingerprint"]
    if concept.get("stale_after"):
        fm["stale_after"] = concept["stale_after"]
    # Use yaml.safe_dump for correct quoting, then strip trailing newline
    dumped = yaml.safe_dump(
        fm, default_flow_style=None, sort_keys=False, allow_unicode=True
    ).rstrip("\n")  # noqa: E501
    # Make generated/verified inline-ish: safe_dump already fine
    lines = ["---", dumped, "---"]
    return "\n".join(lines)


def _discover_modules() -> list[Path]:
    result: list[Path] = []
    for d in _SCOPE_MODULES:
        base = ROOT / d
        if not base.exists():
            continue
        for p in sorted(base.rglob("*.py")):
            if "__pycache__" in p.parts or p.name.startswith("_"):
                continue
            result.append(p)
    for f in _SCOPE_FILES:
        p = ROOT / f
        if p.exists():
            result.append(p)
    return sorted(set(result))


def _discover_migrations() -> list[Path]:
    result: list[Path] = []
    for pattern in [_SCOPE_MIGRATIONS_GLOB]:
        for p in sorted(ROOT.glob(pattern)):
            if p.is_file():
                result.append(p)
    return sorted(set(result))


def _in_scope_module_names(modules_map: dict[str, Path], path: Path) -> bool:
    """Whether a module path is within approved scope."""
    rel = path.relative_to(ROOT).as_posix()
    if rel.startswith("finance/reconciliation/"):
        return True
    return rel in ("apps/api/reconciliation_routes.py", "shared/models/reconciliation.py")


@dataclass
class Concept:
    slug: str
    type: str
    title: str
    description: str
    resource: str
    tags: list[str]
    sources: list[dict[str, str]]
    source_fingerprint: str | None
    body: str


def _build_module_concept(path: Path, modules_map: dict[str, Path]) -> Concept:
    rel = path.relative_to(ROOT).as_posix()
    mod_name = _module_name_for(path)
    desc = _docstring_first_line(path) or f"Module {mod_name}."
    classes, functions = _classes_and_functions(path)
    imports = _imports_of(path, modules_map)
    # only keep in-scope imports for links
    in_scope_imports = [m for m in imports if _in_scope_module_names(modules_map, modules_map[m])]
    sources = [{"id": "src", "resource": f"/{rel}", "title": path.name}]
    fp = _sha256_file(path)
    body_parts = [f"# {path.stem.replace('_', ' ').title()}", ""]
    if classes:
        body_parts.append("## Classes")
        body_parts.append("")
        for c in classes:
            body_parts.append(f"- `{c}`")
        body_parts.append("")
    if functions:
        body_parts.append("## Public functions")
        body_parts.append("")
        for f in functions:
            body_parts.append(f"- `{f}()`")
        body_parts.append("")
    if in_scope_imports:
        body_parts.append("## In-scope dependencies")
        body_parts.append("")
        for m in in_scope_imports:
            slug = _slug(m)
            body_parts.append(f"- [{m}](/code/modules/{slug}.md)")
        body_parts.append("")
    body_parts.append("## Provenance")
    body_parts.append("")
    body_parts.append(f"Source fingerprint (SHA-256): `{fp}`")
    body_parts.append("")
    body_parts.append(
        "> Structural relationships above are derived from static AST analysis. "
        "Runtime behaviour (dependency injection, dynamic dispatch) is not captured; "
        "see `/coverage.md`."
    )
    body_parts.append("")
    return Concept(
        slug=_slug(mod_name),
        type="Module",
        title=mod_name,
        description=desc[:200],
        resource=f"/{rel}",
        tags=["reconciliation", "module"],
        sources=sources,
        source_fingerprint=fp,
        body="\n".join(body_parts),
    )


def _build_api_concept(path: Path) -> Concept:
    rel = path.relative_to(ROOT).as_posix()
    text = path.read_text(encoding="utf-8")
    # find route decorators
    routes = re.findall(r'@router\.(get|post|put|delete|patch)\("([^"]+)"', text)
    endpoints = sorted(set(f"{m.upper()} {p}" for m, p in routes))
    fp = _sha256_file(path)
    body_parts = ["# Reconciliation API routes", ""]
    body_parts.append("## Endpoints")
    body_parts.append("")
    for e in endpoints:
        body_parts.append(f"- `{e}`")
    body_parts.append("")
    body_parts.append("## In-scope dependencies")
    body_parts.append("")
    body_parts.append(
        "- [finance.reconciliation.persistence](/code/modules/finance-reconciliation-persistence.md)"
    )  # noqa: E501
    body_parts.append(
        "- [shared.models.reconciliation](/code/modules/shared-models-reconciliation.md)"
    )  # noqa: E501
    body_parts.append("")
    body_parts.append("## Provenance")
    body_parts.append("")
    body_parts.append(f"Source fingerprint (SHA-256): `{fp}`")
    body_parts.append("")
    body_parts.append("> Route list derived from static decorator scanning.")
    body_parts.append("")
    return Concept(
        slug="apps-api-reconciliation_routes",
        type="API Module",
        title="apps.api.reconciliation_routes",
        description="FastAPI routes for the reconciliation workflow (contract §2).",
        resource=f"/{rel}",
        tags=["reconciliation", "api"],
        sources=[{"id": "src", "resource": f"/{rel}", "title": path.name}],
        source_fingerprint=fp,
        body="\n".join(body_parts),
    )


def _build_models_concept(path: Path) -> Concept:
    rel = path.relative_to(ROOT).as_posix()
    classes, _ = _classes_and_functions(path)
    fp = _sha256_file(path)
    body_parts = ["# Reconciliation ORM models", ""]
    body_parts.append("## Models")
    body_parts.append("")
    for c in classes:
        if c in ("Base",):
            continue
        body_parts.append(f"- `{c}`")
    body_parts.append("")
    body_parts.append("## Provenance")
    body_parts.append("")
    body_parts.append(f"Source fingerprint (SHA-256): `{fp}`")
    body_parts.append("")
    return Concept(
        slug="shared-models-reconciliation",
        type="Data Model",
        title="shared.models.reconciliation",
        description="SQLAlchemy ORM models for the 12 reconciliation tables.",
        resource=f"/{rel}",
        tags=["reconciliation", "data-model"],
        sources=[{"id": "src", "resource": f"/{rel}", "title": path.name}],
        source_fingerprint=fp,
        body="\n".join(body_parts),
    )


def _build_migration_concept(paths: list[Path]) -> Concept:
    body_parts = ["# Reconciliation schema migrations", ""]
    body_parts.append("## Migrations")
    body_parts.append("")
    fps = []
    for p in paths:
        rel = p.relative_to(ROOT).as_posix()
        body_parts.append(f"- `{rel}`")
        fps.append(_sha256_file(p))
    body_parts.append("")
    fp = hashlib.sha256("".join(fps).encode()).hexdigest()
    body_parts.append("## Provenance")
    body_parts.append("")
    body_parts.append(f"Combined source fingerprint (SHA-256): `{fp}`")
    body_parts.append("")
    return Concept(
        slug="alembic-reconciliation-migrations",
        type="Migration",
        title="Reconciliation schema migrations",
        description="Alembic revisions creating the reconciliation tables and RLS policies.",
        resource="/alembic/versions",
        tags=["reconciliation", "migration"],
        sources=[
            {"id": "src", "resource": "/alembic/versions", "title": "reconciliation migrations"}
        ],  # noqa: E501
        source_fingerprint=fp,
        body="\n".join(body_parts),
    )


def _build_arch_concept(
    slug: str, title: str, description: str, links: list[str], fp_sources: list[Path]
) -> Concept:  # noqa: E501
    body_parts = [f"# {title}", "", description, ""]
    if links:
        body_parts.append("## Related concepts")
        body_parts.append("")
        for link in links:
            body_parts.append(f"- [{link}](/code/modules/{_slug(link)}.md)")
        body_parts.append("")
    body_parts.append("## Provenance")
    body_parts.append("")
    fps = [_sha256_file(p) for p in fp_sources if p.exists()]
    fp = hashlib.sha256("".join(fps).encode()).hexdigest() if fps else ""
    body_parts.append(f"Source fingerprint (SHA-256): `{fp}`")
    body_parts.append("")
    body_parts.append(
        "> Architecture concept derived from source structure and existing specs. "
        "Runtime behaviour is not inferred from imports alone."
    )
    body_parts.append("")
    return Concept(
        slug=slug,
        type="Architecture",
        title=title,
        description=description,
        resource=None,
        tags=["reconciliation", "architecture"],
        sources=[
            {"id": "src", "resource": "/finance/reconciliation", "title": "reconciliation runtime"}
        ],  # noqa: E501
        source_fingerprint=fp if fp else None,
        body="\n".join(body_parts),
    )


def _render_concept(c: Concept) -> str:
    fm = _frontmatter(
        {
            "type": c.type,
            "title": c.title,
            "description": c.description,
            "resource": c.resource,
            "tags": c.tags,
            "sources": c.sources,
            "source_fingerprint": c.source_fingerprint,
        }
    )
    return fm + "\n\n" + c.body + "\n"


def _concept_path(knowledge_root: Path, c: Concept) -> Path:
    return knowledge_root / "code" / "modules" / f"{c.slug}.md"


def _is_human_reviewed(path: Path) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    return "human:" in text


def generate_bundle(knowledge_root: Path) -> dict[str, str]:
    """Return a mapping of relative-path -> content for the full bundle."""
    modules_map = _first_party_modules()
    files = _discover_modules()
    migrations = _discover_migrations()

    concepts: list[Concept] = []
    # module concepts
    for path in files:
        if path.as_posix().endswith("reconciliation_routes.py") or path.as_posix().endswith(
            "shared/models/reconciliation.py"
        ):  # noqa: E501
            continue
        _module_name_for(path)
        concepts.append(_build_module_concept(path, modules_map))

    # api concept
    api_path = ROOT / "apps/api/reconciliation_routes.py"
    if api_path.exists():
        concepts.append(_build_api_concept(api_path))

    # models concept
    models_path = ROOT / "shared/models/reconciliation.py"
    if models_path.exists():
        concepts.append(_build_models_concept(models_path))

    # migration concept
    if migrations:
        concepts.append(_build_migration_concept(migrations))

    # architecture concepts
    concepts.append(
        _build_arch_concept(
            "reconciliation-workflow",
            "Reconciliation Workflow",
            "Three-source reconciliation execution path: ingest, validate, reconcile, persist, decide, audit.",  # noqa: E501
            [
                "finance.reconciliation.statement_workflow",
                "apps.api.reconciliation_routes",
                "finance.reconciliation.persistence",
            ],  # noqa: E501
            [
                ROOT / "finance/reconciliation/statement_workflow.py",
                ROOT / "apps/api/reconciliation_routes.py",
            ],  # noqa: E501
        )
    )
    concepts.append(
        _build_arch_concept(
            "tenant-isolation",
            "Tenant Isolation Boundary",
            "Row-level security and transaction-local tenant GUC wiring for reconciliation tables.",
            [
                "finance.reconciliation.persistence",
                "apps.api.reconciliation_routes",
                "shared.models.reconciliation",
            ],  # noqa: E501
            [
                ROOT / "finance/reconciliation/persistence.py",
                ROOT / "apps/api/reconciliation_routes.py",
            ],  # noqa: E501
        )
    )

    # sort concepts by slug for determinism
    concepts.sort(key=lambda c: c.slug)

    bundle: dict[str, str] = {}

    # concept files
    for c in concepts:
        rel = f"code/modules/{c.slug}.md"
        bundle[rel] = _render_concept(c)

    # index files
    bundle["index.md"] = _render_index(concepts)
    bundle["code/index.md"] = _render_code_index(concepts)
    bundle["code/modules/index.md"] = _render_modules_index(concepts)

    # coverage report
    bundle["coverage.md"] = _render_coverage(concepts, files, migrations)

    # NOTICE (attribution)
    bundle["NOTICE.md"] = _render_notice()

    return bundle


def _render_index(concepts: list[Concept]) -> str:
    lines = [
        "# FinSight Reconciliation Knowledge Bundle",
        "",
        "OKF v0.2 bundle. Machine-generated; do not edit by hand.",
        "",
    ]  # noqa: E501
    lines.append("## Concepts")
    lines.append("")
    for c in sorted(concepts, key=lambda x: x.slug):
        lines.append(f"* [{c.title}](/code/modules/{c.slug}.md) - {c.description}")
    lines.append("")
    lines.append("## Navigation")
    lines.append("")
    lines.append("* [Code modules](/code/index.md)")
    lines.append("* [Coverage report](/coverage.md)")
    lines.append("* [Notice](/NOTICE.md)")
    lines.append("")
    return "\n".join(lines)


def _render_code_index(concepts: list[Concept]) -> str:
    lines = ["# Code", "", "## Modules", ""]
    for c in sorted(concepts, key=lambda x: x.slug):
        lines.append(f"* [{c.title}](/code/modules/{c.slug}.md) - {c.description}")
    lines.append("")
    return "\n".join(lines)


def _render_modules_index(concepts: list[Concept]) -> str:
    lines = ["# Modules", ""]
    for c in sorted(concepts, key=lambda x: x.slug):
        lines.append(f"* [{c.title}](/code/modules/{c.slug}.md) - {c.description}")
    lines.append("")
    return "\n".join(lines)


def _render_coverage(concepts: list[Concept], files: list[Path], migrations: list[Path]) -> str:
    lines = ["# Knowledge Graph Coverage Report", ""]
    lines.append("## What the graph discovers reliably")
    lines.append("")
    lines.append("- Python module import relationships (AST-based, first-party only).")
    lines.append("- Public class and function names per module.")
    lines.append("- FastAPI route registrations (decorator scanning).")
    lines.append("- SQLAlchemy model class names.")
    lines.append("- Alembic migration file references.")
    lines.append("- Source file SHA-256 fingerprints for staleness detection.")
    lines.append("")
    lines.append("## What remains invisible to static analysis")
    lines.append("")
    lines.append("- Runtime dependency injection and dynamic dispatch.")
    lines.append("- Database RLS policies and their runtime enforcement.")
    lines.append("- Test coverage quality (imports a module != tests it well).")
    lines.append("- Configuration loaded from environment at runtime.")
    lines.append("- Concurrency and transaction ordering behaviour.")
    lines.append("- LLM-generated content (not used in this bundle).")
    lines.append("")
    lines.append("## Scope")
    lines.append("")
    lines.append(f"- Modules discovered: {len(files)}")
    lines.append(f"- Concepts generated: {len(concepts)}")
    lines.append(f"- Migrations referenced: {len(migrations)}")
    lines.append("")
    lines.append("## Generation")
    lines.append("")
    lines.append("- Generator: `scripts/knowledge_graph.py`")
    lines.append(f"- Generated by: `{GENERATED_BY}`")
    lines.append(f"- Generated at: `{GENERATED_AT}` (fixed for determinism)")
    lines.append("")
    return "\n".join(lines)


def _render_notice() -> str:
    return (
        "# Notice\n\n"
        "The OKF format is vendored from the GoogleCloudPlatform/knowledge-catalog "
        "reference repository (commit 3fcbb9f828c2f23d109c855ee403c3a4c81f3a96), "
        "licensed under Apache-2.0. Copyright (c) Google LLC.\n\n"
        "This bundle's structural content is generated deterministically by "
        "`scripts/knowledge_graph.py` and is marked `machine-confirmed`. "
        "Human-reviewed content is identified by a `human:` actor in the "
        "`verified` frontmatter field and is never overwritten by the generator.\n"
    )


def write_bundle(
    knowledge_root: Path, bundle: dict[str, str], *, preserve_human: bool = True
) -> list[str]:  # noqa: E501
    """Write bundle files. Returns list of files written."""
    written: list[str] = []
    for rel, content in bundle.items():
        target = knowledge_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if preserve_human and target.exists() and _is_human_reviewed(target):
            # do not overwrite
            continue
        target.write_text(content, encoding="utf-8")
        written.append(rel)
    return written


def compute_bundle(knowledge_root: Path | None = None) -> dict[str, str]:
    """Compute the expected bundle (in-memory)."""
    return generate_bundle(knowledge_root or (ROOT / KNOWLEDGE_DIR))


def check_drift(knowledge_root: Path) -> tuple[bool, list[str]]:
    """Compare committed bundle against freshly generated. Returns (ok, messages)."""
    expected = generate_bundle(knowledge_root)
    messages: list[str] = []
    # check all expected files exist and match
    for rel, content in expected.items():
        target = knowledge_root / rel
        if not target.exists():
            messages.append(f"MISSING: {rel}")
            continue
        actual = target.read_text(encoding="utf-8")
        if actual != content:
            # allow human-reviewed files to differ
            if _is_human_reviewed(target):
                continue
            messages.append(f"DRIFT: {rel}")
    # check for unexpected machine-generated files? (skip for now)
    return (len(messages) == 0, messages)


def main() -> int:
    parser = argparse.ArgumentParser(description="FinSight codebase knowledge bundle")
    parser.add_argument("--check", action="store_true", help="exit 1 on drift")
    parser.add_argument("--validate", action="store_true", help="validate an existing bundle")
    parser.add_argument("--out", type=Path, default=None, help="write candidate bundle to this dir")
    args = parser.parse_args()

    knowledge_root = (args.out if args.out else ROOT / KNOWLEDGE_DIR).resolve()
    bundle = generate_bundle(ROOT / KNOWLEDGE_DIR)

    if args.check:
        ok, msgs = check_drift(ROOT / KNOWLEDGE_DIR)
        if not ok:
            for m in msgs:
                print(m)
            print(f"Drift detected: {len(msgs)} issue(s).")
            return 1
        print("Knowledge bundle is in sync with source.")
        return 0

    if args.validate:
        # delegate to validate_knowledge module
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "validate_knowledge", ROOT / "scripts" / "validate_knowledge.py"
        )  # noqa: E501
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.validate_bundle(knowledge_root)

    # write
    knowledge_root.mkdir(parents=True, exist_ok=True)
    written = write_bundle(knowledge_root, bundle)
    print(f"Wrote {len(written)} files to {knowledge_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
