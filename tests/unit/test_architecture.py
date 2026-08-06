"""The C4 container model, derived rather than drawn (G3).

`map_graph_to_c4` has existed since M13 and turns every package node into a
container. On the fixture crate that is two boxes and looks fine; on ripgrep it
is sixty, forty-nine of them crates from crates.io that nobody in this
repository can change. A diagram of your dependencies' dependencies is not an
architecture diagram of your system.

So this narrows it the way the map already narrows its package view — to the
packages the overview measured modules for, which is exactly the set that lives
in this repository — and levelizes them with the same function, so the client
lays the boxes out from data instead of from a layout algorithm nobody pinned.
"""

from __future__ import annotations

from codeatlas.models.graph import (
    Evidence,
    GraphEdge,
    GraphNode,
    ProjectGraph,
    RepositoryRef,
    RevisionRef,
    SourceLocation,
)
from codeatlas.models.overview import ModuleSummary, OverviewCounts, PackageSummary, ProjectOverview
from codeatlas.project.architecture import build_architecture

REVISION = "b" * 40
BUILD = [Evidence(kind="build-system", producer="cargo", producer_version="1.94.1")]


def package(name: str) -> GraphNode:
    return GraphNode(
        id=f"pkg:cargo/{name}@0.1.0",
        kind="package",
        label=f"{name} 0.1.0",
        language="rust",
        location=SourceLocation(path=f"{name}/Cargo.toml"),
        evidence=BUILD,
    )


def depends(source: str, target: str) -> GraphEdge:
    return GraphEdge(
        id=f"edge:{source}->{target}",
        kind="depends-on",
        source=f"pkg:cargo/{source}@0.1.0",
        target=f"pkg:cargo/{target}@0.1.0",
        evidence=BUILD,
    )


def module(path: str, pkg: str) -> ModuleSummary:
    return ModuleSummary(
        key=path, path=path, package=pkg, fan_in=0, fan_out=0, level=0, symbol_count=1
    )


def graph(*names: str, edges: list[GraphEdge] | None = None) -> ProjectGraph:
    return ProjectGraph(
        repository=RepositoryRef(id="local/kv"),
        revision=RevisionRef(head=REVISION),
        nodes=[package(n) for n in names],
        edges=edges or [],
    )


def overview(*packages: str, modules: list[ModuleSummary] | None = None) -> ProjectOverview:
    return ProjectOverview(
        repository_id="local/kv",
        revision=REVISION,
        packages=[
            PackageSummary(name=p, version="0.1.0", file_count=1, symbol_count=1) for p in packages
        ],
        modules=modules or [module(f"{p}/src/lib.rs", p) for p in packages],
        counts=OverviewCounts(packages=len(packages), files=1, symbols=1, edges=0),
    )


class TestOnlyThisRepositorysPackages:
    def test_a_third_party_crate_is_not_a_container(self) -> None:
        """ripgrep depends on 49 crates it does not own; none are its architecture."""
        model = build_architecture(
            graph("kvstore", "serde", "regex"),
            overview("kvstore"),
        )
        assert [c.name for c in model.containers] == ["kvstore"]

    def test_a_relationship_to_a_dropped_container_is_dropped_too(self) -> None:
        model = build_architecture(
            graph("kvstore", "serde", edges=[depends("kvstore", "serde")]),
            overview("kvstore"),
        )
        assert model.relationships == []

    def test_a_relationship_between_two_kept_containers_survives(self) -> None:
        model = build_architecture(
            graph("cli", "kvstore", edges=[depends("cli", "kvstore")]),
            overview("cli", "kvstore"),
        )
        assert [(r.source_key, r.target_key) for r in model.relationships] == [("cli", "kvstore")]


class TestEveryBoxLeadsBackToEvidence:
    def test_a_container_names_the_graph_node_it_came_from(self) -> None:
        model = build_architecture(graph("kvstore"), overview("kvstore"))
        assert model.containers[0].evidence_node_id == "pkg:cargo/kvstore@0.1.0"

    def test_a_container_carries_the_manifest_a_reader_would_open(self) -> None:
        model = build_architecture(graph("kvstore"), overview("kvstore"))
        assert model.containers[0].path == "kvstore/Cargo.toml"

    def test_a_relationship_names_the_graph_edge_it_came_from(self) -> None:
        model = build_architecture(
            graph("cli", "kvstore", edges=[depends("cli", "kvstore")]),
            overview("cli", "kvstore"),
        )
        assert model.relationships[0].evidence_edge_id == "edge:cli->kvstore"


class TestLayoutComesFromData:
    def test_a_dependency_puts_its_target_below_it(self) -> None:
        model = build_architecture(
            graph("cli", "kvstore", edges=[depends("cli", "kvstore")]),
            overview("cli", "kvstore"),
        )
        levels = {c.name: c.level for c in model.containers}
        assert levels["kvstore"] == 0
        assert levels["cli"] == 1

    def test_fan_in_is_reported_so_size_can_encode_it(self) -> None:
        model = build_architecture(
            graph(
                "cli",
                "api",
                "kvstore",
                edges=[depends("cli", "kvstore"), depends("api", "kvstore")],
            ),
            overview("cli", "api", "kvstore"),
        )
        by_name = {c.name: c for c in model.containers}
        assert by_name["kvstore"].fan_in == 2
        assert by_name["kvstore"].fan_out == 0

    def test_the_model_is_a_pure_function_of_the_graph(self) -> None:
        g = graph("cli", "kvstore", edges=[depends("cli", "kvstore")])
        o = overview("cli", "kvstore")
        assert build_architecture(g, o).contract_dump() == build_architecture(g, o).contract_dump()


class TestReadabilityIsStatedNotHidden:
    def test_a_small_model_passes_and_says_so(self) -> None:
        model = build_architecture(graph("kvstore"), overview("kvstore"))
        assert model.readability is not None
        assert model.readability.passed

    def test_a_model_past_the_budget_reports_the_check_it_failed(self) -> None:
        """Unlike a map view this is still emitted — one box per package is the
        smallest honest architecture there is, so the reader is told instead."""
        names = [f"crate{i}" for i in range(30)]
        model = build_architecture(graph(*names), overview(*names))
        assert model.readability is not None
        assert not model.readability.passed
        assert model.readability.first_failure is not None
        assert model.readability.first_failure.name == "node-budget"
        assert any("30" in note for note in model.notes)


class TestNothingToDraw:
    def test_a_project_with_no_measured_packages_says_so(self) -> None:
        model = build_architecture(graph("serde"), overview())
        assert model.containers == []
        assert model.notes
