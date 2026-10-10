"""Unit tests for scripts/secret_gate.py (APA-80 R3).

The gate is fail-closed and dependency-free: leaks fail, scan errors
fail, and only a clean tree passes. Fixtures use synthetic canaries.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

GATE = Path(__file__).resolve().parents[3] / "scripts" / "secret_gate.py"


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    """Run the gate against a fixture tree."""
    return subprocess.run(
        [sys.executable, str(GATE), str(root)],
        capture_output=True,
        text=True,
        check=False,
    )


def _key() -> str:
    """Synthetic high-signal key, built so no literal shape sits in this file."""
    return "AKIA" + "X" * 16


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    """Build a fixture tree from name -> content."""
    for name, content in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    return tmp_path


class TestSecretGate:
    def test_clean_tree_passes(self, tmp_path: Path) -> None:
        root = _tree(tmp_path, {"apps/a.py": "x = 1\n", "README.md": "hello\n"})
        proc = _run(root)
        assert proc.returncode == 0
        assert "secret gate: clean" in proc.stdout

    def test_high_signal_shape_fails(self, tmp_path: Path) -> None:
        root = _tree(tmp_path, {"apps/a.py": 'key = "' + _key() + '"\n'})
        proc = _run(root)
        assert proc.returncode == 1
        assert "LEAK" in proc.stdout

    def test_private_key_fails(self, tmp_path: Path) -> None:
        root = _tree(tmp_path, {"docs/k.txt": "-----BEGIN " + "RSA PRIVATE KEY-----\nabc\n"})
        proc = _run(root)
        assert proc.returncode == 1

    def test_canary_outside_tests_fails(self, tmp_path: Path) -> None:
        root = _tree(tmp_path, {"apps/a.py": 'token = "sk-live-abc123"\n'})
        proc = _run(root)
        assert proc.returncode == 1

    def test_canary_inside_tests_allowed(self, tmp_path: Path) -> None:
        root = _tree(tmp_path, {"tests/unit/t.py": 'token = "sk-live-abc123"\n'})
        proc = _run(root)
        assert proc.returncode == 0

    def test_high_signal_inside_tests_still_fails(self, tmp_path: Path) -> None:
        root = _tree(tmp_path, {"tests/unit/t.py": 'key = "' + _key() + '"\n'})
        proc = _run(root)
        assert proc.returncode == 1

    def test_blocked_filename_fails(self, tmp_path: Path) -> None:
        root = _tree(tmp_path, {"deploy/key.pem": "not a key\n"})
        proc = _run(root)
        assert proc.returncode == 1

    def test_venvs_and_caches_skipped(self, tmp_path: Path) -> None:
        root = _tree(
            tmp_path,
            {
                ".venv/lib/x.py": 'k = "' + _key() + '"\n',
                "__pycache__/a.pyc": "x",
                "volume/data.txt": 'k = "' + _key() + '"\n',
            },
        )
        proc = _run(root)
        assert proc.returncode == 0

    def test_missing_root_fails_closed(self, tmp_path: Path) -> None:
        proc = _run(tmp_path / "does-not-exist")
        assert proc.returncode == 2
        assert "SCAN_ERROR" in proc.stdout

    def test_binary_file_skipped_not_failed(self, tmp_path: Path) -> None:
        target = tmp_path / "apps" / "blob.bin"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"\x00\x01\x02binary\xff\xfe")
        proc = _run(tmp_path)
        assert proc.returncode == 0

    def test_undecodable_text_fails_closed(self, tmp_path: Path) -> None:
        target = tmp_path / "apps" / "odd.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"caf\xe9key sk-live-abc123 \x92special")
        proc = _run(tmp_path)
        assert proc.returncode == 2
        assert "SCAN_ERROR" in proc.stdout
