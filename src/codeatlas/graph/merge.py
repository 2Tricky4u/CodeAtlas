"""Merge extractor fragments into one normalized project graph.

Same-id nodes from different extractors merge their evidence (deduplicated);
first fragment's attributes win for non-evidence fields (conflicting attrs from
different extractors stay visible through the merged evidence trail). Adds
cross-fragment containment: a cargo package whose manifest directory prefixes a
file node's path contains that file.
"""

from __future__ import annotations

from codeatlas.core.ids import edge_id
from codeatlas.extractors.base import GraphFragment
from codeatlas.models.graph import (
    Evidence,
    GraphEdge,
    GraphNode,
    ProjectGraph,
    RepositoryRef,
    RevisionRef,
)


def merge_fragments(
    repository_id: str,
    head_sha: str,
    fragments: list[GraphFragment],
    remote_url: str | None = None,
    base_sha: str | None = None,
) -> ProjectGraph:
    nodes: dict[str, GraphNode] = {}
    edges: dict[str, GraphEdge] = {}

    for fragment in fragments:
        for node in sorted(fragment.nodes, key=lambda n: n.id):
            if node.id in nodes:
                nodes[node.id] = _merge_evidence(nodes[node.id], node)
            else:
                nodes[node.id] = node
        for edge in sorted(fragment.edges, key=lambda e: e.id):
            if edge.id in edges:
                edges[edge.id] = _merge_edge_evidence(edges[edge.id], edge)
            else:
                edges[edge.id] = edge

    _add_package_containment(nodes, edges)

    graph = ProjectGraph(
        repository=RepositoryRef(id=repository_id, url=remote_url),
        revision=RevisionRef(head=head_sha, base=base_sha),
        nodes=sorted(nodes.values(), key=lambda n: n.id),
        edges=sorted(edges.values(), key=lambda e: e.id),
    )
    return graph


def _merge_evidence(existing: GraphNode, incoming: GraphNode) -> GraphNode:
    merged = _dedupe_evidence([*existing.evidence, *incoming.evidence])
    return existing.model_copy(update={"evidence": merged})


def _merge_edge_evidence(existing: GraphEdge, incoming: GraphEdge) -> GraphEdge:
    merged = _dedupe_evidence([*existing.evidence, *incoming.evidence])
    return existing.model_copy(update={"evidence": merged})


def _dedupe_evidence(items: list[Evidence]) -> list[Evidence]:
    seen: dict[tuple[str, str, str | None], Evidence] = {}
    for ev in items:
        key = (ev.kind, ev.producer, ev.producer_version)
        if key not in seen:
            seen[key] = ev
    return sorted(seen.values(), key=lambda e: (e.kind, e.producer, e.producer_version or ""))


def _add_package_containment(nodes: dict[str, GraphNode], edges: dict[str, GraphEdge]) -> None:
    """package -contains-> file where the package manifest dir prefixes the file path."""
    packages = [
        (n.location.path.rsplit("/", 1)[0] + "/", n.id)
        for n in nodes.values()
        if n.kind == "package" and n.location is not None and "/" in n.location.path
    ]
    evidence = Evidence(kind="build-system", producer="codeatlas-merge", confidence=1.0)
    for node in nodes.values():
        if node.kind != "file" or node.location is None:
            continue
        # Longest matching package prefix wins (nested workspace members).
        best: tuple[int, str] | None = None
        for prefix, pkg_id in packages:
            if node.location.path.startswith(prefix) and (best is None or len(prefix) > best[0]):
                best = (len(prefix), pkg_id)
        if best is not None:
            eid = edge_id(best[1], "contains", node.id, None)
            if eid not in edges:
                edges[eid] = GraphEdge(
                    id=eid, source=best[1], target=node.id, kind="contains", evidence=[evidence]
                )
