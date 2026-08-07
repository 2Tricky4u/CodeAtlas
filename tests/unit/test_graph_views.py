"""Views a person can actually read (P4b). Pure — no toolchain.

ripgrep is 104 modules and 13,081 edges. Rendering that as a node-link diagram
produces a hairball, and a hairball is not a smaller amount of understanding than
no diagram — it is a confident-looking picture that cannot be read, which is
worse. Ghoniem, Fekete and Castagliola put the crossover at roughly 20 nodes;
past it a matrix beats a node-link view on every task except path-finding.

So views here are *scoped and bounded*, and a view that fails its readability
checks is refused rather than emitted. The refusal names which check failed, and
the whole-project answer is a matrix, which scales.

The levelized views draw only the edges the layout cannot carry — cycles. That is
the Structure101/Sonargraph technique: position encodes direction, so a downward
edge is already visible and drawing it is ink for nothing.
"""

from __future__ import annotations

from codeatlas.core.ids import edge_id
from codeatlas.models.graph import (
    Evidence,
    GraphEdge,
    GraphNode,
    ProjectGraph,
    RepositoryRef,
    RevisionRef,
    SourceLocation,
)
from codeatlas.project.overview import build_overview
from codeatlas.project.views import DEFAULT_NODE_BUDGET, build_views

SHA = "a" * 40
LSP = Evidence(kind="language-server", producer="rust-analyzer", confidence=1.0)
CARGO = Evidence(kind="build-system", producer="cargo", confidence=1.0)


def file_node(path: str) -> GraphNode:
    return GraphNode(
        id=f"file:{path}",
        kind="file",
        label=path,
        location=SourceLocation(path=path),
        evidence=[LSP],
    )


def sym_node(name: str, path: str, package: str = "kvstore") -> GraphNode:
    return GraphNode(
        id=f"sym:scip/rust-analyzer cargo {package} 0.1.0 {name}",
        kind="function",
        label=name.rstrip("()."),
        location=SourceLocation(path=path, start_line=1, end_line=5),
        evidence=[LSP],
    )


def package_node(name: str) -> GraphNode:
    return GraphNode(
        id=f"pkg:cargo/{name}@0.1.0",
        kind="package",
        label=f"{name} 0.1.0",
        location=SourceLocation(path=f"{name}/Cargo.toml"),
        evidence=[CARGO],
    )


def edge(source: GraphNode, kind: str, target: GraphNode) -> GraphEdge:
    return GraphEdge(
        id=edge_id(source.id, kind, target.id, None),
        source=source.id,
        target=target.id,
        kind=kind,  # type: ignore[arg-type]
        evidence=[LSP],
    )


def graph(nodes: list[GraphNode], edges: list[GraphEdge]) -> ProjectGraph:
    return ProjectGraph(
        repository=RepositoryRef(id="local/kvstore"),
        revision=RevisionRef(head=SHA),
        nodes=sorted(nodes, key=lambda n: n.id),
        edges=sorted(edges, key=lambda e: e.id),
    )


def views_for(project: ProjectGraph):  # type: ignore[no-untyped-def]
    return build_views(project, build_overview(project, repository_id="local/kvstore"))


# Two packages: app depends on core. Inside core, a and b form a cycle.
APP_FILE = file_node("app/src/main.rs")
CORE_A, CORE_B, CORE_C = (file_node(f"core/src/{n}.rs") for n in ("a", "b", "c"))
APP_FN = sym_node("app/run().", "app/src/main.rs", package="app")
A_FN = sym_node("a/f().", "core/src/a.rs", package="core")
B_FN = sym_node("b/g().", "core/src/b.rs", package="core")
C_FN = sym_node("c/h().", "core/src/c.rs", package="core")

