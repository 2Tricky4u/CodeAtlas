"""Unit tests for post-schema graph constraint validation (graph/validate.py)."""

from __future__ import annotations

from codeatlas.graph.validate import validate_graph
from codeatlas.models.graph import (
    Evidence,
    GraphEdge,
    GraphNode,
    ProjectGraph,
    RepositoryRef,
    RevisionRef,
    SourceLocation,
)

DET = Evidence(kind="build-system", producer="cargo", confidence=1.0)
LLM = Evidence(kind="llm-inference", producer="reviewer", confidence=0.7)
SHA = "c" * 40


def _graph(nodes: list[GraphNode], edges: list[GraphEdge]) -> ProjectGraph:
    return ProjectGraph(
        repository=RepositoryRef(id="local/x"),
        revision=RevisionRef(head=SHA),
        nodes=nodes,
        edges=edges,
    )


def _node(nid: str, kind: str = "package", path: str | None = None) -> GraphNode:
    loc = SourceLocation(path=path) if path else None
    return GraphNode(id=nid, kind=kind, label=nid, location=loc, evidence=[DET])  # type: ignore[arg-type]


def test_valid_graph_has_no_violations() -> None:
    a, b = _node("pkg:cargo/a@1"), _node("pkg:cargo/b@1")
    e = GraphEdge(id="edge:1", source=a.id, target=b.id, kind="depends-on", evidence=[DET])
    assert validate_graph(_graph([a, b], [e])) == []


def test_dangling_edge_endpoint_rejected() -> None:
    a = _node("pkg:cargo/a@1")
    e = GraphEdge(
        id="edge:1", source=a.id, target="pkg:cargo/ghost@1", kind="depends-on", evidence=[DET]
    )
    violations = validate_graph(_graph([a], [e]))
    assert any("ghost" in v and "endpoint" in v for v in violations)


def test_duplicate_node_and_edge_ids_rejected() -> None:
    a1, a2 = _node("pkg:cargo/a@1"), _node("pkg:cargo/a@1")
    e1 = GraphEdge(id="edge:1", source=a1.id, target=a1.id, kind="contains", evidence=[DET])
    e2 = GraphEdge(id="edge:1", source=a1.id, target=a1.id, kind="contains", evidence=[DET])
    violations = validate_graph(_graph([a1, a2], [e1, e2]))
    assert any("duplicate node id" in v for v in violations)
    assert any("duplicate edge id" in v for v in violations)


def test_inverted_line_range_rejected() -> None:
    n = GraphNode(
        id="file:x.rs",
        kind="file",
        label="x.rs",
        location=SourceLocation(path="x.rs", start_line=10, end_line=5),
        evidence=[DET],
    )
    violations = validate_graph(_graph([n], []))
    assert any("startLine" in v for v in violations)


def test_llm_only_edge_rejected() -> None:
    a, b = _node("pkg:cargo/a@1"), _node("pkg:cargo/b@1")
    e = GraphEdge(id="edge:1", source=a.id, target=b.id, kind="calls", evidence=[LLM])
    violations = validate_graph(_graph([a, b], [e]))
    assert any("llm-inference" in v for v in violations)


def test_mixed_evidence_edge_allowed() -> None:
    a, b = _node("pkg:cargo/a@1"), _node("pkg:cargo/b@1")
    e = GraphEdge(id="edge:1", source=a.id, target=b.id, kind="calls", evidence=[DET, LLM])
    assert validate_graph(_graph([a, b], [e])) == []


def test_unknown_path_rejected_when_tree_given() -> None:
    n = _node("file:src/nope.rs", kind="file", path="src/nope.rs")
    violations = validate_graph(_graph([n], []), valid_paths={"src/lib.rs"})
    assert any("nope.rs" in v and "revision" in v for v in violations)


def test_known_path_accepted_when_tree_given() -> None:
    n = _node("file:src/lib.rs", kind="file", path="src/lib.rs")
    assert validate_graph(_graph([n], []), valid_paths={"src/lib.rs"}) == []
