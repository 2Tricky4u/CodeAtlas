"""Source lock: pin exactly what a run analyzes (stage 1 of the pipeline).

Repository mode pins a single head revision; PR mode additionally pins base,
merge-base, and the changed-path set. Generated/vendored files are classified
so review stages can scope findings to hand-written code.
"""

from __future__ import annotations

import re
from pathlib import Path

from codeatlas.models.manifest import SourceLock
from codeatlas.vcs.git import GitClient

# Path patterns considered generated or vendored. Order-independent; matching is
# on the repo-relative forward-slash path.
_GENERATED_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(^|/)Cargo\.lock$"),
    re.compile(r"(^|/)package-lock\.json$"),
    re.compile(r"(^|/)uv\.lock$"),
    re.compile(r"(^|/)target/"),
    re.compile(r"(^|/)node_modules/"),
    re.compile(r"(^|/)dist/"),
    re.compile(r"(^|/)build/"),
    re.compile(r"\.min\.(js|css)$"),
    re.compile(r"\.(pb|pb2|generated)\.\w+$"),
    re.compile(r"_pb2(_grpc)?\.py$"),
)


def classify_generated(paths: list[str]) -> list[str]:
    """Return the sorted subset of `paths` classified as generated/vendored."""
    return sorted(p for p in paths if any(rx.search(p) for rx in _GENERATED_PATTERNS))


def build_source_lock(
    repo: Path,
    repository_id: str,
    head_ref: str,
    base_ref: str | None = None,
    remote_url: str | None = None,
    git: GitClient | None = None,
) -> SourceLock:
    g = git or GitClient()
    head_sha = g.resolve_sha(repo, head_ref)

    if base_ref is None:
        tree_paths = [e.path for e in g.ls_tree(repo, head_sha)]
        return SourceLock(
            repository_id=repository_id,
            remote_url=remote_url,
            head_sha=head_sha,
            base_sha=None,
            merge_base_sha=None,
            changed_paths=[],
            generated_paths=classify_generated(tree_paths),
        )

    base_sha = g.resolve_sha(repo, base_ref)
    merge_base_sha = g.merge_base(repo, base_sha, head_sha)
    changed = g.changed_paths(repo, merge_base_sha, head_sha)
    return SourceLock(
        repository_id=repository_id,
        remote_url=remote_url,
        head_sha=head_sha,
        base_sha=base_sha,
        merge_base_sha=merge_base_sha,
        changed_paths=changed,
        generated_paths=classify_generated(changed),
    )
