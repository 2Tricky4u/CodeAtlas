"""Structural difference between two project graphs.

What a text diff cannot tell you: that `storage` now imports `api`, that nothing
calls `evict_oldest` any more, that `Cache` moved to another file. None of those
appear in the diff of any single file; all of them are set operations over two
graphs whose node and edge ids are deterministic functions of content (ADR-0007).

**Identity is not the id.** A real symbol id is

    sym:scip/rust-analyzer cargo kvstore 0.1.0 cache/Cache#evict_oldest().

with the package version sitting in the middle, and edge ids are hashes of their
endpoints. Comparing raw ids would therefore report a release pull request — one
line of Cargo.toml — as the entire crate being deleted and rewritten. Every
comparison here runs on a `stable_key` with the version coordinate removed, and
the version change is reported as the fact it is instead of as churn.

**Facts and guesses live in different fields.** A removal and an addition are
facts. "That was a rename" is a guess about intent, so it is offered as
`likely_renamed` with its basis and confidence, and it never edits the removal
and addition it is a guess about.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from codeatlas.models.diff import (
    DiffEdge,
    DiffNode,
    DiffSummary,
    EdgeDelta,
    GraphDiff,
    MovedNode,
    NodeDelta,
    RenameGuess,
    VersionChange,
)
from codeatlas.models.graph import GraphEdge, GraphNode, ProjectGraph

# `sym:scip/<scheme> <manager> <package> <version> <descriptors...>` — the SCIP
# symbol grammar rust-analyzer emits. The version is dropped; everything else
# identifies the symbol.
_SCIP = re.compile(
    r"^sym:scip/(?P<scheme>\S+) (?P<manager>\S+) (?P<package>\S+) (?P<version>\S+) (?P<rest>.+)$"
)
_PACKAGE = re.compile(r"^pkg:(?P<namespace>[^/]+)/(?P<name>.+)@(?P<version>[^@]+)$")

# Below this, two names are not plausibly the same thing under a new spelling.
_RENAME_SIMILARITY_FLOOR = 0.6


def stable_key(node_ref: str) -> str:
    """A node id with its version coordinate removed.

    Falls back to the id unchanged when the id is not in a known scheme. That
    direction is deliberate: leaving an id alone can produce spurious churn,
    while inventing a normalization could merge two genuinely distinct symbols
    into one and hide a real change.
    """
    scip = _SCIP.match(node_ref)
    if scip:
        return "sym:scip/{scheme} {manager} {package} {rest}".format(**scip.groupdict())
    package = _PACKAGE.match(node_ref)
    if package:
        return f"pkg:{package.group('namespace')}/{package.group('name')}"
    return node_ref


def is_normalized(node_ref: str) -> bool:
    """Whether this id carries a version coordinate we know how to remove."""
    return bool(_SCIP.match(node_ref) or _PACKAGE.match(node_ref) or node_ref.startswith("file:"))


def _edge_key(edge: GraphEdge) -> tuple[str, str, str, str]:
    return (
        stable_key(edge.source),
        edge.kind,
        stable_key(edge.target),
        edge.configuration or "",
    )


@dataclass(frozen=True, slots=True)
class _Side:
    nodes: dict[str, GraphNode]
    edges: dict[tuple[str, str, str, str], GraphEdge]

    @staticmethod
    def of(graph: ProjectGraph) -> _Side:
        return _Side(
            nodes={stable_key(n.id): n for n in graph.nodes},
            edges={_edge_key(e): e for e in graph.edges},
        )


def diff_graphs(
    base: ProjectGraph,
    head: ProjectGraph,
    added_lines: dict[str, set[int]] | None = None,
) -> GraphDiff:
    """Compare two graphs of the same repository at two revisions.

    `added_lines` is the change's added-line set per path. Supplied, it yields
    `nodes.touched` — the symbols the change actually edited. Omitted, `touched`
    is empty, which means "not computed" rather than "nothing was touched"; the
    schema says so, because the two must not look alike.
    """
    before, after = _Side.of(base), _Side.of(head)

    added_keys = sorted(after.nodes.keys() - before.nodes.keys())
    removed_keys = sorted(before.nodes.keys() - after.nodes.keys())
    common_keys = sorted(before.nodes.keys() & after.nodes.keys())

    added = [_diff_node(key, after.nodes[key]) for key in added_keys]
    removed = [_diff_node(key, before.nodes[key]) for key in removed_keys]

    moved = [
        MovedNode(
            stable_key=key,
            kind=after.nodes[key].kind,
            label=after.nodes[key].label,
            before_path=_path(before.nodes[key]) or "",
            after_path=_path(after.nodes[key]) or "",
        )
        for key in common_keys
        if _path(before.nodes[key])
        and _path(after.nodes[key])
        and _path(before.nodes[key]) != _path(after.nodes[key])
    ]

    return GraphDiff(
        base_revision=base.revision.head,
        head_revision=head.revision.head,
        nodes=NodeDelta(
            added=added,
            removed=removed,
            moved=moved,
            touched=_touched(after, common_keys + added_keys, added_lines),
        ),
        edges=EdgeDelta(
            added=_edges(after, sorted(after.edges.keys() - before.edges.keys())),
            removed=_edges(before, sorted(before.edges.keys() - after.edges.keys())),
        ),
        package_version_changes=_version_changes(before, after, common_keys),
        likely_renamed=_infer_renames(removed, added),
        unnormalized_identities=sum(
            1 for node in {**before.nodes, **after.nodes}.values() if not is_normalized(node.id)
        ),
        summary=DiffSummary(
            nodes_added=len(added),
            nodes_removed=len(removed),
            nodes_moved=len(moved),
            nodes_touched=len(_touched(after, common_keys + added_keys, added_lines)),
            edges_added=len(after.edges.keys() - before.edges.keys()),
            edges_removed=len(before.edges.keys() - after.edges.keys()),
        ),
    )


def _path(node: GraphNode) -> str | None:
    return node.location.path if node.location else None


def _diff_node(key: str, node: GraphNode) -> DiffNode:
    return DiffNode(
        stable_key=key,
        id=node.id,
        kind=node.kind,
        label=node.label,
        path=_path(node),
        start_line=node.location.start_line if node.location else None,
        end_line=node.location.end_line if node.location else None,
    )


def _edges(side: _Side, keys: list[tuple[str, str, str, str]]) -> list[DiffEdge]:
    out: list[DiffEdge] = []
    for key in keys:
        edge = side.edges[key]
        source = side.nodes.get(key[0])
        target = side.nodes.get(key[2])
        out.append(
            DiffEdge(
                id=edge.id,
                kind=edge.kind,
                source_key=key[0],
                target_key=key[2],
                # An endpoint outside the graph still names itself; the key is
                # always more informative than dropping the edge would be.
                source_label=source.label if source else key[0],
                target_label=target.label if target else key[2],
                source_path=_path(source) if source else None,
                target_path=_path(target) if target else None,
            )
        )
    return out


def _touched(
    after: _Side, keys: list[str], added_lines: dict[str, set[int]] | None
) -> list[DiffNode]:
    if not added_lines:
        return []
    out: list[DiffNode] = []
    for key in sorted(keys):
        node = after.nodes[key]
        path = _path(node)
        if path is None or node.location is None:
            continue
        lines = added_lines.get(path)
        if not lines:
            continue
        start = node.location.start_line
        if start is None:
            continue
        end = node.location.end_line or start
        if any(start <= line <= end for line in lines):
            out.append(_diff_node(key, node))
    return out


def _version_changes(before: _Side, after: _Side, common: list[str]) -> list[VersionChange]:
    changes: list[VersionChange] = []
    for key in common:
        old, new = before.nodes[key].id, after.nodes[key].id
        old_match, new_match = _PACKAGE.match(old), _PACKAGE.match(new)
        if not (old_match and new_match):
            continue
        if old_match.group("version") == new_match.group("version"):
            continue
        changes.append(
            VersionChange(
                name=new_match.group("name"),
                before=old_match.group("version"),
                after=new_match.group("version"),
            )
        )
    return sorted(changes, key=lambda c: c.name)


def _infer_renames(removed: list[DiffNode], added: list[DiffNode]) -> list[RenameGuess]:
    """Pair a removal with an addition that plausibly replaced it.

    Two passes, in the spirit of `sem`'s matching: an overlapping source range in
    the same file is much stronger evidence than a similar name, so it is
    consumed first. Each side is used at most once, and a pairing is emitted
    alongside — never instead of — the removal and addition it explains.
    """
    candidates: list[tuple[float, str, DiffNode, DiffNode]] = []
    for old in removed:
        for new in added:
            if old.kind != new.kind or not old.path or old.path != new.path:
                continue
            similarity = SequenceMatcher(None, old.label, new.label).ratio()
            if _overlaps(old, new):
                candidates.append(
                    (
                        max(similarity, 0.75),
                        f"same file and overlapping source range; name similarity {similarity:.2f}",
                        old,
                        new,
                    )
                )
            elif similarity >= _RENAME_SIMILARITY_FLOOR:
                candidates.append(
                    (similarity, f"same file; name similarity {similarity:.2f}", old, new)
                )

    # Strongest first; ties broken by key so the output is a pure function of input.
    candidates.sort(key=lambda c: (-c[0], c[2].stable_key, c[3].stable_key))
    used_old: set[str] = set()
    used_new: set[str] = set()
    guesses: list[RenameGuess] = []
    for confidence, basis, old, new in candidates:
        if old.stable_key in used_old or new.stable_key in used_new:
            continue
        used_old.add(old.stable_key)
        used_new.add(new.stable_key)
        guesses.append(
            RenameGuess(
                before_key=old.stable_key,
                after_key=new.stable_key,
                before_label=old.label,
                after_label=new.label,
                path=old.path,
                confidence=round(min(confidence, 1.0), 3),
                basis=basis,
            )
        )
    return sorted(guesses, key=lambda g: g.before_key)


def _overlaps(old: DiffNode, new: DiffNode) -> bool:
    if old.start_line is None or new.start_line is None:
        return False
    old_end = old.end_line or old.start_line
    new_end = new.end_line or new.start_line
    return old.start_line <= new_end and new.start_line <= old_end
