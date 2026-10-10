"""Fail-closed secret scan (APA-80 R3): dependency-free, stdlib only.

Replaces the shell/rg gate (rg is not on the CI runner PATH, and the
old ``! rg`` polarity masked that as green). Exit codes:

- 1 (LEAK) on any match or blocked filename.
- 2 (SCAN_ERROR) on unreadable roots (never silently green).
- 0 when clean.

Scope (documented carve-outs, see ci.yml):

- High-signal shapes repo-wide (private keys, AKIA, ghp/gho/pat,
  sk-ant, xoxb, sk-or-v1, gsk_).
- Canary shapes (Stripe-test-like and bearer-token-like literals)
  everywhere EXCEPT ``tests/`` (intentional sanitizer fixtures) and
  the repo-root ``.env`` (live credential store owned by APA-79).
- Blocked filenames (``*.pem``, ``id_rsa*``, ``.env.*``) excluding
  dependency directories. The repo-root ``.env`` itself is APA-79's.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HIGH_SIGNAL = re.compile(
    r"AKIA[0-9A-Z]{16}"
    r"|BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY"
    r"|ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9]{20,}"
    r"|sk-ant-[A-Za-z0-9-]{10,}|xoxb-[A-Za-z0-9-]{10,}"
    r"|sk-or-v1-[A-Za-z0-9]{10,}|gsk_[A-Za-z0-9]{10,}"
)
# Built from fragments so this scanner's own source contains no literal
# canary shape (otherwise the gate would always flag itself). Canaries
# require a trailing payload (>= 4 chars) so bare pattern-name mentions
# in docs (e.g. bare pattern-name mentions) do not flag.
_CANARY_SRC = (
    "s" + "k_live[_-]?[A-Za-z0-9._~+-]{4,}|s" + "k-live[_-]?[A-Za-z0-9._~+-]{4,}"
    "|Bearer [A-Za-z0-9._~+/=-]{8}"
)
CANARY = re.compile(_CANARY_SRC)

SKIP_DIRS = {
    ".git",
    ".venv",
    "volume",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".hypothesis",
    "node_modules",
    "dist",
    "build",
    ".next",
}
BLOCKED_NAMES = (".pem", "id_rsa")

#: Well-known placeholder tokens that are never real secrets.
PLACEHOLDERS = frozenset({"redacted", "example", "placeholder", "changeme", "yourkey", "testkey"})

#: Known-binary asset suffixes skipped by extension (auditable list).
#: Everything else is decoded after NUL-stripping and scanned; undecodable
#: remainder fails closed. Unknown binaries (e.g. `.bin`) are scanned,
#: not skipped — a NUL-padded secret in one still flags.
BINARY_SUFFIXES = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".ico",
        ".webp",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".otf",
        ".pdf",
        ".zip",
        ".gz",
        ".tar",
        ".whl",
        ".so",
        ".dylib",
        ".dll",
        ".exe",
    }
)


def _is_placeholder(token: str) -> bool:
    """Return True for obvious non-secret placeholder tokens."""
    folded = token.lower()
    if folded in PLACEHOLDERS:
        return True
    return len(set(folded)) == 1  # "xxxxxxxx", "00000000", "***..."


def _canary_hit(text: str) -> bool:
    """Return True when a non-placeholder canary shape is present."""
    for match in CANARY.finditer(text):
        token = match.group(0).split(None, 1)[-1]
        if not _is_placeholder(token):
            return True
    return False


def _venv_roots(root: Path) -> list[Path]:
    """Directories containing pyvenv.cfg (virtualenvs by marker, not name)."""
    return [p.parent for p in root.glob("*/pyvenv.cfg")]


def _iter_files(root: Path) -> list[Path]:
    """Collect scannable files, skipping dependency and cache trees."""
    collected: list[Path] = []
    venv_tops = {str(v.relative_to(root)) for v in _venv_roots(root)}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if rel_parts[0] in venv_tops:
            continue  # virtualenv tree (pyvenv.cfg marker)
        parts = set(rel_parts[:-1])
        if parts & SKIP_DIRS or any(part.startswith(".venv") for part in rel_parts):
            continue
        if path.suffix == ".pyc":
            continue
        collected.append(path)
    return collected


def scan(root: Path) -> list[str]:
    """Return human-readable findings (empty means clean)."""
    findings: list[str] = []
    try:
        files = _iter_files(root)
    except OSError as exc:
        print(f"SCAN_ERROR cannot list {root}: {exc}")
        raise SystemExit(2) from exc
    for path in sorted(files):
        rel = str(path.relative_to(root))
        name = path.name
        if name.endswith(BLOCKED_NAMES) or (name.startswith(".env.") and name != ".env.example"):
            findings.append(f"{rel}: blocked filename")
            continue
        if rel == ".env":
            continue  # live credential store; owned by APA-79
        if path.suffix.lower() in BINARY_SUFFIXES:
            continue  # known-binary asset, not a literal carrier
        try:
            raw = path.read_bytes()
        except OSError as exc:
            # A file that should be scanned but cannot be read must fail
            # the gate — never silently skipped (review finding on R3).
            print(f"SCAN_ERROR unreadable file {rel}: {exc}")
            raise SystemExit(2) from exc
        # NUL bytes are stripped before decoding so a NUL-padded secret
        # cannot evade the scan; undecodable remainder still fails closed.
        try:
            text = raw.replace(b"\x00", b"").decode("utf-8")
        except UnicodeDecodeError as exc:
            print(f"SCAN_ERROR undecodable text file {rel}: {exc}")
            raise SystemExit(2) from exc
        if HIGH_SIGNAL.search(text):
            findings.append(f"{rel}: high-signal secret shape")
        elif rel.startswith("tests/"):
            continue  # intentional sanitizer canaries
        elif _canary_hit(text):
            findings.append(f"{rel}: canary secret shape")
    return findings


def main(argv: list[str] | None = None) -> int:
    """Entry point: scan the repo root given as argv[1] (default cwd)."""
    root = Path(argv[1] if argv and len(argv) > 1 else ".")
    if not root.is_dir():
        print(f"SCAN_ERROR unreadable root: {root}")
        return 2
    findings = scan(root)
    for finding in findings:
        print(f"LEAK {finding}")
    if findings:
        return 1
    print("secret gate: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
