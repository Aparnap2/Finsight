"""Mypy baseline ratchet: CI rejects new strict errors without hiding debt.

Compares a fresh ``mypy .`` report against the recorded baseline as
multisets of ``path|message`` keys (line numbers intentionally excluded
so edits don't churn the baseline). Any difference in EITHER direction
fails: new errors list explicitly; resolved errors fail with the
``--update`` instruction so the baseline ratchets down monotonically in
the same commit as the fix. A missing or unreadable report fails closed.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

_ERROR_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_/.\-]*\.py):\d+: error: (.*)$")
_SUCCESS_MARKER = "Success: no issues found"


def parse_report(text: str) -> Counter[str] | None:
    """Parse mypy output into a key Counter, or None when unreadable.

    Returns an empty Counter for a clean run; None when the text has
    neither error lines nor the success marker (truncated/crashed run).
    """
    keys: Counter[str] = Counter()
    ok = False
    for raw_line in text.splitlines():
        line = re.sub(r"\x1b\[[0-9;]*m", "", raw_line).rstrip()
        if _SUCCESS_MARKER in line:
            ok = True
        match = _ERROR_RE.search(line)
        if match:
            ok = True
            keys[f"{match.group(1)}|{match.group(2)}"] += 1
    if not ok:
        return None
    return keys


def read_baseline(path: Path) -> Counter[str]:
    """Read a baseline file (``#`` comments and blanks skipped)."""
    keys: Counter[str] = Counter()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#"):
            keys[line] += 1
    return keys


def check(baseline: Counter[str], current: Counter[str]) -> tuple[list[str], list[str]]:
    """Return (new_keys, resolved_keys) expanded with multiplicities."""
    new: list[str] = []
    resolved: list[str] = []
    for key in sorted(set(baseline) | set(current)):
        delta = current.get(key, 0) - baseline.get(key, 0)
        if delta > 0:
            new.extend([key] * delta)
        elif delta < 0:
            resolved.extend([key] * -delta)
    return new, resolved


def main(argv: list[str] | None = None) -> int:
    """Run the ratchet check (or regenerate the baseline with --update)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, help="Baseline file path")
    parser.add_argument("--report", required=True, help="Fresh mypy output path")
    parser.add_argument(
        "--update",
        action="store_true",
        help="Rewrite the baseline from the report instead of checking",
    )
    args = parser.parse_args(argv)

    baseline_path = Path(args.baseline)
    report_path = Path(args.report)
    if not report_path.is_file():
        print(f"mypy-baseline: report missing: {report_path}", file=sys.stderr)
        return 1
    current = parse_report(report_path.read_text(encoding="utf-8", errors="replace"))
    if current is None:
        print("mypy-baseline: report unreadable (no errors, no success marker)", file=sys.stderr)
        return 1

    if args.update:
        lines = [
            "# mypy strict baseline: one `path|message` key per error occurrence.",
            "# Regenerate only alongside the fix commit: scripts/mypy_baseline_check.py --update",
        ]
        for key in sorted(current.elements()):
            lines.append(key)
        baseline_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"mypy-baseline: wrote {len(current)} entries to {baseline_path}")
        return 0

    if not baseline_path.is_file():
        print(f"mypy-baseline: baseline missing: {baseline_path}", file=sys.stderr)
        return 1
    baseline = read_baseline(baseline_path)
    new, resolved = check(baseline, current)
    total_base = sum(baseline.values())
    total_now = sum(current.values())
    print(
        f"mypy-baseline: recorded={total_base} current={total_now} "
        f"new={len(new)} resolved={len(resolved)}"
    )
    if new:
        print("mypy-baseline: NEW errors (fix or justify, never silence):", file=sys.stderr)
        for key in new[:50]:
            print(f"  + {key}", file=sys.stderr)
        return 1
    if resolved:
        print(
            "mypy-baseline: errors resolved without baseline update; "
            "re-run with --update and commit the smaller baseline.",
            file=sys.stderr,
        )
        return 1
    print("mypy-baseline: clean — no new errors, baseline matches exactly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
