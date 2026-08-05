"""Resolving an analysis source, whether it is a local path or a remote URL.

The mirror is created first and everything is resolved *from the mirror*, so a
clone URL and a directory on disk behave identically. Resolving against the
source directly only works for local paths — and passing a URL there produced a
Windows "invalid directory name" error rather than anything diagnosable.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from codeatlas.pipeline.deps import PipelineDeps

_REMOTE_PREFIXES = ("http://", "https://", "git://", "ssh://", "git@")


def is_remote(source: str) -> bool:
    return source.startswith(_REMOTE_PREFIXES)


def mirror_path(deps: PipelineDeps, repository_id: str) -> Path:
    return deps.mirrors / (repository_id.replace("/", "_") + ".git")


@dataclass(frozen=True, slots=True)
class PreparedSource:
    mirror: Path
    head_sha: str
    provider: str
    remote_url: str | None


def prepare_source(
    deps: PipelineDeps, source: str, repository_id: str, ref: str = "HEAD"
) -> PreparedSource:
    """Mirror `source` and resolve `ref` against the mirror.

    `source` may be a local repository path or any URL git can clone. For a
    remote, the ref is fetched explicitly first: a mirror clone brings branch
    tips, but a pull request head can live outside them.
    """
    remote = is_remote(source)
    mirror = mirror_path(deps, repository_id)
    deps.git.ensure_mirror(source, mirror)

    try:
        head_sha = deps.git.resolve_sha(mirror, ref)
    except Exception:
        if not remote:
            raise
        # A pull request head is often not on a mirrored branch. Fetch the ref
        # explicitly, then resolve again.
        deps.git.run(["fetch", "origin", ref], cwd=mirror, check=False)
        deps.git.run(
            ["fetch", "origin", "+refs/pull/*/head:refs/pull/*/head"], cwd=mirror, check=False
        )
        head_sha = deps.git.resolve_sha(mirror, ref)

    return PreparedSource(
        mirror=mirror,
        head_sha=head_sha,
        provider="github" if remote else "local",
        remote_url=source if remote else None,
    )
