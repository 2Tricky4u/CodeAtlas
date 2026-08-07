"""Unit tests for the Cytoscape elements projection."""

from __future__ import annotations

from codeatlas.artifacts.cytoscape import to_cytoscape
from codeatlas.core.canonical import canonical_sha256
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
LS = Evidence(kind="language-server", producer="rust-analyzer", confidence=0.9)


def _graph() -> ProjectGraph:
    return ProjectGraph(
        repository=RepositoryRef(id="local/x"),
        revision=RevisionRef(head="e" * 40),
        nodes=[
            GraphNode(
                id="file:src/lib.rs",
                kind="file",
                label="src/lib.rs",
                language="rust",
                location=SourceLocation(path="src/lib.rs"),
                evidence=[LS],
            ),
            GraphNode(id="pkg:cargo/x@1", kind="package", label="x 1", evidence=[DET]),
        ],
        edges=[
            GraphEdge(
                id="edge:1",
                source="pkg:cargo/x@1",
                target="file:src/lib.rs",
                kind="contains",
                evidence=[DET, LS],
            )
        ],
    )


def test_the_visibility_metric_is_projected() -> None:
    """The dashboard's pub badge reads `data.public`; nodes measured private say
    False, and nodes from graphs that never measured visibility say nothing."""
    g = ProjectGraph(
        repository=RepositoryRef(id="local/x"),
        revision=RevisionRef(head="e" * 40),
        nodes=[
            GraphNode(
                id="sym:scip/a",
                kind="function",
                label="a",
                metrics={"public": True},
                evidence=[LS],
            ),
            GraphNode(
                id="sym:scip/b",
                kind="function",
                label="b",
                metrics={"public": False},
                evidence=[LS],
            ),
            GraphNode(id="sym:scip/c", kind="function", label="c", evidence=[LS]),
        ],
        edges=[],
    )
    data = {n["data"]["id"]: n["data"] for n in to_cytoscape(g)["elements"]["nodes"]}
    assert data["sym:scip/a"]["public"] is True
    assert data["sym:scip/b"]["public"] is False
    assert "public" not in data["sym:scip/c"]


def test_counts_and_core_fields() -> None:
    payload = to_cytoscape(_graph())
    assert payload["revision"] == "e" * 40
    assert len(payload["elements"]["nodes"]) == 2
    assert len(payload["elements"]["edges"]) == 1
    node = next(
        n["data"] for n in payload["elements"]["nodes"] if n["data"]["id"] == "file:src/lib.rs"
    )
    assert node["path"] == "src/lib.rs"
    assert node["producers"] == ["rust-analyzer"]
    edge = payload["elements"]["edges"][0]["data"]
    assert edge["source"] == "pkg:cargo/x@1"
    assert edge["producers"] == ["cargo", "rust-analyzer"]


def test_projection_is_deterministic() -> None:
    assert canonical_sha256(to_cytoscape(_graph())) == canonical_sha256(to_cytoscape(_graph()))
