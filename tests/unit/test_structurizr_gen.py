"""Structurizr DSL generation from the project graph (pure text generation).

Every generated element must trace back to a graph node, so the architecture
model is derived evidence rather than an independent drawing.
"""

from __future__ import annotations

from codeatlas.artifacts.structurizr.gen import (
    ArchitectureMapping,
    generate_dsl,
    map_graph_to_c4,
)
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
LS = Evidence(kind="language-server", producer="rust-analyzer", confidence=1.0)
SHA = "a" * 40


def _package(name: str, version: str) -> GraphNode:
    return GraphNode(
        id=f"pkg:cargo/{name}@{version}",
        kind="package",
        label=f"{name} {version}",
        language="rust",
        evidence=[DET],
    )


class TestDuplicateDependencyVersions:
    """fd's real tree carries bitflags 1.x and 2.x at once; two containers
    sharing one display name is a Structurizr validation error. Two versions
    are two real nodes — colliding names keep their version."""

    def _mapping(self) -> ArchitectureMapping:
        graph = ProjectGraph(
            repository=RepositoryRef(id="sharkdp/fd"),
            revision=RevisionRef(head=SHA),
            nodes=[
                _package("bitflags", "1.3.2"),
                _package("bitflags", "2.11.0"),
                _package("fd-find", "10.4.2"),
            ],
            edges=[],
        )
        return map_graph_to_c4(graph, system_name="fd")

    def test_colliding_names_keep_their_version(self) -> None:
        mapping = self._mapping()
        names = sorted(c.name for c in mapping.containers)
        assert names == ["bitflags 1.3.2", "bitflags 2.11.0", "fd-find"]

    def test_keys_are_unique_and_the_dsl_validates_names_once(self) -> None:
        mapping = self._mapping()
        keys = [c.key for c in mapping.containers]
        assert len(keys) == len(set(keys)), keys
        dsl = generate_dsl(mapping, revision_sha=SHA)
        assert dsl.count('container "bitflags 1.3.2"') == 1
        assert dsl.count('container "bitflags 2.11.0"') == 1
        assert 'container "bitflags"' not in dsl


def _graph() -> ProjectGraph:
    return ProjectGraph(
        repository=RepositoryRef(id="local/kvstore"),
        revision=RevisionRef(head=SHA),
        nodes=[
            GraphNode(
                id="pkg:cargo/kvstore@0.1.0",
                kind="package",
                label="kvstore 0.1.0",
                language="rust",
                location=SourceLocation(path="kvstore/Cargo.toml"),
                evidence=[DET],
            ),
            GraphNode(
                id="pkg:cargo/kvstore-cli@0.1.0",
                kind="package",
                label="kvstore-cli 0.1.0",
                language="rust",
                location=SourceLocation(path="kvstore-cli/Cargo.toml"),
                evidence=[DET],
            ),
            GraphNode(
                id="file:kvstore/src/cache.rs",
                kind="file",
                label="kvstore/src/cache.rs",
                location=SourceLocation(path="kvstore/src/cache.rs"),
                evidence=[LS],
            ),
        ],
        edges=[
            GraphEdge(
                id="edge:dep",
                source="pkg:cargo/kvstore-cli@0.1.0",
                target="pkg:cargo/kvstore@0.1.0",
                kind="depends-on",
                configuration="normal",
                evidence=[DET],
            ),
            GraphEdge(
                id="edge:contains",
                source="pkg:cargo/kvstore@0.1.0",
                target="file:kvstore/src/cache.rs",
                kind="contains",
                evidence=[DET],
            ),
        ],
    )


class TestMapping:
    def test_packages_become_containers(self) -> None:
        mapping = map_graph_to_c4(_graph(), system_name="kvstore")
        keys = {c.key for c in mapping.containers}
        assert keys == {"kvstore", "kvstore_cli"}

    def test_dependency_edges_become_relationships(self) -> None:
        mapping = map_graph_to_c4(_graph(), system_name="kvstore")
        assert any(
            r.source_key == "kvstore_cli" and r.target_key == "kvstore"
            for r in mapping.relationships
        )

    def test_containment_edges_do_not_become_relationships(self) -> None:
        """package -contains-> file is structure, not an architectural dependency."""
        mapping = map_graph_to_c4(_graph(), system_name="kvstore")
        assert len(mapping.relationships) == 1

    def test_every_element_records_its_graph_node(self) -> None:
        mapping = map_graph_to_c4(_graph(), system_name="kvstore")
        for container in mapping.containers:
            assert container.evidence_node_id.startswith("pkg:cargo/")

    def test_mapping_is_deterministic(self) -> None:
        first = map_graph_to_c4(_graph(), system_name="kvstore")
        second = map_graph_to_c4(_graph(), system_name="kvstore")
        assert [c.key for c in first.containers] == [c.key for c in second.containers]


class TestDsl:
    def test_dsl_contains_workspace_model_and_views(self) -> None:
        dsl = generate_dsl(map_graph_to_c4(_graph(), system_name="kvstore"), revision_sha=SHA)
        assert dsl.startswith("workspace ")
        assert "model {" in dsl
        assert "views {" in dsl
        assert "systemContext" in dsl
        assert "container " in dsl

    def test_evidence_is_embedded_as_properties(self) -> None:
        dsl = generate_dsl(map_graph_to_c4(_graph(), system_name="kvstore"), revision_sha=SHA)
        assert "atlas.evidence" in dsl
        assert "pkg:cargo/kvstore@0.1.0" in dsl

    def test_revision_is_pinned_in_the_workspace(self) -> None:
        dsl = generate_dsl(map_graph_to_c4(_graph(), system_name="kvstore"), revision_sha=SHA)
        assert SHA in dsl

    def test_no_bom_and_lf_line_endings(self) -> None:
        """Structurizr rejects a BOM outright; CRLF would also churn diffs."""
        dsl = generate_dsl(map_graph_to_c4(_graph(), system_name="kvstore"), revision_sha=SHA)
        assert not dsl.startswith("﻿")
        assert "\r" not in dsl

    def test_quotes_in_names_are_escaped(self) -> None:
        mapping = ArchitectureMapping(
            system_name='weird "quoted" system',
            containers=[],
            relationships=[],
        )
        dsl = generate_dsl(mapping, revision_sha=SHA)
        assert '\\"quoted\\"' in dsl

    def test_generation_is_deterministic(self) -> None:
        mapping = map_graph_to_c4(_graph(), system_name="kvstore")
        assert generate_dsl(mapping, revision_sha=SHA) == generate_dsl(mapping, revision_sha=SHA)
