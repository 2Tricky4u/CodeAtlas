"""Build throwaway git repositories from the committed fixture trees.

Fixtures are committed as plain directories (never nested .git); tests and the
CLI build real repos from them on demand. Returns the head SHA so callers can
pin immediately.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from codeatlas.vcs.git import GitClient

# MANIFEST.yaml is the evaluator's answer key: it names every planted bug and
# decoy. It must NEVER reach a built repo, or reviewer agents could read the
# answers and the recall/precision numbers would be meaningless. The evaluator
# loads it from the fixture source directory instead.
_EXCLUDE = {"target", ".git", "MANIFEST.yaml"}


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


# Fixed identity and timestamps make the built repository's SHA a pure function
# of its content. That determinism is load-bearing: replay cassettes are keyed on
# the analyzed revision, and golden artifacts embed it.
_FIXED_ENV = {
    "GIT_AUTHOR_NAME": "codeatlas-fixture",
    "GIT_AUTHOR_EMAIL": "fixture@codeatlas.local",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00",
    "GIT_COMMITTER_NAME": "codeatlas-fixture",
    "GIT_COMMITTER_EMAIL": "fixture@codeatlas.local",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
}


def build_fixture_repo(source_dir: Path, dest_dir: Path, git: GitClient | None = None) -> str:
    """Materialize `source_dir` as a fresh git repo at `dest_dir`; returns head SHA.

    The same source tree always yields the same SHA.
    """
    g = git or GitClient()
    dest_dir.mkdir(parents=True, exist_ok=True)
    _copy_tree(source_dir, dest_dir)
    g.run(["init", "-b", "main"], cwd=dest_dir, extra_env=_FIXED_ENV)
    g.run(["add", "-A"], cwd=dest_dir, extra_env=_FIXED_ENV)
    g.run(["commit", "-m", "fixture import"], cwd=dest_dir, extra_env=_FIXED_ENV)
    return g.resolve_sha(dest_dir, "HEAD")
