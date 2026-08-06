"""Structural difference between two project graphs (P2b). Pure — no toolchain.

This is the signal a text diff cannot give: *storage now imports api*, *nothing
calls `evict_oldest` any more*. Node and edge ids are deterministic functions of
content (ADR-0007), so comparing two revisions is a set operation.

Except that the ids embed a coordinate that has nothing to do with structure.
A real symbol id is:

    sym:scip/rust-analyzer cargo kvstore 0.1.0 cache/Cache#evict_oldest().

The package version sits in the middle of it, and edge ids are hashes of their
endpoints. Bumping 0.1.0 to 0.2.0 therefore changes every symbol id and every
edge id in the crate, and a plain set difference would announce that the entire
project was deleted and rewritten — on a release pull request that changed one
line of Cargo.toml. Most of this file is about that.
"""

from __future__ import annotations

from codeatlas.change.graph import diff_graphs, stable_key
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

BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40

LSP = Evidence(kind="language-server", producer="rust-analyzer", confidence=1.0)
CARGO = Evidence(kind="build-system", producer="cargo", confidence=1.0)


def sym(name: str, version: str = "0.1.0", package: str = "kvstore") -> str:
    return f"sym:scip/rust-analyzer cargo {package} {version} {name}"


def node(
    node_ref: str,
    kind: str = "function",
    label: str = "f",
    path: str = "kvstore/src/cache.rs",
    start: int = 10,
    end: int = 20,
) -> GraphNode:
    return GraphNode(
        id=node_ref,
        kind=kind,  # type: ignore[arg-type]
        label=label,
        location=SourceLocation(path=path, start_line=start, end_line=end),
        evidence=[LSP],
    )


def edge(source: str, kind: str, target: str) -> GraphEdge:
    return GraphEdge(
        id=edge_id(source, kind, target, None),
        source=source,
        target=target,
        kind=kind,  # type: ignore[arg-type]
        evidence=[LSP],
    )


def graph(sha: str, nodes: list[GraphNode], edges: list[GraphEdge]) -> ProjectGraph:
    return ProjectGraph(
        repository=RepositoryRef(id="local/kvstore"),
        revision=RevisionRef(head=sha),
        nodes=sorted(nodes, key=lambda n: n.id),
        edges=sorted(edges, key=lambda e: e.id),
    )


# --- the version trap -------------------------------------------------------


class TestVersionBumpsAreNotStructuralChanges:
    def test_a_symbol_keeps_its_identity_across_a_version_bump(self) -> None:
        assert stable_key(sym("evict().", version="0.1.0")) == stable_key(
            sym("evict().", version="0.2.0")
        )

    def test_two_different_symbols_keep_different_identities(self) -> None:
        assert stable_key(sym("evict().")) != stable_key(sym("put()."))

    def test_the_same_name_in_two_packages_stays_distinct(self) -> None:
        assert stable_key(sym("new().", package="kvstore")) != stable_key(
            sym("new().", package="kvstore-cli")
        )

    def test_a_package_keeps_its_identity_across_a_version_bump(self) -> None:
        assert stable_key("pkg:cargo/kvstore@0.1.0") == stable_key("pkg:cargo/kvstore@0.2.0")

    def test_a_file_identity_is_its_path(self) -> None:
        assert stable_key("file:src/lib.rs") == "file:src/lib.rs"

    def test_a_release_bump_reports_no_structural_change_at_all(self) -> None:
        """The whole point: one line of Cargo.toml must not look like a rewrite."""
        before = graph(
            BASE_SHA,
            [
                node(
                    "pkg:cargo/kvstore@0.1.0",
                    kind="package",
                    label="kvstore 0.1.0",
                    path="Cargo.toml",
                ),
                node(sym("put().", "0.1.0"), label="put"),
                node(sym("get().", "0.1.0"), label="get"),
            ],
            [edge(sym("put().", "0.1.0"), "calls", sym("get().", "0.1.0"))],
        )
        after = graph(
            HEAD_SHA,
            [
                node(
                    "pkg:cargo/kvstore@0.2.0",
                    kind="package",
                    label="kvstore 0.2.0",
                    path="Cargo.toml",
                ),
                node(sym("put().", "0.2.0"), label="put"),
                node(sym("get().", "0.2.0"), label="get"),
            ],
            [edge(sym("put().", "0.2.0"), "calls", sym("get().", "0.2.0"))],
        )

        result = diff_graphs(before, after)
        assert result.nodes.added == []
        assert result.nodes.removed == []
        assert result.edges.added == []
        assert result.edges.removed == []

    def test_but_the_version_change_itself_is_still_reported(self) -> None:
        """Suppressing the churn must not suppress the fact that caused it."""
        before = graph(
            BASE_SHA,
            [
                node(
                    "pkg:cargo/kvstore@0.1.0",
                    kind="package",
                    label="kvstore 0.1.0",
                    path="Cargo.toml",
                )
            ],
            [],
        )
        after = graph(
            HEAD_SHA,
            [
                node(
                    "pkg:cargo/kvstore@0.2.0",
                    kind="package",
                    label="kvstore 0.2.0",
                    path="Cargo.toml",
                )
            ],
            [],
        )
        result = diff_graphs(before, after)
        assert [(c.name, c.before, c.after) for c in result.package_version_changes] == [
            ("kvstore", "0.1.0", "0.2.0")
        ]

    def test_an_unparseable_identity_is_counted_rather_than_guessed_at(self) -> None:
        """A symbol not in the expected grammar keeps its raw id, and says so."""
        odd = "sym:scip/local 0"
        assert stable_key(odd) == odd
        before = graph(BASE_SHA, [node(odd, label="anon")], [])
        result = diff_graphs(before, graph(HEAD_SHA, [node(odd, label="anon")], []))
        assert result.unnormalized_identities == 1


