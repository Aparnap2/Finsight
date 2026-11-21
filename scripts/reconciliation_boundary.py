"""Compute and verify the reconciliation runtime boundary.

The boundary is the transitive first-party import closure of
``finance.reconciliation.operator_report`` (the CLI that runs the workflow),
plus the fixture files it reads. It is the set of files that must survive
repository cleanup: everything outside it is either the separate FP&A
application (``apps/``) or a historical product generation.

The manifest is committed at ``docs/release/reconciliation-boundary.json`` and
guarded by ``tests/unit/reconciliation/test_boundary_manifest.py``, so a module
entering or leaving the runtime is a reviewed change rather than an accident.

Usage::

    python scripts/reconciliation_boundary.py            # print the manifest
    python scripts/reconciliation_boundary.py --check     # exit 1 on drift
    python scripts/reconciliation_boundary.py --out PATH  # rewrite the manifest
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = Path("docs") / "release" / "reconciliation-boundary.json"
ENTRY_POINT = "finance.reconciliation.operator_report"
SCHEMA_VERSION = 1
FIRST_PARTY_ROOTS = ("apps", "agents", "finance", "finplatform", "shared")
FIXTURE_PATHS = (
    "tests/fixtures/reconciliation/triangle/cases.json",
    "tests/fixtures/reconciliation/triangle/expected.json",
    "tests/fixtures/reconciliation/triangle/operator_expected.json",
)


def _module_name(path: Path) -> str:
    """Return the dotted module name for a source file under the repository root."""
    parts = list(path.relative_to(ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _first_party_modules() -> dict[str, Path]:
    """Map every first-party module name to its source file."""
    modules: dict[str, Path] = {}
    for root in FIRST_PARTY_ROOTS:
        for path in (ROOT / root).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            modules[_module_name(path)] = path
    return modules


def _imports(path: Path) -> set[str]:
    """Return the absolute import targets declared in one module."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


def _package_chain(name: str) -> list[str]:
    """Return the parent packages whose ``__init__`` runs before ``name``."""
    parts = name.split(".")
    return [".".join(parts[:index]) for index in range(len(parts) - 1, 0, -1)]


def compute_boundary() -> dict[str, object]:
    """Compute the reconciliation runtime boundary as a JSON-ready mapping."""
    modules = _first_party_modules()
    if ENTRY_POINT not in modules:
        raise SystemExit(f"entry point not found: {ENTRY_POINT}")

    stdlib = frozenset(sys.stdlib_module_names)
    boundary: set[str] = set()
    third_party: set[str] = set()
    stack = [ENTRY_POINT]
    while stack:
        name = stack.pop()
        if name in boundary:
            continue
        path = modules.get(name)
        if path is None:
            continue
        boundary.add(name)
        # Importing a module executes its parent packages first.
        stack.extend(package for package in _package_chain(name) if package in modules)
        for imported in _imports(path):
            root = imported.split(".")[0]
            if root in FIRST_PARTY_ROOTS:
                stack.extend(
                    candidate
                    for candidate in (imported, f"{imported}.__init__")
                    if candidate in modules
                )
            elif root not in stdlib and root != "__future__":
                third_party.add(root)

    files = sorted(str(modules[name].relative_to(ROOT)) for name in boundary)
    # Package members that the CLI does not reach but that still exist in the
    # repository. They must not be deleted while the FP&A application that uses
    # them is present, and they are candidates for removal once it is gone.
    outside = sorted(
        str(path.relative_to(ROOT))
        for path in (ROOT / "finance" / "reconciliation").glob("*.py")
        if str(path.relative_to(ROOT)) not in files
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "entry_point": ENTRY_POINT,
        "modules": sorted(boundary),
        "files": files,
        "fixtures": list(FIXTURE_PATHS),
        "third_party_imports": sorted(third_party),
        "environment_variables": [],
        "package_members_outside_closure": outside,
    }


def _render(manifest: dict[str, object]) -> str:
    """Render the manifest deterministically."""
    return json.dumps(manifest, indent=2, sort_keys=True) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    """Print, write, or verify the boundary manifest."""
    parser = argparse.ArgumentParser(
        description="Compute and verify the reconciliation runtime boundary.",
    )
    parser.add_argument("--check", action="store_true", help="verify the committed manifest")
    parser.add_argument("--out", type=Path, default=None, help="write the manifest to PATH")
    args = parser.parse_args(argv)

    computed = compute_boundary()

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(_render(computed), encoding="utf-8")
        return 0

    if not args.check:
        sys.stdout.write(_render(computed))
        return 0

    manifest_path = ROOT / MANIFEST_PATH
    if not manifest_path.exists():
        sys.stderr.write(f"ERROR: manifest missing: {MANIFEST_PATH}\n")
        return 1
    committed = json.loads(manifest_path.read_text(encoding="utf-8"))
    if committed == computed:
        return 0
    for key in sorted(set(committed) | set(computed)):
        if committed.get(key) != computed.get(key):
            sys.stderr.write(
                f"ERROR: boundary drift in {key!r}\n"
                f"  committed: {committed.get(key)!r}\n"
                f"  computed:  {computed.get(key)!r}\n"
            )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