TWO_PACKAGES = graph(
    [
        package_node("app"),
        package_node("core"),
        APP_FILE,
        CORE_A,
        CORE_B,
        CORE_C,
        APP_FN,
        A_FN,
        B_FN,
        C_FN,
    ],
    [
        edge(APP_FILE, "contains", APP_FN),
        edge(CORE_A, "contains", A_FN),
        edge(CORE_B, "contains", B_FN),
        edge(CORE_C, "contains", C_FN),
        edge(APP_FN, "calls", A_FN),  # app -> core
        edge(A_FN, "calls", B_FN),  # cycle
        edge(B_FN, "calls", A_FN),  # cycle
        edge(A_FN, "calls", C_FN),  # downward, carried by the layout
    ],
)


class TestThePackageView:
    def test_it_exists_and_holds_one_node_per_package(self) -> None:
        view = next(v for v in views_for(TWO_PACKAGES).views if v.id == "packages")
        assert sorted(n.label for n in view.nodes) == ["app", "core"]

    def test_package_dependencies_are_aggregated_with_a_weight(self) -> None:
        view = next(v for v in views_for(TWO_PACKAGES).views if v.id == "packages")
        assert len(view.edges) == 1
        assert view.edges[0].source.endswith("app")
        assert view.edges[0].target.endswith("core")
        assert view.edges[0].weight == 1

    def test_it_is_the_view_a_reader_opens_first(self) -> None:
        views = views_for(TWO_PACKAGES)
        assert views.views[0].id == "packages"


class TestLevelizedModuleViews:
    def test_one_view_per_package(self) -> None:
        ids = {v.id for v in views_for(TWO_PACKAGES).views}
        assert "modules:core" in ids
        assert "modules:app" in ids

    def test_nodes_carry_their_level_for_the_layout(self) -> None:
        view = next(v for v in views_for(TWO_PACKAGES).views if v.id == "modules:core")
        levels = {n.label: n.level for n in view.nodes}
        assert levels["core/src/c.rs"] == 0
        assert levels["core/src/a.rs"] == levels["core/src/b.rs"], "a cycle shares a level"

    def test_only_cycle_edges_are_drawn(self) -> None:
        """The layout carries direction; a downward edge drawn is ink for nothing."""
        view = next(v for v in views_for(TWO_PACKAGES).views if v.id == "modules:core")
        drawn = {(e.source, e.target) for e in view.edges}
        assert ("file:core/src/a.rs", "file:core/src/b.rs") in drawn
        assert ("file:core/src/b.rs", "file:core/src/a.rs") in drawn
        assert ("file:core/src/a.rs", "file:core/src/c.rs") not in drawn

    def test_the_edges_the_layout_carries_are_counted_not_hidden(self) -> None:
        view = next(v for v in views_for(TWO_PACKAGES).views if v.id == "modules:core")
        assert view.suppressed_edges == 1, "a -> c is implied by the levels"

    def test_a_clean_package_says_so_rather_than_looking_broken(self) -> None:
        view = next(v for v in views_for(TWO_PACKAGES).views if v.id == "modules:app")
        assert view.edges == []
        assert "no cycles" in " ".join(view.notes).lower()

    def test_nodes_are_nested_under_their_package(self) -> None:
        """Compound parents are what let the UI collapse a package to one box."""
        view = next(v for v in views_for(TWO_PACKAGES).views if v.id == "modules:core")
        assert all(n.parent == "pkg:core" for n in view.nodes)


class TestChurnOnViewNodes:
    def test_a_measured_module_churn_reaches_the_levelized_view(self) -> None:
        """The map's heat channel reads off ViewNode — a metric that stops at
        the overview never draws."""
        overview = build_overview(
            TWO_PACKAGES,
            repository_id="local/kvstore",
            churn={"core/src/a.rs": 7},
        )
        views = build_views(TWO_PACKAGES, overview)
        levelized = next(v for v in views.views if v.id == "modules:core")
        by_path = {n.path: n for n in levelized.nodes if n.path}
        assert by_path["core/src/a.rs"].churn == 7
        assert by_path["core/src/b.rs"].churn == 0

    def test_unmeasured_stays_absent(self) -> None:
        views = views_for(TWO_PACKAGES)
        levelized = next(v for v in views.views if v.kind == "levelized-modules")
        assert all(n.churn is None for n in levelized.nodes)


