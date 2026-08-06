"""Understanding a project you have never seen (P4a). Pure — no agent, no toolchain.

This is the deterministic half of project comprehension: entry points, layering,
cycles, hubs, orphans, and a "start here" list — all computed from the graph, so
every element points at an edge or a node rather than at someone's impression of
the codebase.

The layering here is *levelization* (Structure101/Sonargraph): assign each module
to a level such that it depends only downward. That is computed from the actual
dependency edges, not from a list of conventional module names — a naming
convention is a guess about a codebase, and this is supposed to be a measurement
of one.
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

SHA = "a" * 40
LSP = Evidence(kind="language-server", producer="rust-analyzer", confidence=1.0)
CARGO = Evidence(kind="build-system", producer="cargo", confidence=1.0)


def file_node(path: str) -> GraphNode:
    return GraphNode(
        id=f"file:{path}",
        kind="file",
        label=path,
        language="rust",
        location=SourceLocation(path=path),
        evidence=[LSP],
    )


def sym_node(name: str, path: str, kind: str = "function", package: str = "kvstore") -> GraphNode:
    return GraphNode(
        id=f"sym:scip/rust-analyzer cargo {package} 0.1.0 {name}",
        kind=kind,  # type: ignore[arg-type]
        label=name.rstrip("().#/").rsplit("/", 1)[-1],
        location=SourceLocation(path=path, start_line=1, end_line=5),
        evidence=[LSP],
    )


def package_node(name: str, version: str = "0.1.0") -> GraphNode:
    return GraphNode(
        id=f"pkg:cargo/{name}@{version}",
        kind="package",
        label=f"{name} {version}",
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


# api -> cache -> storage, a clean three-level stack.
API, CACHE, STORAGE = (file_node(f"kvstore/src/{n}.rs") for n in ("api", "cache", "storage"))
HANDLE = sym_node("api/handle().", "kvstore/src/api.rs")
GET = sym_node("cache/get().", "kvstore/src/cache.rs")
READ = sym_node("storage/read().", "kvstore/src/storage.rs")
STACK = graph(
    [API, CACHE, STORAGE, HANDLE, GET, READ],
    [
        edge(API, "contains", HANDLE),
        edge(CACHE, "contains", GET),
        edge(STORAGE, "contains", READ),
        edge(HANDLE, "calls", GET),
        edge(GET, "calls", READ),
    ],
)


class TestLevelization:
    def test_a_module_depending_on_nothing_sits_at_the_bottom(self) -> None:
        overview = build_overview(STACK, repository_id="local/kvstore")
        levels = {m.path: m.level for m in overview.modules}
        assert levels["kvstore/src/storage.rs"] == 0

    def test_each_module_sits_above_everything_it_depends_on(self) -> None:
        overview = build_overview(STACK, repository_id="local/kvstore")
        levels = {m.path: m.level for m in overview.modules}
        assert levels["kvstore/src/cache.rs"] == 1
        assert levels["kvstore/src/api.rs"] == 2

    def test_the_levels_are_reported_bottom_up(self) -> None:
        overview = build_overview(STACK, repository_id="local/kvstore")
        assert [level.level for level in overview.levels] == [0, 1, 2]
        assert level_members(overview, 0) == ["kvstore/src/storage.rs"]

    def test_containment_does_not_make_a_module_depend_on_itself(self) -> None:
        """A file contains its symbols; that is not a dependency on anything."""
        overview = build_overview(STACK, repository_id="local/kvstore")
        assert overview.cycles == []


def level_members(overview, level: int) -> list[str]:  # type: ignore[no-untyped-def]
    return next(entry.modules for entry in overview.levels if entry.level == level)


class TestCycles:
    def test_a_two_module_cycle_is_reported_with_both_members(self) -> None:
        a, b = file_node("kvstore/src/a.rs"), file_node("kvstore/src/b.rs")
        fa, fb = sym_node("a/f().", "kvstore/src/a.rs"), sym_node("b/g().", "kvstore/src/b.rs")
        cyclic = graph(
            [a, b, fa, fb],
            [
                edge(a, "contains", fa),
                edge(b, "contains", fb),
                edge(fa, "calls", fb),
                edge(fb, "calls", fa),
            ],
        )
        overview = build_overview(cyclic, repository_id="local/kvstore")
        assert len(overview.cycles) == 1
        assert overview.cycles[0].members == ["kvstore/src/a.rs", "kvstore/src/b.rs"]

    def test_modules_in_a_cycle_share_a_level(self) -> None:
        a, b = file_node("kvstore/src/a.rs"), file_node("kvstore/src/b.rs")
        fa, fb = sym_node("a/f().", "kvstore/src/a.rs"), sym_node("b/g().", "kvstore/src/b.rs")
        cyclic = graph(
            [a, b, fa, fb],
            [
                edge(a, "contains", fa),
                edge(b, "contains", fb),
                edge(fa, "calls", fb),
                edge(fb, "calls", fa),
            ],
        )
        overview = build_overview(cyclic, repository_id="local/kvstore")
        levels = {m.path: m.level for m in overview.modules}
        assert levels["kvstore/src/a.rs"] == levels["kvstore/src/b.rs"]

    def test_an_acyclic_project_reports_no_cycles(self) -> None:
        assert build_overview(STACK, repository_id="local/kvstore").cycles == []


class TestTheCrateRootIsNotADependency:
    """Found by looking at the fixture's overview instead of only its tests.

    Every Rust module that writes `use crate::…` references the crate root
    symbol, whose definition site is `lib.rs`. Counted as a dependency, every
    module depends on `lib.rs` while `lib.rs` depends on everything it
    re-exports — so the entire crate becomes one strongly connected component
    and the levelization says nothing at all.
    """

    def _with_crate_root(self):  # type: ignore[no-untyped-def]
        lib = file_node("kvstore/src/lib.rs")
        crate_root = sym_node("crate/", "kvstore/src/lib.rs", kind="module")
        api_module = sym_node("api/", "kvstore/src/api.rs", kind="module")
        return graph(
            [*STACK.nodes, lib, crate_root, api_module],
            [
                *STACK.edges,
                edge(lib, "contains", crate_root),
                edge(API, "contains", api_module),
                # `use crate::cache::Cache;` inside api.rs
                edge(API, "imports", crate_root),
                # `pub mod api;` in lib.rs — a genuine dependency
                edge(lib, "imports", api_module),
            ],
        )

    def test_an_intermediate_module_reference_creates_no_cycle(self) -> None:
        """Found on memchr, where 25 of 35 modules landed in one cycle.

        Resolving `crate::arch::all::twoway::Finder` mentions every module on
        the way, each defined in some `mod.rs`. Counted as dependencies, every
        file that reaches into a subtree depends on each `mod.rs` above it,
        while each `mod.rs` declares the files beneath it.
        """
        parent = file_node("kvstore/src/arch/mod.rs")
        child = file_node("kvstore/src/arch/avx2.rs")
        arch_module = sym_node("arch/", "kvstore/src/arch/mod.rs", kind="module")
        avx_module = sym_node("arch/avx2/", "kvstore/src/arch/avx2.rs", kind="module")
        finder = sym_node("arch/avx2/Finder#", "kvstore/src/arch/avx2.rs", kind="type")

        nested = graph(
            [parent, child, arch_module, avx_module, finder],
            [
                edge(parent, "contains", arch_module),
                edge(child, "contains", avx_module),
                edge(child, "contains", finder),
                # `pub mod avx2;` in arch/mod.rs
                edge(parent, "imports", avx_module),
                # `use crate::arch::...` from inside avx2.rs mentions its parent
                edge(child, "imports", arch_module),
            ],
        )
        overview = build_overview(nested, repository_id="local/kvstore")
        assert overview.cycles == []

    def test_a_real_dependency_through_a_module_path_still_counts(self) -> None:
        """Excluding namespaces must not also exclude the item they lead to."""
        holder = file_node("kvstore/src/arch/avx2.rs")
        user = file_node("kvstore/src/memmem.rs")
        avx_module = sym_node("arch/avx2/", "kvstore/src/arch/avx2.rs", kind="module")
        finder = sym_node("arch/avx2/Finder#", "kvstore/src/arch/avx2.rs", kind="type")

        real = graph(
            [holder, user, avx_module, finder],
            [
                edge(holder, "contains", avx_module),
                edge(holder, "contains", finder),
                edge(user, "imports", avx_module),  # namespace on the way
                edge(user, "imports", finder),  # the thing actually used
            ],
        )
        overview = build_overview(real, repository_id="local/kvstore")
        by_path = {m.path: m for m in overview.modules}
        assert by_path["kvstore/src/memmem.rs"].fan_out == 1
        assert by_path["kvstore/src/arch/avx2.rs"].fan_in == 1

    def test_referencing_the_crate_root_creates_no_cycle(self) -> None:
        overview = build_overview(self._with_crate_root(), repository_id="local/kvstore")
        assert overview.cycles == []

    def test_the_crate_root_reference_is_not_counted_as_fan_out(self) -> None:
        overview = build_overview(self._with_crate_root(), repository_id="local/kvstore")
        by_path = {m.path: m for m in overview.modules}
        assert by_path["kvstore/src/api.rs"].fan_out == 1, "only the real call into cache"

    def test_a_bare_module_declaration_is_not_a_dependency(self) -> None:
        """`pub mod api;` names a namespace; it does not use anything in it.

        This assertion originally went the other way, under the narrower rule
        that excluded only `crate`/`super`/`self`. Measuring memchr settled it:
        that rule left 25 of 35 modules in a single cycle, and excluding every
        namespace reference leaves a largest cycle of two. A `mod.rs` that only
        declares its children depends on none of them — and a `lib.rs` that also
        re-exports their items still does, through those item references.
        """
        overview = build_overview(self._with_crate_root(), repository_id="local/kvstore")
        by_path = {m.path: m for m in overview.modules}
        assert by_path["kvstore/src/lib.rs"].fan_out == 0
        assert by_path["kvstore/src/api.rs"].fan_in == 0
        assert "kvstore/src/lib.rs" in by_path, "the module is still present, just unlinked"


class TestHubsAndOrphans:
    def test_the_most_depended_on_module_is_named(self) -> None:
        overview = build_overview(STACK, repository_id="local/kvstore")
        assert overview.hubs.depended_on[0].path == "kvstore/src/storage.rs"

    def test_fan_in_and_fan_out_are_counted_per_module(self) -> None:
        overview = build_overview(STACK, repository_id="local/kvstore")
        by_path = {m.path: m for m in overview.modules}
        assert by_path["kvstore/src/cache.rs"].fan_in == 1
        assert by_path["kvstore/src/cache.rs"].fan_out == 1
        assert by_path["kvstore/src/api.rs"].fan_in == 0

    def test_a_module_nothing_reaches_and_which_reaches_nothing_is_an_orphan(self) -> None:
        stray = file_node("kvstore/src/stray.rs")
        overview = build_overview(
            graph([*STACK.nodes, stray], list(STACK.edges)), repository_id="local/kvstore"
        )
        assert [o.path for o in overview.orphans] == ["kvstore/src/stray.rs"]


class TestEntryPoints:
    def test_a_main_function_is_an_entry_point(self) -> None:
        main_file = file_node("kvstore-cli/src/main.rs")
        main_fn = sym_node("main().", "kvstore-cli/src/main.rs", package="kvstore-cli")
        overview = build_overview(
            graph(
                [*STACK.nodes, main_file, main_fn],
                [*STACK.edges, edge(main_file, "contains", main_fn)],
            ),
            repository_id="local/kvstore",
        )
        paths = {e.path: e.reason for e in overview.entry_points}
        assert "kvstore-cli/src/main.rs" in paths
        assert "main" in paths["kvstore-cli/src/main.rs"]

    def test_a_library_root_is_an_entry_point(self) -> None:
        lib = file_node("kvstore/src/lib.rs")
        overview = build_overview(
            graph([*STACK.nodes, lib], list(STACK.edges)), repository_id="local/kvstore"
        )
        assert "kvstore/src/lib.rs" in {e.path for e in overview.entry_points}

    def test_every_entry_point_says_why_it_is_one(self) -> None:
        lib = file_node("kvstore/src/lib.rs")
        overview = build_overview(
            graph([*STACK.nodes, lib], list(STACK.edges)), repository_id="local/kvstore"
        )
        assert all(entry.reason for entry in overview.entry_points)


class TestStartHere:
    def test_the_program_entry_point_comes_first(self) -> None:
        main_file = file_node("kvstore-cli/src/main.rs")
        main_fn = sym_node("main().", "kvstore-cli/src/main.rs", package="kvstore-cli")
        overview = build_overview(
            graph(
                [*STACK.nodes, main_file, main_fn],
                [*STACK.edges, edge(main_file, "contains", main_fn)],
            ),
            repository_id="local/kvstore",
        )
        assert overview.start_here[0].path == "kvstore-cli/src/main.rs"

    def test_a_library_root_with_no_dependents_does_not_lead(self) -> None:
        """Found on ripgrep: four `mod.rs` files and a build script filled the list.

        A workspace has a library root per crate, so seeding "start here" with
        every entry point returns facades and nothing a reader has to go and
        read. Library roots stay in `entryPoints` and compete on fan-in here.
        """
        lib = file_node("kvstore/src/lib.rs")
        overview = build_overview(
            graph([*STACK.nodes, lib], list(STACK.edges)), repository_id="local/kvstore"
        )
        assert "kvstore/src/lib.rs" in {e.path for e in overview.entry_points}
        assert overview.start_here[0].path == "kvstore/src/storage.rs", "the foundation leads"

    def test_a_build_script_is_not_an_entry_point(self) -> None:
        """`build.rs` defines `main` and runs at compile time. It was ranked #1."""
        build = file_node("build.rs")
        build_main = sym_node("main().", "build.rs", package="kvstore")
        overview = build_overview(
            graph(
                [*STACK.nodes, build, build_main],
                [*STACK.edges, edge(build, "contains", build_main)],
            ),
            repository_id="local/kvstore",
        )
        assert "build.rs" not in {e.path for e in overview.entry_points}
        assert "build.rs" not in {e.path for e in overview.start_here}

    def test_an_example_does_not_outrank_the_program(self) -> None:
        """Three of ripgrep's `examples/*.rs` define `main` and took three slots."""
        example = file_node("crates/grep/examples/simplegrep.rs")
        example_main = sym_node("main().", "crates/grep/examples/simplegrep.rs")
        overview = build_overview(
            graph(
                [*STACK.nodes, example, example_main],
                [*STACK.edges, edge(example, "contains", example_main)],
            ),
            repository_id="local/kvstore",
        )
        assert overview.start_here[0].path != "crates/grep/examples/simplegrep.rs"
        listed = {e.path: e.reason for e in overview.entry_points}
        assert "example or test" in listed["crates/grep/examples/simplegrep.rs"]

    def test_the_most_depended_on_module_follows(self) -> None:
        overview = build_overview(STACK, repository_id="local/kvstore")
        assert overview.start_here[0].path == "kvstore/src/storage.rs"

    def test_the_list_is_short_enough_to_read(self) -> None:
        many = [file_node(f"kvstore/src/m{i}.rs") for i in range(40)]
        overview = build_overview(
            graph([*STACK.nodes, *many], list(STACK.edges)), repository_id="local/kvstore"
        )
        assert len(overview.start_here) <= 7

    def test_every_suggestion_carries_its_reason(self) -> None:
        overview = build_overview(STACK, repository_id="local/kvstore")
        assert all(entry.reason for entry in overview.start_here)


