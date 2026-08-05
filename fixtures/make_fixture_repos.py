"""Build throwaway git repositories from the committed fixture trees.

Fixtures are committed as plain directories (never nested .git); tests and the
CLI build real repos from them on demand. Returns the head SHA so callers can
pin immediately.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from codeatlas.vcs.git import GitClient

_EXCLUDE = {"target", ".git"}


def _copy_tree(src: Path, dest: Path) -> None:
    for item in src.iterdir():
        if item.name in _EXCLUDE:
            continue
        target = dest / item.name
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            _copy_tree(item, target)
        else:
            shutil.copy2(item, target)


def build_fixture_repo(source_dir: Path, dest_dir: Path, git: GitClient | None = None) -> str:
    """Materialize `source_dir` as a fresh git repo at `dest_dir`; returns head SHA."""
    g = git or GitClient()
    dest_dir.mkdir(parents=True, exist_ok=True)
    _copy_tree(source_dir, dest_dir)
    g.run(["init", "-b", "main"], cwd=dest_dir)
    g.run(["add", "-A"], cwd=dest_dir)
    g.run(["commit", "-m", "fixture import"], cwd=dest_dir)
    return g.resolve_sha(dest_dir, "HEAD")
