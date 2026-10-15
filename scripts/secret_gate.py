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
- Tracked dotenv guard: any ``.env`` / ``.env.*`` in the git index
  (except ``.env.example``) fails, paths only, never contents — so the
  content-scan carve-out for the untracked live ``.env`` cannot hide a
  committed dotenv file.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Literal

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
BLOCKED_SUFFIXES = (".pem",)
BLOCKED_PREFIXES = ("id_rsa",)

#: Well-known placeholder tokens that are never real secrets.
PLACEHOLDERS = frozenset({"redacted", "example", "placeholder", "changeme", "yourkey", "testkey"})

#: Known-binary asset suffixes skipped by extension (auditable list).
#: Archive formats (.zip/.whl/.tar/.gz) are NOT skipped: their member
#: names and decodable contents are inspected instead (see below).
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
        ".so",
        ".dylib",
        ".dll",
        ".exe",
    }
)

#: Archive suffixes whose members are inspected (names + decodable text).
ARCHIVE_SUFFIXES = frozenset({".zip", ".whl", ".tar", ".tgz", ".gz"})

#: Per-member and per-archive read caps (fail-closed, not silent skip).
_MAX_MEMBER_BYTES = 1_000_000
_MAX_ARCHIVE_BYTES = 5_000_000


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


def _member_name_hit(member: str) -> bool:
    """Return True when an archive member name is itself blocked."""
    base = member.rsplit("/", 1)[-1]
    return (
        base.endswith(BLOCKED_SUFFIXES)
        or base.startswith(BLOCKED_PREFIXES)
        or (base.startswith(".env.") and base != ".env.example")
        or base == ".env"
    )


def _scan_text_blob(blob: bytes, origin: str) -> list[str]:
    """Scan decodable bytes; fail closed when undecodable."""
    try:
        text = blob.replace(b"\x00", b"").decode("utf-8")
    except UnicodeDecodeError as exc:
        print(f"SCAN_ERROR undecodable text {origin}: {exc}")
        raise SystemExit(2) from exc
    findings: list[str] = []
    if HIGH_SIGNAL.search(text):
        findings.append(f"{origin}: high-signal secret shape")
    elif _canary_hit(text):
        findings.append(f"{origin}: canary secret shape")
    return findings


class _OverrunError(Exception):
    """Decompressed read exceeded its bound (zip-bomb guard)."""


def _bounded_read(stream: Any, cap: int, origin: str, total: list[int]) -> bytes:
    """Stream at most cap+1 bytes; fail closed on overrun or total breach."""
    chunks: list[bytes] = []
    remaining = cap + 1
    while True:
        piece = stream.read(min(65536, remaining))
        if not piece:
            break
        chunks.append(piece)
        remaining -= len(piece)
        total[0] += len(piece)
        if remaining <= 0 or total[0] > _MAX_ARCHIVE_BYTES:
            raise _OverrunError(origin)
    return b"".join(chunks)


def _archive_findings(path: Path, rel: str) -> list[str]:
    """Inspect archive member names and decodable member text."""
    import gzip
    import tarfile
    import zipfile

    findings: list[str] = []
    suffix = path.suffix.lower()
    members: list[tuple[str, bytes]] = []
    total = [0]
    try:
        if suffix in (".zip", ".whl"):
            with zipfile.ZipFile(path) as archive:
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    if info.file_size > _MAX_MEMBER_BYTES:
                        print(f"SCAN_ERROR oversized archive member {rel}!{info.filename}")
                        raise SystemExit(2)
                    with archive.open(info) as stream:
                        try:
                            blob = _bounded_read(stream, _MAX_MEMBER_BYTES, info.filename, total)
                        except _OverrunError:
                            print(f"SCAN_ERROR oversized archive member {rel}!{info.filename}")
                            raise SystemExit(2) from None
                    members.append((info.filename, blob))
        elif suffix in (".tar", ".tgz") or suffix == ".gz":
            import contextlib

            tar_members: list[tuple[str, int, Any]] = []
            archive: Any = None
            tar_mode: Literal["r:gz", "r"] = "r:gz" if suffix == ".gz" else "r"
            for mode in (tar_mode,):
                candidate = None
                try:
                    # Managed manually (closed below): the winning handle
                    # must survive beyond this block.
                    candidate = tarfile.open(path, mode)  # noqa: SIM115
                    for member in candidate.getmembers():
                        if member.isfile():
                            tar_members.append((member.name, member.size, member))
                    archive = candidate
                    candidate = None
                    break
                except tarfile.TarError:
                    continue
                finally:
                    if candidate is not None:
                        candidate.close()
            if archive is None:
                if suffix != ".gz":
                    # No tar mode could open this file: corrupt, fail closed.
                    print(f"SCAN_ERROR unreadable archive {rel}")
                    raise SystemExit(2)
                with gzip.open(path, "rb") as handle:
                    try:
                        blob = _bounded_read(handle, _MAX_ARCHIVE_BYTES, rel, total)
                    except _OverrunError:
                        print(f"SCAN_ERROR archive too large to scan {rel}")
                        raise SystemExit(2) from None
                members = [(path.name, blob)]
            else:
                with contextlib.closing(archive):
                    for member_name, declared, member in tar_members:
                        if declared > _MAX_MEMBER_BYTES:
                            print(f"SCAN_ERROR oversized archive member {rel}!{member_name}")
                            raise SystemExit(2)
                        extracted = archive.extractfile(member)
                        if extracted is None:
                            continue
                        try:
                            blob = _bounded_read(extracted, _MAX_MEMBER_BYTES, member_name, total)
                        except _OverrunError:
                            print(f"SCAN_ERROR oversized archive member {rel}!{member_name}")
                            raise SystemExit(2) from None
                        members.append((member_name, blob))
        else:
            return findings
    except (OSError, EOFError, zipfile.BadZipFile, tarfile.TarError) as exc:
        print(f"SCAN_ERROR unreadable archive {rel}: {exc}")
        raise SystemExit(2) from exc
    for member_name, blob in members:
        if _member_name_hit(member_name):
            findings.append(f"{rel}!{member_name}: blocked member name")
            continue
        if Path(member_name).suffix.lower() in BINARY_SUFFIXES:
            continue
        findings.extend(_scan_text_blob(blob, f"{rel}!{member_name}"))
    return findings