class TestTheReadabilityGate:
    def _wide(self, count: int) -> ProjectGraph:
        hub = file_node("core/src/hub.rs")
        hub_fn = sym_node("hub/h().", "core/src/hub.rs", package="core")
        nodes: list[GraphNode] = [package_node("core"), hub, hub_fn]
        edges: list[GraphEdge] = [edge(hub, "contains", hub_fn)]
        for index in range(count):
            leaf = file_node(f"core/src/m{index:03d}.rs")
            leaf_fn = sym_node(f"m{index}/f().", f"core/src/m{index:03d}.rs", package="core")
            nodes += [leaf, leaf_fn]
            edges += [edge(leaf, "contains", leaf_fn), edge(hub_fn, "calls", leaf_fn)]
        return graph(nodes, edges)

    def test_a_view_over_budget_is_refused_not_rendered(self) -> None:
        views = build_views(
            self._wide(40), build_overview(self._wide(40), repository_id="local/kvstore")
        )
        assert not any(v.id == "modules:core" for v in views.views)
        refusal = next(r for r in views.refused if r.id == "modules:core")
        assert "41" in refusal.reason or "node" in refusal.reason

    def test_the_refusal_names_the_check_that_failed(self) -> None:
        views = build_views(
            self._wide(40), build_overview(self._wide(40), repository_id="local/kvstore")
        )
        refusal = next(r for r in views.refused if r.id == "modules:core")
        assert refusal.failed_check == "node-budget"
        assert str(DEFAULT_NODE_BUDGET) in refusal.reason

    def test_every_emitted_view_records_the_checks_it_passed(self) -> None:
        for view in views_for(TWO_PACKAGES).views:
            assert view.readability.passed
            assert view.readability.checks, view.id

    def test_a_dense_view_is_refused_even_within_the_node_budget(self) -> None:
        """Twenty nodes wired to everything is unreadable at any size."""
        nodes: list[GraphNode] = [package_node("core")]
        edges: list[GraphEdge] = []
        files = []
        for index in range(12):
            path = f"core/src/n{index:02d}.rs"
            f, fn = file_node(path), sym_node(f"n{index}/f().", path, package="core")
            files.append((f, fn))
            nodes += [f, fn]
            edges.append(edge(f, "contains", fn))
        # Every module calls every other: a complete graph, and a cycle.
        for source_file, source_fn in files:
            for target_file, target_fn in files:
                if source_file.id != target_file.id:
                    edges.append(edge(source_fn, "calls", target_fn))
        dense = graph(nodes, edges)

        views = build_views(dense, build_overview(dense, repository_id="local/kvstore"))
        refusal = next(r for r in views.refused if r.id == "modules:core")
        assert refusal.failed_check in ("edge-density", "max-degree")


class TestTheMatrixFallback:
    def test_the_whole_project_is_offered_as_a_matrix(self) -> None:
        """A matrix scales where a node-link view cannot, so there is always an answer."""
        views = views_for(TWO_PACKAGES)
        matrix = next(v for v in views.views if v.kind == "matrix")
        assert len(matrix.nodes) == 4, "every module, no budget"
        assert matrix.readability.passed

    def test_the_matrix_orders_modules_by_level_so_the_shape_is_visible(self) -> None:
        matrix = next(v for v in views_for(TWO_PACKAGES).views if v.kind == "matrix")
        levels = [n.level for n in matrix.nodes]
        assert levels == sorted(levels)


class TestHonestyAndDeterminism:
    def test_the_same_graph_produces_byte_identical_views(self) -> None:
        from codeatlas.core.canonical import canonical_sha256

        first = canonical_sha256(views_for(TWO_PACKAGES).contract_dump())
        second = canonical_sha256(views_for(TWO_PACKAGES).contract_dump())
        assert first == second

    def test_an_empty_graph_produces_no_views_and_says_why(self) -> None:
        empty = graph([], [])
        views = build_views(empty, build_overview(empty, repository_id="local/kvstore"))
        assert views.views == []
        assert views.notes