# --- what the diff is for ---------------------------------------------------


class TestStructuralFacts:
    def test_a_removed_symbol_and_the_edges_into_it_are_both_reported(self) -> None:
        """ "Nothing calls evict_oldest any more" is the sentence this enables."""
        caller, victim = sym("handle()."), sym("evict_oldest().")
        before = graph(
            BASE_SHA,
            [node(caller, label="handle"), node(victim, label="evict_oldest")],
            [edge(caller, "calls", victim)],
        )
        after = graph(HEAD_SHA, [node(caller, label="handle")], [])

        result = diff_graphs(before, after)
        assert [n.label for n in result.nodes.removed] == ["evict_oldest"]
        assert result.nodes.added == []
        assert len(result.edges.removed) == 1
        gone = result.edges.removed[0]
        assert gone.kind == "calls"
        assert gone.source_label == "handle"
        assert gone.target_label == "evict_oldest"

    def test_a_new_dependency_between_modules_is_reported(self) -> None:
        """ "storage now imports api" — invisible in a text diff of either file."""
        storage, api = sym("storage/"), sym("api/")
        nodes = [
            node(storage, kind="module", label="storage", path="kvstore/src/storage.rs"),
            node(api, kind="module", label="api", path="kvstore/src/api.rs"),
        ]
        before = graph(BASE_SHA, nodes, [])
        after = graph(HEAD_SHA, nodes, [edge(storage, "imports", api)])

        result = diff_graphs(before, after)
        assert len(result.edges.added) == 1
        assert result.edges.added[0].source_label == "storage"
        assert result.edges.added[0].target_label == "api"
        assert result.edges.removed == []

    def test_a_symbol_that_changed_file_is_reported_as_moved_not_rewritten(self) -> None:
        moved = sym("Cache#")
        before = graph(
            BASE_SHA, [node(moved, kind="type", label="Cache", path="kvstore/src/cache.rs")], []
        )
        after = graph(
            HEAD_SHA, [node(moved, kind="type", label="Cache", path="kvstore/src/eviction.rs")], []
        )

        result = diff_graphs(before, after)
        assert result.nodes.added == []
        assert result.nodes.removed == []
        assert len(result.nodes.moved) == 1
        assert result.nodes.moved[0].before_path == "kvstore/src/cache.rs"
        assert result.nodes.moved[0].after_path == "kvstore/src/eviction.rs"

    def test_line_shifts_alone_are_not_reported_as_change(self) -> None:
        """Editing above a symbol moves it. That is not news about the symbol."""
        shifted = sym("get().")
        before = graph(BASE_SHA, [node(shifted, label="get", start=10, end=20)], [])
        after = graph(HEAD_SHA, [node(shifted, label="get", start=31, end=41)], [])

        result = diff_graphs(before, after)
        assert result.nodes.moved == []
        assert result.nodes.added == []
        assert result.nodes.removed == []


