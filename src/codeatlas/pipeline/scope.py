"""Build the changed-scope for a run from the pinned mirror.

`review/scope.py` decides what a scope *means* — introduced, adjacent,
pre-existing, blocking. This module answers where the scope comes from: two
pinned SHAs in the local mirror, never a provider API. The diff a review is
scoped against has to be the diff of the code that was analyzed, and the only
place both are certainly the same is the repository the extraction ran on.
"""

from __future__ import annotations

from codeatlas.pipeline.deps import PipelineDeps
from codeatlas.pipeline.source import mirror_path
from codeatlas.review.scope import ChangedScope, parse_added_lines


def changed_scope_for(
    deps: PipelineDeps, repository_id: str, base_sha: str | None, head_sha: str
) -> ChangedScope | None:
    """The scope for a two-revision run, or None in repository mode.

    None is meaningful: with no base there is no "pre-existing", the whole tree
    is under review, and every finding blocks.
    """
    if not base_sha:
        return None
    mirror = mirror_path(deps, repository_id)
    merge_base = deps.git.merge_base(mirror, base_sha, head_sha)
    changed = deps.git.changed_paths(mirror, merge_base, head_sha)
    diff = deps.git.unified_diff(mirror, merge_base, head_sha)
    return ChangedScope(changed_paths=set(changed), added_lines=parse_added_lines(diff))


def scope_from_state(deps: PipelineDeps, state: dict[str, object]) -> ChangedScope | None:
    """Rebuild the scope from checkpointed pipeline state.

    Line numbers travel through the LangGraph checkpoint as sorted lists (a JSON
    document has no sets), so they are widened back here rather than at every
    use site.
    """
    changed = state.get("changed_paths")
    if not changed:
        return None
    added_raw = state.get("added_lines") or {}
    assert isinstance(changed, list)
    assert isinstance(added_raw, dict)
    return ChangedScope(
        changed_paths=set(changed),
        added_lines={path: set(lines) for path, lines in added_raw.items()},
    )
