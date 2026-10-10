"""CI completeness gate (APA-80 R1): fail green-but-incomplete runs.

Parses a teed ``pytest -q`` log and enforces:

- FAIL (exit 2, ``NO_PASSING_TESTS``) when zero tests passed.
- FAIL (exit 2, ``NO_SUMMARY``) when no summary line exists
  (collection error, empty run, stub output).
- FAIL (exit 2, ``SKIP_BUDGET_EXCEEDED``) when skips exceed budget.
  Budgets are per-job and documented in the workflows; expected
  environment-gated skips (e.g. SQS E2E in CI) fit inside them.
- PASS (exit 0) otherwise, echoing ``passed=``/``failed=``/``skipped=``
  for the job summary.

Test failures themselves are NOT this script's question: the pytest
step already fails on those (pipefail). stdlib only.
"""

from __future__ import annotations

import argparse
import re
import sys

_SUMMARY_RE = re.compile(
    r"^(?:(?P<failed>\d+) failed)?,?\s*"
    r"(?:(?P<passed>\d+) passed)?,?\s*"
    r"(?:(?P<skipped>\d+) skipped)?,?\s*"
    r"(?:(?P<errors>\d+) errors?)?,?\s*.*in [\d.]+s\s*$"
)


def _parse_counts(log: str) -> dict[str, int] | None:
    """Return counts from the last pytest summary line, else None."""
    for line in reversed(log.splitlines()):
        match = _SUMMARY_RE.match(line.strip())
        if match:
            counts = {key: int(value) for key, value in match.groupdict().items() if value}
            if counts:
                return counts
    return None


def main(argv: list[str] | None = None) -> int:
    """Entry point: evaluate one teed pytest log against the gate."""
    parser = argparse.ArgumentParser(description="Fail green-but-incomplete CI runs.")
    parser.add_argument("log", help="Path to the teed pytest output log.")
    parser.add_argument("--max-skips", type=int, default=10**9)
    args = parser.parse_args(argv)

    try:
        with open(args.log, encoding="utf-8") as handle:  # noqa: PTH123 - CLI path arg
            log = handle.read()
    except OSError as exc:
        print(f"NO_SUMMARY unreadable log: {exc}")
        return 2

    counts = _parse_counts(log)
    if counts is None:
        print("NO_SUMMARY no pytest summary line found")
        return 2
    passed = counts.get("passed", 0)
    failed = counts.get("failed", 0)
    skipped = counts.get("skipped", 0)
    print(f"passed={passed} failed={failed} skipped={skipped}")
    if passed == 0:
        print("NO_PASSING_TESTS zero tests passed")
        return 2
    if skipped > args.max_skips:
        print(f"SKIP_BUDGET_EXCEEDED skipped={skipped} budget={args.max_skips}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