def _venv_roots(root: Path) -> list[Path]:
    """Directories containing pyvenv.cfg (virtualenvs by marker, not name)."""
    return [p.parent for p in root.rglob("pyvenv.cfg")]


def _iter_files(root: Path) -> list[Path]:
    """Collect scannable files, skipping dependency and cache trees.

    Uses os.walk with an error handler: unreadable subtrees fail closed
    (pathlib.rglob silently skips them, contradicting this gate).
    """
    import os

    collected: list[Path] = []
    failures: list[str] = []

    def _onerror(exc: OSError) -> None:
        failures.append(f"{exc.filename or '?'}: {exc.strerror}")

    venv_tops = {str(v.relative_to(root)) for v in _venv_roots(root)}
    for dirpath, dirnames, filenames in os.walk(root, onerror=_onerror, followlinks=False):
        current = Path(dirpath)
        try:
            rel_dir = current.relative_to(root)
        except ValueError:
            continue
        if "pyvenv.cfg" in filenames:
            dirnames[:] = []
            continue  # virtualenv subtree (marker beats pre-scan depth)
        if rel_dir.parts and (
            rel_dir.parts[0] in venv_tops
            or set(rel_dir.parts) & SKIP_DIRS
            or any(part.startswith(".venv") for part in rel_dir.parts)
        ):
            dirnames[:] = []
            continue
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in SKIP_DIRS and not d.startswith(".venv") and d != "__pycache__"
        )
        for name in sorted(filenames):
            if name.endswith(".pyc"):
                continue
            collected.append(current / name)
    if failures:
        print(f"SCAN_ERROR unreadable directories: {'; '.join(sorted(failures))}")
        raise SystemExit(2)
    return collected


def tracked_env_files(root: Path) -> list[str]:
    """Return git-tracked dotenv files that must never be committed.

    The content scan carves out the untracked repo-root ``.env`` (live
    credential store, APA-79). That carve-out must not extend to TRACKED
    files: any ``.env`` / ``.env.*`` in the git index — except the
    conventional safe template ``.env.example`` — fails the gate.
    Only paths are reported, never file contents.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        print(f"SCAN_ERROR git unavailable: {exc}")
        raise SystemExit(2) from exc
    if proc.returncode != 0:
        # Not a git checkout or index unreadable: the tracked check cannot
        # establish absence, so the gate fails rather than reporting clean.
        print("SCAN_ERROR cannot inspect git index (not a repository?)")
        raise SystemExit(2)
    offenders: list[str] = []
    for line in proc.stdout.splitlines():
        name = line.strip().rsplit("/", 1)[-1]
        if name == ".env.example":
            continue
        if name == ".env" or name.startswith(".env."):
            offenders.append(line.strip())
    return sorted(offenders)


def scan(root: Path) -> list[str]:
    """Return human-readable findings (empty means clean)."""
    findings: list[str] = []
    for offender in tracked_env_files(root):
        findings.append(f"{offender}: tracked dotenv file must not be committed")
    try:
        files = _iter_files(root)
    except OSError as exc:
        print(f"SCAN_ERROR cannot list {root}: {exc}")
        raise SystemExit(2) from exc
    for path in sorted(files):
        rel = str(path.relative_to(root))
        name = path.name
        if (
            name.endswith(BLOCKED_SUFFIXES)
            or name.startswith(BLOCKED_PREFIXES)
            or (name.startswith(".env.") and name != ".env.example")
        ):
            findings.append(f"{rel}: blocked filename")
            continue
        if rel == ".env":
            continue  # live credential store; owned by APA-79
        if path.suffix.lower() in ARCHIVE_SUFFIXES:
            findings.extend(_archive_findings(path, rel))
            continue
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