class TestTouchedSymbols:
    """Joining the graph with the change's added lines: what did this PR edit?"""

    def test_a_symbol_overlapping_an_added_line_is_touched(self) -> None:
        target = sym("put().")
        nodes = [node(target, label="put", path="kvstore/src/api.rs", start=10, end=20)]
        result = diff_graphs(
            graph(BASE_SHA, nodes, []),
            graph(HEAD_SHA, nodes, []),
            added_lines={"kvstore/src/api.rs": {14}},
        )
        assert [n.label for n in result.nodes.touched] == ["put"]

    def test_a_symbol_elsewhere_in_the_same_file_is_not_touched(self) -> None:
        target = sym("put().")
        nodes = [node(target, label="put", path="kvstore/src/api.rs", start=10, end=20)]
        result = diff_graphs(
            graph(BASE_SHA, nodes, []),
            graph(HEAD_SHA, nodes, []),
            added_lines={"kvstore/src/api.rs": {80}},
        )
        assert result.nodes.touched == []

    def test_without_a_diff_nothing_is_claimed_to_be_touched(self) -> None:
        target = sym("put().")
        nodes = [node(target, label="put")]
        result = diff_graphs(graph(BASE_SHA, nodes, []), graph(HEAD_SHA, nodes, []))
        assert result.nodes.touched == []


# --- inference stays labelled as inference ----------------------------------


class TestRenamesAreInferredNeverAsserted:
    def test_a_likely_rename_is_offered_with_its_basis(self) -> None:
        before = graph(
            BASE_SHA, [node(sym("evict_oldest()."), label="evict_oldest", start=41, end=48)], []
        )
        after = graph(HEAD_SHA, [node(sym("evict()."), label="evict", start=41, end=50)], [])

        result = diff_graphs(before, after)
        assert len(result.likely_renamed) == 1
        guess = result.likely_renamed[0]
        assert guess.before_label == "evict_oldest"
        assert guess.after_label == "evict"
        assert guess.basis, "an inference without its reason cannot be checked"
        assert 0.0 < guess.confidence <= 1.0

    def test_the_underlying_facts_are_not_rewritten_by_the_guess(self) -> None:
        """The removal and the addition both happened. A guess does not undo them."""
        before = graph(
            BASE_SHA, [node(sym("evict_oldest()."), label="evict_oldest", start=41, end=48)], []
        )
        after = graph(HEAD_SHA, [node(sym("evict()."), label="evict", start=41, end=50)], [])

        result = diff_graphs(before, after)
        assert [n.label for n in result.nodes.removed] == ["evict_oldest"]
        assert [n.label for n in result.nodes.added] == ["evict"]

    def test_unrelated_names_in_different_files_are_not_paired(self) -> None:
        before = graph(
            BASE_SHA,
            [node(sym("parse_header()."), label="parse_header", path="kvstore/src/wire.rs")],
            [],
        )
        after = graph(
            HEAD_SHA,
            [node(sym("Cache#"), kind="type", label="Cache", path="kvstore/src/cache.rs")],
            [],
        )
        assert diff_graphs(before, after).likely_renamed == []

    def test_each_side_of_a_rename_is_used_at_most_once(self) -> None:
        before = graph(
            BASE_SHA,
            [
                node(sym("evict_oldest()."), label="evict_oldest", start=41, end=48),
                node(sym("evict_newest()."), label="evict_newest", start=60, end=68),
            ],
            [],
        )
        after = graph(HEAD_SHA, [node(sym("evict()."), label="evict", start=41, end=50)], [])

        result = diff_graphs(before, after)
        assert len(result.likely_renamed) == 1
        assert result.likely_renamed[0].before_label == "evict_oldest", "the overlapping span wins"


class TestDeterminism:
    def test_the_same_pair_of_graphs_hashes_identically(self) -> None:
        from codeatlas.core.canonical import canonical_sha256

        before = graph(BASE_SHA, [node(sym("a().", label := "a"), label=label)], [])
        after = graph(HEAD_SHA, [node(sym("b()."), label="b")], [])
        first = canonical_sha256(diff_graphs(before, after).contract_dump())
        second = canonical_sha256(diff_graphs(before, after).contract_dump())
        assert first == second

    def test_the_summary_counts_match_the_lists(self) -> None:
        before = graph(BASE_SHA, [node(sym("a()."), label="a")], [])
        after = graph(HEAD_SHA, [node(sym("a()."), label="a"), node(sym("b()."), label="b")], [])
        result = diff_graphs(before, after)
        assert result.summary.nodes_added == len(result.nodes.added)
        assert result.summary.nodes_removed == len(result.nodes.removed)
        assert result.summary.edges_added == len(result.edges.added)
        assert result.summary.edges_removed == len(result.edges.removed)