class TestRollupAndCounts:
    def test_packages_are_rolled_up_with_their_files(self) -> None:
        overview = build_overview(
            graph([*STACK.nodes, package_node("kvstore")], list(STACK.edges)),
            repository_id="local/kvstore",
        )
        assert [p.name for p in overview.packages] == ["kvstore"]
        assert overview.packages[0].file_count == 3

    def test_the_counts_match_the_graph(self) -> None:
        overview = build_overview(STACK, repository_id="local/kvstore")
        assert overview.counts.files == 3
        assert overview.counts.symbols == 3
        assert overview.counts.edges == len(STACK.edges)


class TestHonestyAndDeterminism:
    def test_an_empty_graph_says_so_rather_than_inventing_structure(self) -> None:
        overview = build_overview(graph([], []), repository_id="local/kvstore")
        assert overview.modules == []
        assert overview.start_here == []
        assert any("no modules" in note.lower() for note in overview.notes)

    def test_the_same_graph_produces_a_byte_identical_overview(self) -> None:
        from codeatlas.core.canonical import canonical_sha256

        first = canonical_sha256(
            build_overview(STACK, repository_id="local/kvstore").contract_dump()
        )
        second = canonical_sha256(
            build_overview(STACK, repository_id="local/kvstore").contract_dump()
        )
        assert first == second

    def test_node_order_does_not_change_the_result(self) -> None:
        from codeatlas.core.canonical import canonical_sha256

        shuffled = ProjectGraph(
            repository=STACK.repository,
            revision=STACK.revision,
            nodes=list(reversed(STACK.nodes)),
            edges=list(reversed(STACK.edges)),
        )
        assert canonical_sha256(
            build_overview(shuffled, repository_id="local/kvstore").contract_dump()
        ) == canonical_sha256(build_overview(STACK, repository_id="local/kvstore").contract_dump())
