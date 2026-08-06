"""Who else could this change affect (P2c). Pure — no toolchain.

Static change-impact analysis has a precision of roughly 38-50% in the published
surveys. An unbounded transitive closure over a real codebase therefore reaches
almost everything and is right about almost none of it, which spends the reader's
trust on the first thing they check. So the traversal is bounded by default, the
surplus is counted rather than dropped, and nothing here claims more than "could
be affected" — except where a symbol was deleted outright, where the claim can be
stronger because the caller demonstrably referred to something that is gone.
"""

from __future__ import annotations

import pytest

from codeatlas.change.graph import diff_graphs
from codeatlas.change.impact import analyze_impact
from codeatlas.core.ids import edge_id
from codeatlas.models.api import ApiPackage, ApiSurface
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


def sym(descriptor: str, package: str = "kvstore") -> str:
    return f"sym:scip/rust-analyzer cargo {package} 0.1.0 {descriptor}"


def node(
    ref: str,
    label: str,
    path: str = "kvstore/src/cache.rs",
    kind: str = "function",
    start: int = 10,
    end: int = 20,
) -> GraphNode:
    return GraphNode(
        id=ref,
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


# A -> B -> C -> D, all calling rightwards. The change edits D.
CHAIN_A, CHAIN_B, CHAIN_C, CHAIN_D = (sym(f"{n}().") for n in ("a", "b", "c", "d"))
CHAIN_NODES = [
    node(CHAIN_A, "a", start=10, end=19),
    node(CHAIN_B, "b", start=20, end=29),
    node(CHAIN_C, "c", start=30, end=39),
    node(CHAIN_D, "d", start=40, end=49),
]
CHAIN_EDGES = [
    edge(CHAIN_A, "calls", CHAIN_B),
    edge(CHAIN_B, "calls", CHAIN_C),
    edge(CHAIN_C, "calls", CHAIN_D),
]
TOUCHED_D = {"kvstore/src/cache.rs": {42}}


def chain_impact(**kwargs):  # type: ignore[no-untyped-def]
    before = graph(BASE_SHA, CHAIN_NODES, CHAIN_EDGES)
    after = graph(HEAD_SHA, CHAIN_NODES, CHAIN_EDGES)
    diff = diff_graphs(before, after, added_lines=TOUCHED_D)
    return analyze_impact(diff, head=after, base=before, **kwargs)


class TestTheTraversalIsBounded:
    def test_one_hop_by_default(self) -> None:
        result = chain_impact()
        assert [i.label for i in result.impacted] == ["c"]
        assert result.hops == 1

    def test_two_hops_when_asked(self) -> None:
        result = chain_impact(hops=2)
        assert sorted(i.label for i in result.impacted) == ["b", "c"]

    def test_a_larger_request_is_clamped_and_says_so(self) -> None:
        """No caller gets an unbounded closure by passing a big number."""
        result = chain_impact(hops=99)
        assert result.hops == 2
        assert sorted(i.label for i in result.impacted) == ["b", "c"]
        assert "clamped" in result.notes[0].lower()

    def test_each_impacted_symbol_records_how_far_away_it_is(self) -> None:
        result = chain_impact(hops=2)
        by_label = {i.label: i.hop for i in result.impacted}
        assert by_label == {"c": 1, "b": 2}

    def test_the_seed_itself_is_not_reported_as_impacted(self) -> None:
        assert "d" not in {i.label for i in chain_impact().impacted}


class TestWhatCountsAsADependency:
    def test_containment_is_not_impact(self) -> None:
        """A file contains a symbol; that is structure, not a dependency.

        Following `contains` backwards would pull in the whole file, then
        everything importing the file, and the bound would stop meaning anything.
        """
        target = sym("d().")
        file_node = node("file:kvstore/src/cache.rs", "cache.rs", kind="file")
        nodes = [node(target, "d", start=40, end=49), file_node]
        edges = [edge("file:kvstore/src/cache.rs", "contains", target)]
        before = graph(BASE_SHA, nodes, edges)
        after = graph(HEAD_SHA, nodes, edges)
        diff = diff_graphs(before, after, added_lines=TOUCHED_D)

        result = analyze_impact(diff, head=after, base=before)
        assert result.impacted == []

    def test_an_import_is_impact(self) -> None:
        target = sym("d().")
        importer = "file:kvstore/src/api.rs"
        nodes = [
            node(target, "d", start=40, end=49),
            node(importer, "api.rs", path="kvstore/src/api.rs", kind="file"),
        ]
        edges = [edge(importer, "imports", target)]
        before = graph(BASE_SHA, nodes, edges)
        after = graph(HEAD_SHA, nodes, edges)
        diff = diff_graphs(before, after, added_lines=TOUCHED_D)

        assert [i.label for i in analyze_impact(diff, head=after, base=before).impacted] == [
            "api.rs"
        ]


class TestSurplusIsCountedNotDropped:
    def test_beyond_the_report_limit_the_remainder_is_stated(self) -> None:
        target = sym("d().")
        callers = [node(sym(f"c{i}()."), f"c{i}", start=100 + i, end=100 + i) for i in range(10)]
        nodes = [node(target, "d", start=40, end=49), *callers]
        edges = [edge(c.id, "calls", target) for c in callers]
        before = graph(BASE_SHA, nodes, edges)
        after = graph(HEAD_SHA, nodes, edges)
        diff = diff_graphs(before, after, added_lines=TOUCHED_D)

        result = analyze_impact(diff, head=after, base=before, max_reported=4)
        assert len(result.impacted) == 4
        assert result.suppressed == 6
        assert result.total_impacted == 10, "the count is honest even when the list is not complete"


class TestRanking:
    def test_a_crate_crossing_dependency_outranks_an_internal_one(self) -> None:
        target = sym("d().")
        internal = sym("local_caller().")
        crossing = sym("cli_caller().", package="kvstore-cli")
        nodes = [
            node(target, "d", start=40, end=49),
            node(internal, "local_caller", start=60, end=69),
            node(crossing, "cli_caller", path="kvstore-cli/src/main.rs", start=1, end=9),
        ]
        edges = [edge(internal, "calls", target), edge(crossing, "calls", target)]
        before = graph(BASE_SHA, nodes, edges)
        after = graph(HEAD_SHA, nodes, edges)
        diff = diff_graphs(before, after, added_lines=TOUCHED_D)

        result = analyze_impact(diff, head=after, base=before)
        assert [i.label for i in result.impacted] == ["cli_caller", "local_caller"]
        assert result.impacted[0].rank == "crate-crossing"
        assert result.impacted[1].rank == "internal"

    def test_test_code_ranks_below_production_code(self) -> None:
        target = sym("d().")
        production = sym("prod_caller().")
        test = sym("test_caller().")
        nodes = [
            node(target, "d", start=40, end=49),
            node(production, "prod_caller", start=60, end=69),
            node(test, "test_caller", path="kvstore/tests/cache_test.rs", start=1, end=9),
        ]
        edges = [edge(production, "calls", target), edge(test, "calls", target)]
        before = graph(BASE_SHA, nodes, edges)
        after = graph(HEAD_SHA, nodes, edges)
        diff = diff_graphs(before, after, added_lines=TOUCHED_D)

        result = analyze_impact(diff, head=after, base=before)
        assert [i.rank for i in result.impacted] == ["internal", "test-only"]

    def test_a_publicly_exported_caller_ranks_highest(self) -> None:
        target = sym("d().")
        exported = sym("cache/Cache#put().")
        nodes = [node(target, "d", start=40, end=49), node(exported, "put", start=60, end=69)]
        edges = [edge(exported, "calls", target)]
        before = graph(BASE_SHA, nodes, edges)
        after = graph(HEAD_SHA, nodes, edges)
        diff = diff_graphs(before, after, added_lines=TOUCHED_D)

        surface = ApiSurface(
            revision=HEAD_SHA,
            tool="cargo-public-api 0.52.0",
            packages=[
                ApiPackage(
                    name="kvstore",
                    version="0.1.0",
                    manifest_path="kvstore/Cargo.toml",
                    items=["pub fn kvstore::cache::Cache::put(&mut self, usize)"],
                )
            ],
            skipped=[],
        )
        result = analyze_impact(diff, head=after, base=before, api_surface=surface)
        assert result.impacted[0].rank == "public-api"

    def test_without_an_api_surface_nothing_is_called_public(self) -> None:
        """A rank that was never measured must not be asserted."""
        target = sym("d().")
        exported = sym("cache/Cache#put().")
        nodes = [node(target, "d", start=40, end=49), node(exported, "put", start=60, end=69)]
        edges = [edge(exported, "calls", target)]
        before = graph(BASE_SHA, nodes, edges)
        after = graph(HEAD_SHA, nodes, edges)
        diff = diff_graphs(before, after, added_lines=TOUCHED_D)

        result = analyze_impact(diff, head=after, base=before)
        assert result.impacted[0].rank != "public-api"
        assert any("public" in note.lower() for note in result.notes)


class TestClaimStrength:
    def test_a_caller_of_an_edited_symbol_only_could_be_affected(self) -> None:
        assert {i.claim_strength for i in chain_impact().impacted} == {"could-be-affected"}

    def test_a_caller_of_a_deleted_symbol_is_a_stronger_claim(self) -> None:
        """It referred to something that is not there any more."""
        gone, caller = sym("gone()."), sym("caller().")
        before = graph(
            BASE_SHA,
            [node(gone, "gone", start=40, end=49), node(caller, "caller", start=60, end=69)],
            [edge(caller, "calls", gone)],
        )
        after = graph(HEAD_SHA, [node(caller, "caller", start=60, end=69)], [])
        diff = diff_graphs(before, after)

        result = analyze_impact(diff, head=after, base=before)
        assert [i.label for i in result.impacted] == ["caller"]
        assert result.impacted[0].claim_strength == "referred-to-removed-symbol"

    def test_a_removed_caller_of_a_removed_symbol_is_not_reported(self) -> None:
        """Both went away together; there is nobody left to affect."""
        gone, caller = sym("gone()."), sym("caller().")
        before = graph(
            BASE_SHA,
            [node(gone, "gone", start=40, end=49), node(caller, "caller", start=60, end=69)],
            [edge(caller, "calls", gone)],
        )
        after = graph(HEAD_SHA, [], [])
        diff = diff_graphs(before, after)
        assert analyze_impact(diff, head=after, base=before).impacted == []


class TestHonesty:
    def test_the_precision_limit_travels_with_the_result(self) -> None:
        result = chain_impact()
        assert result.basis
        assert "possib" in result.caveat.lower() or "not certain" in result.caveat.lower()

    def test_a_change_with_no_seeds_reports_nothing_rather_than_everything(self) -> None:
        before = graph(BASE_SHA, CHAIN_NODES, CHAIN_EDGES)
        after = graph(HEAD_SHA, CHAIN_NODES, CHAIN_EDGES)
        diff = diff_graphs(before, after)  # no added_lines: nothing known to be touched
        result = analyze_impact(diff, head=after, base=before)
        assert result.impacted == []
        assert result.seeds == []
        assert any("no changed symbols" in note.lower() for note in result.notes)

    def test_the_result_is_deterministic(self) -> None:
        from codeatlas.core.canonical import canonical_sha256

        first = canonical_sha256(chain_impact(hops=2).contract_dump())
        second = canonical_sha256(chain_impact(hops=2).contract_dump())
        assert first == second


@pytest.mark.parametrize("hops", [0, -1])
def test_a_nonpositive_hop_budget_is_refused(hops: int) -> None:
    with pytest.raises(ValueError, match="at least one hop"):
        chain_impact(hops=hops)
