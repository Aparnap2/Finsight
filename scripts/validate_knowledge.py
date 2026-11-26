"""Validate an OKF knowledge bundle (FinSight subset).

Checks:
* Every concept markdown file has valid YAML frontmatter with `type`.
* Internal links (absolute bundle-relative) resolve to existing files.
* Source fingerprints match current source files (stale detection).
* Provenance present (sources list non-empty for machine-generated).
* Human-reviewed files are not overwritten by the generator (checked by generator).

Usage::

    python scripts/validate_knowledge.py [BUNDLE_DIR]
    python scripts/validate_knowledge.py --strict   # treat warnings as errors

Exit code 0 on success, 1 on validation failure.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLE = ROOT / "docs" / "knowledge"


def _parse_frontmatter(path: Path) -> tuple[dict[str, Any] | None, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None, text
    try:
        fm = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return None, text
    if not isinstance(fm, dict):
        return None, text
    return fm, parts[2]


def validate_bundle(bundle_dir: Path, *, strict: bool = False) -> int:
    errors: list[str] = []
    warnings: list[str] = []

    if not bundle_dir.exists():
        print(f"Bundle directory not found: {bundle_dir}")
        return 1

    md_files = sorted(bundle_dir.rglob("*.md"))
    concept_files = [
        p for p in md_files if p.name not in ("index.md", "log.md", "NOTICE.md", "coverage.md")
    ]

    # 1. frontmatter conformance
    for path in concept_files:
        rel = path.relative_to(bundle_dir).as_posix()
        fm, body = _parse_frontmatter(path)
        if fm is None:
            errors.append(f"{rel}: missing or invalid frontmatter")
            continue
        if "type" not in fm:
            errors.append(f"{rel}: missing required 'type' field")
        # provenance check for machine-generated
        gen = fm.get("generated")
        if (
            isinstance(gen, dict)
            and gen.get("by", "").startswith("process:")
            and not fm.get("sources")
        ):
            warnings.append(f"{rel}: machine-generated concept has no sources")
        # fingerprint staleness (any concept with a fingerprint)
        fp = fm.get("source_fingerprint")
        if fp is not None:
            fp = str(fp)
            srcs = fm.get("sources", [])
            for s in srcs:
                res = s.get("resource", "")
                if res.startswith("/"):
                    src_path = ROOT / res.lstrip("/")
                    if src_path.is_file():
                        actual = hashlib.sha256(src_path.read_bytes()).hexdigest()
                        if actual != fp:
                            errors.append(f"{rel}: stale source fingerprint")
                            break

    # 2. internal links resolve
    for path in md_files:
        rel = path.relative_to(bundle_dir).as_posix()
        text = path.read_text(encoding="utf-8")
        # find markdown links
        for m in re.finditer(r"\[[^\]]*\]\(([^)]+)\)", text):
            link = m.group(1)
            if link.startswith("http") or link.startswith("#") or link.startswith("mailto:"):
                continue
            target = link.split("#")[0]
            if not target:
                continue
            # bundle-relative (starts with /)
            if target.startswith("/"):
                resolved = bundle_dir / target.lstrip("/")
            else:
                resolved = (path.parent / target).resolve()
            if not resolved.exists():
                # broken link is a warning, not error (per spec, broken links allowed)
                warnings.append(f"{rel}: broken link -> {link}")

    # 3. index files present
    if not (bundle_dir / "index.md").exists():
        warnings.append("missing bundle root index.md")

    # report
    for w in warnings:
        print(f"WARN: {w}")
    for e in errors:
        print(f"ERROR: {e}")

    if errors:
        print(f"Validation failed: {len(errors)} error(s), {len(warnings)} warning(s).")
        return 1
    if strict and warnings:
        print(f"Strict mode: {len(warnings)} warning(s) treated as errors.")
        return 1
    print(f"Validation passed: {len(errors)} errors, {len(warnings)} warnings.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an OKF knowledge bundle")
    parser.add_argument("bundle_dir", nargs="?", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    return validate_bundle(args.bundle_dir.resolve(), strict=args.strict)


if __name__ == "__main__":
    sys.exit(main())
