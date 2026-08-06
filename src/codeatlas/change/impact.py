"""Bounded change impact: who else could this change affect.

Reverse reachability from the symbols a change modified or removed, over the
relationships that actually constitute a dependency.

**Why it is bounded.** Static change-impact analysis reports possibilities, and
published surveys put its precision at roughly 38-50%. A transitive closure over
a real codebase therefore reaches nearly everything while being right about
nearly none of it, and the first reader who checks one entry and finds it
irrelevant stops reading the rest. One hop by default, two at the very most, with
whatever does not fit counted rather than quietly dropped.

**Why `contains` is not followed.** A file contains a symbol; that is structure,
not dependence. Following it backwards would pull in the enclosing file, then
everything importing that file, and the bound would stop meaning anything. Only
`calls` and `imports` are traversed.

**Two graphs, not one.** A symbol the change *edited* still exists at head, so its
callers are found in the head graph. A symbol the change *deleted* has no head
edges at all — its callers only exist in the base graph, and a caller that also
disappeared is not reported, because there is nobody left to affect.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from codeatlas.change.graph import stable_key
from codeatlas.graph.symbols import namespace_nodes
from codeatlas.models.api import ApiSurface
from codeatlas.models.diff import GraphDiff
from codeatlas.models.graph import ProjectGraph
from codeatlas.models.impact import (
    RANK_ORDER,
    ChangeImpact,
    ImpactedSymbol,
    ImpactRank,
    ImpactSeed,
)

# Relationships that make one symbol depend on another.
DEPENDENCY_EDGE_KINDS = frozenset({"calls", "imports"})

MAX_HOPS = 2
DEFAULT_HOPS = 1
DEFAULT_MAX_REPORTED = 50

BASIS = (
    "bounded reverse reachability over calls and imports, from the symbols this "
    "change modified or removed"
)
CAVEAT = (
    "Static change-impact analysis reports possibilities, not certainties: a "
    "symbol listed here depends on something the change altered, which is not the "
    "same as being broken by it. Published precision for this class of analysis "
    "is roughly 38-50%."
)

_TEST_PATH = re.compile(r"(^|/)(tests?|benches)/|_tests?\.[a-z]+$|\.test\.[a-z]+$")
_SCIP_KEY = re.compile(r"^sym:scip/\S+ \S+ (?P<package>\S+) (?P<descriptor>.+)$")
# `pub fn kvstore::cache::Cache::put(&mut self, usize)` -> the dotted path only.
_API_ITEM = re.compile(r"^pub (?:\w+ )*?(?P<path>[A-Za-z_][A-Za-z0-9_]*(?:::[A-Za-z0-9_]+)+)")


@dataclass(frozen=True, slots=True)
class _Reached:
    key: str
    hop: int
    seed: str
    edge_kind: str
    removed_seed: bool


def analyze_impact(
    diff: GraphDiff,
    head: ProjectGraph,
    base: ProjectGraph,
    api_surface: ApiSurface | None = None,
    hops: int = DEFAULT_HOPS,
    max_reported: int = DEFAULT_MAX_REPORTED,
) -> ChangeImpact:
    """Bounded impact of `diff`, ranked, with the surplus counted."""
    if hops < 1:
        raise ValueError("impact analysis needs at least one hop")

    notes: list[str] = []
    effective_hops = min(hops, MAX_HOPS)
    if effective_hops != hops:
        notes.append(
            f"hop budget clamped from {hops} to {MAX_HOPS}: beyond two hops the result "
            "reaches most of the codebase and stops distinguishing anything"
        )

    head_nodes = {stable_key(n.id): n for n in head.nodes}
    base_nodes = {stable_key(n.id): n for n in base.nodes}
    head_callers = _reverse_index(head)
    base_callers = _reverse_index(base)

    seeds = [
        ImpactSeed(stable_key=n.stable_key, label=n.label, path=n.path, reason="touched")
        for n in diff.nodes.touched
    ] + [
        ImpactSeed(stable_key=n.stable_key, label=n.label, path=n.path, reason="removed")
        for n in diff.nodes.removed
    ]
    seeds.sort(key=lambda s: (s.reason, s.stable_key))
    if not seeds:
        notes.append(
            "no changed symbols were identified, so no impact was computed; this is "
            "not a finding that the change affects nothing"
        )

    seed_keys = {s.stable_key for s in seeds}
    reached: dict[str, _Reached] = {}
    for seed in seeds:
        callers = base_callers if seed.reason == "removed" else head_callers
        _walk(
            seed=seed.stable_key,
            callers=callers,
            hops=effective_hops,
            removed_seed=seed.reason == "removed",
            seed_keys=seed_keys,
            out=reached,
        )

    exported = _exported_paths(api_surface)
    if api_surface is None:
        notes.append("no public API surface was supplied, so no symbol is ranked as public-api")

    impacted: list[ImpactedSymbol] = []
    for key, hit in reached.items():
        # A caller that the change also deleted has nobody left to affect.
        node = head_nodes.get(key)
        if node is None:
            continue
        seed_node = head_nodes.get(hit.seed) or base_nodes.get(hit.seed)
        impacted.append(
            ImpactedSymbol(
                stable_key=key,
                label=node.label,
                kind=node.kind,
                path=node.location.path if node.location else None,
                start_line=node.location.start_line if node.location else None,
                end_line=node.location.end_line if node.location else None,
                hop=hit.hop,
                rank=_rank(key, node.location.path if node.location else None, seed_node, exported),
                claim_strength=(
                    "referred-to-removed-symbol" if hit.removed_seed else "could-be-affected"
                ),
                via_seed=hit.seed,
                via_edge_kind=hit.edge_kind,
            )
        )

    impacted.sort(key=lambda i: (RANK_ORDER[i.rank], i.hop, i.stable_key))
    total = len(impacted)
    shown = impacted[:max_reported]

    return ChangeImpact(
        base_revision=diff.base_revision,
        head_revision=diff.head_revision,
        hops=effective_hops,
        max_hops=MAX_HOPS,
        seeds=seeds,
        impacted=shown,
        total_impacted=total,
        suppressed=total - len(shown),
        basis=BASIS,
        caveat=CAVEAT,
        notes=notes,
    )


def _reverse_index(graph: ProjectGraph) -> dict[str, list[tuple[str, str]]]:
    """target -> [(source, edge kind)] over dependency edges only."""
    index: dict[str, list[tuple[str, str]]] = defaultdict(list)
    namespaces = namespace_nodes(graph)
    for edge in graph.edges:
        if edge.kind not in DEPENDENCY_EDGE_KINDS:
            continue
        # Resolving any path mentions every module along it. Left in, a change
        # near a module anchor would report most of the crate as impacted, which
        # is the unbounded answer this module exists to avoid.
        if edge.target in namespaces or edge.source in namespaces:
            continue
        index[stable_key(edge.target)].append((stable_key(edge.source), edge.kind))
    return index


def _walk(
    seed: str,
    callers: dict[str, list[tuple[str, str]]],
    hops: int,
    removed_seed: bool,
    seed_keys: set[str],
    out: dict[str, _Reached],
) -> None:
    """Breadth-first, so the recorded hop is always the shortest path to a seed."""
    frontier = [seed]
    visited = {seed}
    for hop in range(1, hops + 1):
        next_frontier: list[str] = []
        for target in frontier:
            for source, kind in sorted(callers.get(target, [])):
                if source in visited:
                    continue
                visited.add(source)
                next_frontier.append(source)
                if source in seed_keys:
                    continue  # a changed symbol is not "impacted" by the change
                existing = out.get(source)
                if existing is None or hop < existing.hop:
                    out[source] = _Reached(
                        key=source,
                        hop=hop,
                        seed=seed,
                        edge_kind=kind,
                        removed_seed=removed_seed,
                    )
        frontier = next_frontier
        if not frontier:
            return


def _exported_paths(surface: ApiSurface | None) -> set[str]:
    """`kvstore::cache::Cache::put` -> `kvstore/cache/Cache/put`, for matching."""
    if surface is None:
        return set()
    paths: set[str] = set()
    for package in surface.packages:
        for item in package.items:
            match = _API_ITEM.match(item)
            if match:
                paths.add(match.group("path").replace("::", "/"))
    return paths


def _symbol_path(key: str) -> str | None:
    """`sym:scip/... kvstore cache/Cache#put().` -> `kvstore/cache/Cache/put`."""
    match = _SCIP_KEY.match(key)
    if not match:
        return None
    descriptor = match.group("descriptor").rstrip(".")
    for suffix in ("()", "#", "/"):
        descriptor = descriptor.replace(suffix, "/")
    parts = [p for p in descriptor.split("/") if p]
    return "/".join([match.group("package"), *parts]) if parts else None


def _package_of(key: str) -> str | None:
    match = _SCIP_KEY.match(key)
    return match.group("package") if match else None


def _rank(
    key: str,
    path: str | None,
    seed_node: object,
    exported: set[str],
) -> ImpactRank:
    symbol_path = _symbol_path(key)
    if symbol_path and symbol_path in exported:
        return "public-api"
    if path and _TEST_PATH.search(path):
        return "test-only"
    seed_id = getattr(seed_node, "id", None)
    seed_package = _package_of(stable_key(seed_id)) if isinstance(seed_id, str) else None
    package = _package_of(key)
    if package and seed_package and package != seed_package:
        return "crate-crossing"
    return "internal"
