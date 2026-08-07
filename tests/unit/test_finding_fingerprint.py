"""The finding-memory identity (ADR-0016), pure parts: no database, no agent.

The fingerprint must survive exactly what changes between honest re-runs —
line drift and the model rewording its claim — and must differ on exactly what
distinguishes defects: category, file, and the definition the finding sits in.
"""

from __future__ import annotations

from codeatlas.models.findings import Finding
from codeatlas.models.graph import (
    Evidence,
    GraphNode,
    ProjectGraph,
    RepositoryRef,
    RevisionRef,
    SourceLocation,
)
from codeatlas.validation.memory import (
    FindingMemory,
    RememberedRejection,
    enclosing_symbol,
    finding_fingerprint,
    spans_overlap,
)

LSP = Evidence(kind="language-server", producer="rust-analyzer", confidence=1.0)
SHA = "a" * 40


def _node(nid: str, kind: str, path: str, start: int, end: int) -> GraphNode:
    return GraphNode(
        id=nid,
        kind=kind,  # type: ignore[arg-type]
        label=nid.rsplit("/", 1)[-1],
        location=SourceLocation(path=path, start_line=start, end_line=end),
        evidence=[LSP],
    )


def _graph(nodes: list[GraphNode]) -> ProjectGraph:
    return ProjectGraph(
        repository=RepositoryRef(id="local/kvstore"),
        revision=RevisionRef(head=SHA),
        nodes=nodes,
        edges=[],
    )


def _finding(
    category: str = "correctness",
    path: str = "src/cache.rs",
    start: int = 30,
    end: int = 32,
    claim: str = "unwrap on untrusted input",
) -> Finding:
    return Finding(
        finding_id="F-0001",
        category=category,  # type: ignore[arg-type]
        discovered_by_skill="reviewer-correctness",
        skill_version="1.1.0",
        severity="high",
        confidence=0.9,
        claim=claim,
        location=SourceLocation(path=path, start_line=start, end_line=end),
        evidence=[Evidence(kind="llm-inference", producer="reviewer-correctness", confidence=0.9)],
    )


class TestEnclosingSymbol:
    def test_the_smallest_containing_span_wins(self) -> None:
        graph = _graph(
            [
                _node("sym:impl", "type", "src/cache.rs", 10, 90),
                _node("sym:put", "function", "src/cache.rs", 25, 40),
            ]
        )
        assert enclosing_symbol(graph, "src/cache.rs", 30) == "sym:put"

    def test_ties_break_on_the_lexicographic_id(self) -> None:
        graph = _graph(
            [
                _node("sym:b", "function", "src/cache.rs", 25, 40),
                _node("sym:a", "function", "src/cache.rs", 25, 40),
            ]
        )
        assert enclosing_symbol(graph, "src/cache.rs", 30) == "sym:a"

    def test_module_level_code_has_no_symbol(self) -> None:
        graph = _graph([_node("sym:put", "function", "src/cache.rs", 25, 40)])
        assert enclosing_symbol(graph, "src/cache.rs", 5) is None

    def test_a_lineless_finding_has_no_symbol(self) -> None:
        graph = _graph([_node("sym:put", "function", "src/cache.rs", 25, 40)])
        assert enclosing_symbol(graph, "src/cache.rs", None) is None


class TestFingerprint:
    def test_line_drift_and_rewording_do_not_change_the_identity(self) -> None:
        a = finding_fingerprint("correctness", "src/cache.rs", "sym:put")
        b = finding_fingerprint("correctness", "src/cache.rs", "sym:put")
        assert a == b

    def test_category_path_and_symbol_each_change_it(self) -> None:
        base = finding_fingerprint("correctness", "src/cache.rs", "sym:put")
        assert finding_fingerprint("security", "src/cache.rs", "sym:put") != base
        assert finding_fingerprint("correctness", "src/api.rs", "sym:put") != base
        assert finding_fingerprint("correctness", "src/cache.rs", "sym:get") != base
        assert finding_fingerprint("correctness", "src/cache.rs", None) != base


class TestMatch:
    GRAPH = staticmethod(lambda: _graph([_node("sym:put", "function", "src/cache.rs", 25, 40)]))

    def _memory(
        self,
        blob: str = "b" * 40,
        row_start: int = 29,
        row_end: int = 33,
    ) -> FindingMemory:
        graph = self.GRAPH()
        fp = finding_fingerprint("correctness", "src/cache.rs", "sym:put")
        row = RememberedRejection(
            fingerprint=fp,
            file_blob_sha=blob,
            start_line=row_start,
            end_line=row_end,
            reason="the caller checks for None before this unwrap",
            decided_in_run="01RUN",
        )
        return FindingMemory(
            repository_id="local/kvstore",
            blob_shas={"src/cache.rs": blob},
            graph=graph,
            rows={(fp, blob): row},
        )

    def test_a_recurring_rejection_matches(self) -> None:
        hit = self._memory().match(_finding(claim="reworded claim, same defect"))
        assert hit is not None
        assert hit.reason == "the caller checks for None before this unwrap"
        assert hit.decided_in_run == "01RUN"

    def test_an_edited_file_reopens_the_question(self) -> None:
        memory = self._memory()
        edited = FindingMemory(
            repository_id=memory.repository_id,
            blob_shas={"src/cache.rs": "c" * 40},  # different blob at this revision
            graph=memory.graph,
            rows=memory.rows,
        )
        assert edited.match(_finding()) is None

    def test_a_different_defect_in_the_same_function_is_not_silenced(self) -> None:
        # Remembered span 29-33; a candidate at 36-38 shares the enclosing
        # symbol (same fingerprint) but cites different lines — validate it.
        assert self._memory().match(_finding(start=36, end=38)) is None

    def test_a_file_the_revision_does_not_have_never_matches(self) -> None:
        memory = self._memory()
        gone = FindingMemory(
            repository_id=memory.repository_id,
            blob_shas={},
            graph=memory.graph,
            rows=memory.rows,
        )
        assert gone.match(_finding()) is None


class TestSpansOverlap:
    def test_touching_ranges_overlap(self) -> None:
        assert spans_overlap(10, 20, 20, 25)

    def test_adjacent_ranges_do_not(self) -> None:
        assert not spans_overlap(10, 20, 21, 25)

    def test_lineless_spans_normalize_like_the_dedup_rule(self) -> None:
        assert spans_overlap(None, None, None, None)
