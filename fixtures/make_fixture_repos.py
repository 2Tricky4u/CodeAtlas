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


def build_pr_fixture_repo(
    source_dir: Path, dest_dir: Path, git: GitClient | None = None
) -> tuple[str, str]:
    """Build a repo whose `main` is defensive and whose `feature` branch adds B4.

    Returns (base_sha, head_sha). The base commit parses the wire request
    defensively; the feature commit replaces that with the unwrap chain, so the
    panic is genuinely *introduced by the change* — which is what changed-scope
    enforcement has to distinguish from a pre-existing defect.
    """
    g = git or GitClient()
    dest_dir.mkdir(parents=True, exist_ok=True)
    _copy_tree(source_dir, dest_dir)

    api = dest_dir / "kvstore" / "src" / "api.rs"
    flawed = api.read_text(encoding="utf-8")
    defensive = flawed.replace(
        "            let key = parts.next().unwrap().to_string();\n"
        "            let ttl_secs: u64 = parts.next().unwrap().parse().unwrap();\n",
        "            let Some(key) = parts.next().map(str::to_string) else {\n"
        '                return Response::Error("missing key".to_string());\n'
        "            };\n"
        "            let Some(Ok(ttl_secs)) = parts.next().map(str::parse::<u64>) else {\n"
        '                return Response::Error("bad ttl".to_string());\n'
        "            };\n",
    )
    if defensive == flawed:
        raise RuntimeError("PR fixture: could not build the defensive base revision")

    api.write_text(defensive, encoding="utf-8", newline="\n")
    g.run(["init", "-b", "main"], cwd=dest_dir, extra_env=_FIXED_ENV)
    g.run(["add", "-A"], cwd=dest_dir, extra_env=_FIXED_ENV)
    g.run(["commit", "-m", "kvstore at base revision"], cwd=dest_dir, extra_env=_FIXED_ENV)
    base_sha = g.resolve_sha(dest_dir, "HEAD")

    g.run(["checkout", "-b", "feature"], cwd=dest_dir, extra_env=_FIXED_ENV)
    api.write_text(flawed, encoding="utf-8", newline="\n")
    g.run(["add", "-A"], cwd=dest_dir, extra_env=_FIXED_ENV)
    g.run(["commit", "-m", "simplify put parsing"], cwd=dest_dir, extra_env=_FIXED_ENV)
    head_sha = g.resolve_sha(dest_dir, "HEAD")
    return base_sha, head_sha


_EVICT_OLDEST = """    /// Evict the `n` oldest entries.
    pub fn evict_oldest(&mut self, n: usize) {
        for _ in 0..=n {
            if let Some(oldest) = self.order.pop_front() {
                self.map.remove(&oldest);
            }
        }
    }
"""

_EVICT_REPLACEMENT = """    /// Evict the `n` oldest entries, returning how many were removed.
    pub fn evict(&mut self, n: usize) -> usize {
        let mut removed = 0;
        for _ in 0..n {
            match self.order.pop_front() {
                Some(oldest) => {
                    self.map.remove(&oldest);
                    removed += 1;
                }
                None => break,
            }
        }
        removed
    }

    /// The configured maximum number of entries.
    pub fn capacity(&self) -> usize {
        self.max_entries
    }
"""


def build_api_change_fixture_repo(
    source_dir: Path, dest_dir: Path, git: GitClient | None = None
) -> tuple[str, str]:
    """Build a repo whose feature branch changes the crate's *public API*.

    Returns (base_sha, head_sha). `Cache::evict_oldest` is removed and replaced
    by `Cache::evict`, and `Cache::capacity` is added — one breaking removal and
    two additions. The other pull-request fixture deliberately changes only
    function bodies, which is the right shape for scope enforcement and the wrong
    shape for proving an API delta: a before/after that reports no change cannot
    tell "nothing changed" apart from "nothing was measured".
    """
    g = git or GitClient()
    dest_dir.mkdir(parents=True, exist_ok=True)
    _copy_tree(source_dir, dest_dir)

    g.run(["init", "-b", "main"], cwd=dest_dir, extra_env=_FIXED_ENV)
    g.run(["add", "-A"], cwd=dest_dir, extra_env=_FIXED_ENV)
    g.run(["commit", "-m", "kvstore at base revision"], cwd=dest_dir, extra_env=_FIXED_ENV)
    base_sha = g.resolve_sha(dest_dir, "HEAD")

    cache = dest_dir / "kvstore" / "src" / "cache.rs"
    before = cache.read_text(encoding="utf-8")
    if _EVICT_OLDEST not in before:
        raise RuntimeError("API fixture: evict_oldest is not where the builder expects it")
    after = before.replace(_EVICT_OLDEST, _EVICT_REPLACEMENT).replace(
        "self.evict_oldest(overflow + 1);", "self.evict(overflow + 1);"
    )
    cache.write_text(after, encoding="utf-8", newline="\n")

    g.run(["checkout", "-b", "feature"], cwd=dest_dir, extra_env=_FIXED_ENV)
    g.run(["add", "-A"], cwd=dest_dir, extra_env=_FIXED_ENV)
    g.run(["commit", "-m", "replace evict_oldest with evict"], cwd=dest_dir, extra_env=_FIXED_ENV)
    return base_sha, g.resolve_sha(dest_dir, "HEAD")


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
