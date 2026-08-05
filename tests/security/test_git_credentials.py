"""The GitHub token must never persist to disk or appear in a receipt.

Embedding a credential in a remote URL is the usual shortcut, and it writes the
token into `.git/config`, where it survives the run and lands in any backup of
the workdir. Passing it on the command line exposes it to every process that can
list processes. Neither is acceptable, so the token travels in git's
environment-based config.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codeatlas.vcs.git import GitClient

pytestmark = pytest.mark.subproc

# A synthetic token that belongs to nothing; it exists to prove the real one
# never reaches disk.
TOKEN = "github_pat_11QK9mX2pT7vN4rW8zB3cD_5fG0hJkR6sL1yU9aE4iO7qM2xC8nV5bZ3tP0wS6dH1jF9gK4lA7"  # noqa: S105


def test_auth_env_is_built_only_when_a_token_is_present() -> None:
    assert GitClient()._auth_env() == {}
    env = GitClient(github_token=TOKEN)._auth_env()
    assert env["GIT_CONFIG_COUNT"] == "1"
    assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
    assert env["GIT_CONFIG_VALUE_0"].startswith("AUTHORIZATION: basic ")


def test_the_raw_token_is_not_placed_verbatim_in_the_env_value() -> None:
    """It is base64 of `x-access-token:<token>`, matching git's expected form."""
    import base64

    value = GitClient(github_token=TOKEN)._auth_env()["GIT_CONFIG_VALUE_0"]
    encoded = value.removeprefix("AUTHORIZATION: basic ")
    assert TOKEN not in value
    assert base64.b64decode(encoded).decode() == f"x-access-token:{TOKEN}"


def test_receipts_never_contain_the_token(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    client = GitClient(github_token=TOKEN)
    client.run(["init", "-b", "main"], cwd=repo)
    client.run(["status"], cwd=repo)

    assert client.receipts
    for receipt in client.receipts:
        assert TOKEN not in receipt.command


def test_token_is_not_written_into_git_config(tmp_path: Path) -> None:
    """The decisive property: nothing on disk holds the credential afterwards."""
    source = tmp_path / "source"
    source.mkdir()
    plain = GitClient()
    plain.run(["init", "-b", "main"], cwd=source)
    (source / "a.txt").write_text("x\n", encoding="utf-8")
    plain.run(["add", "-A"], cwd=source)
    plain.run(["commit", "-m", "initial"], cwd=source)

    client = GitClient(github_token=TOKEN)
    mirror = tmp_path / "mirror.git"
    client.mirror_clone(str(source), mirror)

    config = (mirror / "config").read_text(encoding="utf-8")
    assert TOKEN not in config
    assert "extraheader" not in config.lower()

    for path in mirror.rglob("*"):
        if path.is_file() and path.stat().st_size < 1_000_000:
            assert TOKEN not in path.read_bytes().decode("utf-8", "ignore"), path
