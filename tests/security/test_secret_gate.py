"""Regression tests for the gitleaks secret gate (.gitleaks.toml).

The M0 planted-secret validation found that gitleaks' default ruleset filtered a
sequential-alphabet dummy PAT via its global allowlist, and missed our other secret
types entirely. The repo config adds strict rules for exactly the secret types this
project holds. These tests pin that behavior: realistic planted secrets MUST be
caught; the clean tree MUST pass.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.subproc

REPO_ROOT = Path(__file__).resolve().parents[2]

# Realistic-looking fakes (random tails — the default allowlist rightly ignores
# sequential-alphabet dummies, so test vectors must not contain long runs).
PLANTED = {
    "github-fine-grained-pat": (
        'token = "github_pat_11QK9mX2pT7vN4rW8zB3cD'
        '_5fG0hJkR6sL1yU9aE4iO7qM2xC8nV5bZ3tP0wS6dH1jF9gK4lA7rT2uY5mB"'
    ),
    "github-classic-pat": 'token = "ghp_x7K2mQ9pL4vN8rT3wY6zB1cD5fG0hJkMnPqR"',
    "anthropic-api-key": 'key = "sk-ant-api03-x7K2mQ9pL4vN8rT3wY6zB1cD5fG0hJkMnPqR"',
    "postgres-url-password": 'dsn = "postgresql://codeatlas_app:hunter2secret@localhost/db"',
}


def _gitleaks() -> str:
    exe = shutil.which("gitleaks")
    if exe is None:
        pytest.skip("gitleaks not on PATH")
    return exe


def _scan_dir(tmp_path: Path) -> int:
    """Run gitleaks dir-mode with the repo's config against tmp_path."""
    exe = _gitleaks()
    proc = subprocess.run(
        [
            exe,
            "dir",
            str(tmp_path),
            "--config",
            str(REPO_ROOT / ".gitleaks.toml"),
            "--redact",
            "--no-banner",
            "--exit-code",
            "9",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode in (0, 9), f"gitleaks failed unexpectedly: {proc.stderr}"
    return proc.returncode


@pytest.mark.parametrize("name", sorted(PLANTED))
def test_planted_secret_is_caught(tmp_path: Path, name: str) -> None:
    (tmp_path / "leak.txt").write_text(PLANTED[name] + "\n", encoding="utf-8")
    assert _scan_dir(tmp_path) == 9, f"planted {name} was NOT caught by the secret gate"


def test_benign_content_passes(tmp_path: Path) -> None:
    (tmp_path / "ok.txt").write_text(
        'url = "postgresql://localhost/codeatlas"\nname = "github_pat_placeholder"\n',
        encoding="utf-8",
    )
    assert _scan_dir(tmp_path) == 0


def test_repo_config_exists_and_extends_defaults() -> None:
    config = (REPO_ROOT / ".gitleaks.toml").read_text(encoding="utf-8")
    assert "useDefault = true" in config
    assert "codeatlas-github-fine-grained-pat" in config
    assert "codeatlas-anthropic-api-key" in config
