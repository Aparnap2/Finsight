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


def _tree(tmp_path: Path, files: dict[str, str | bytes]) -> Path:
    """Build a fixture tree from name -> content (always a git repo).

    The tracked-dotenv guard is fail-closed: it requires a readable git
    index, so every fixture tree is initialized as one.
    """
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)
    for name, content in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
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

    def test_non_repo_root_fails_closed(self, tmp_path: Path) -> None:
        (tmp_path / "apps").mkdir(parents=True, exist_ok=True)
        (tmp_path / "apps" / "a.py").write_text("x = 1\n")
        proc = _run(tmp_path)  # no git init: index absence unprovable
        assert proc.returncode == 2
        assert "SCAN_ERROR" in proc.stdout

    def test_nul_padded_secret_still_detected(self, tmp_path: Path) -> None:
        root = _tree(tmp_path, {"apps/blob.bin": b"\x00" + _key().encode() + b"\x00"})
        proc = _run(root)
        assert proc.returncode == 1
        assert "LEAK" in proc.stdout

    def test_venv_by_marker_skipped(self, tmp_path: Path) -> None:
        root = _tree(
            tmp_path,
            {
                "customenv/pyvenv.cfg": "home = /x\n",
                "customenv/bin/python": b"\xff\xfe\x00binary",
            },
        )
        proc = _run(root)
        assert proc.returncode == 0

    def test_undecodable_text_fails_closed(self, tmp_path: Path) -> None:
        root = _tree(tmp_path, {"apps/odd.txt": b"caf\xe9key sk-live-abc123 \x92special"})
        proc = _run(root)
        assert proc.returncode == 2
        assert "undecodable" in proc.stdout

    def test_git_missing_fails_closed(self, tmp_path: Path) -> None:
        import os

        root = _tree(tmp_path, {"apps/a.py": "x = 1\n"})
        empty_path = tmp_path / "emptybin"
        empty_path.mkdir(exist_ok=True)
        env = {**os.environ, "PATH": str(empty_path)}
        proc = subprocess.run(
            [sys.executable, str(GATE), str(root)],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        assert proc.returncode == 2
        assert "SCAN_ERROR" in proc.stdout

    def _git_repo(self, tmp_path: Path, tracked: dict[str, str]) -> Path:
        """Init a git repo with the given tracked files (content irrelevant)."""
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
        subprocess.run(
            ["git", "-C", str(tmp_path), "config", "user.email", "t@t"],
            check=True,
        )
        subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)
        for name, content in tracked.items():
            target = tmp_path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
            subprocess.run(["git", "-C", str(tmp_path), "add", name], check=True)
        return tmp_path

    def test_tracked_dotenv_fails_paths_only(self, tmp_path: Path) -> None:
        repo = self._git_repo(
            tmp_path,
            {
                ".env.staging": "SUPER_SEKRET_VALUE_12345\n",
                "apps/a.py": "x = 1\n",
            },
        )
        proc = _run(repo)
        assert proc.returncode == 1
        assert ".env.staging" in proc.stdout
        assert "SUPER_SEKRET_VALUE_12345" not in proc.stdout

    def test_tracked_root_dotenv_fails(self, tmp_path: Path) -> None:
        repo = self._git_repo(tmp_path, {".env": "K=v\n"})
        proc = _run(repo)
        assert proc.returncode == 1
        assert "tracked dotenv" in proc.stdout

    def test_tracked_env_example_allowed(self, tmp_path: Path) -> None:
        repo = self._git_repo(tmp_path, {".env.example": "K=placeholder\n"})
        proc = _run(repo)
        assert proc.returncode == 0

    def test_untracked_live_dotenv_still_skipped(self, tmp_path: Path) -> None:
        repo = self._git_repo(tmp_path, {"apps/a.py": "x = 1\n"})
        (tmp_path / ".env").write_text("LIVE_KEY=abc\n")  # untracked: APA-79
        proc = _run(repo)
        assert proc.returncode == 0
