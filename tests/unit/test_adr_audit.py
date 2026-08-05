"""ADR drift audit: does the implementation still honor accepted decisions?

Two rules dominate. The audit classifies into exactly four outcomes and says
`unverifiable` when it cannot check — an unchecked assertion must never be
reported as conformant. And the audit NEVER changes a decision's status; only a
human supersedes a decision.
"""

from __future__ import annotations

from codeatlas.adr.audit import (
    LayeringRule,
    audit_layering,
    classify_assertion,
)
from codeatlas.adr.parser import Decision
from codeatlas.models.graph import (
    Evidence,
    GraphEdge,
    GraphNode,
    ProjectGraph,
    RepositoryRef,
    RevisionRef,
    SourceLocation,
)

LS = Evidence(kind="language-server", producer="rust-analyzer", confidence=1.0)
SHA = "a" * 40


def _decision(
    status: str = "accepted", text: str = "api may use cache; storage depends on nothing"
) -> Decision:
    return Decision(
        path="docs/adr/adr-0001-layering.md",
        number=1,
        title="Strict downward layering",
        status=status,
        date="2026-01-15",
        superseded_by=None,
        decision_text=text,
        content_sha256="sha256:" + "0" * 64,
    )


def _graph(edges: list[GraphEdge]) -> ProjectGraph:
    files = ["kvstore/src/api.rs", "kvstore/src/cache.rs", "kvstore/src/storage.rs"]
    return ProjectGraph(
        repository=RepositoryRef(id="local/kvstore"),
        revision=RevisionRef(head=SHA),
        nodes=[
            GraphNode(
                id=f"file:{path}",
                kind="file",
                label=path,
                location=SourceLocation(path=path),
                evidence=[LS],
            )
            for path in files
        ]
        + [
            GraphNode(
                id="sym:scip/api/Response#",
                kind="type",
                label="Response",
                location=SourceLocation(path="kvstore/src/api.rs", start_line=6, end_line=10),
                evidence=[LS],
            )
        ],
        edges=edges,
    )


def _import(source_file: str, target_symbol: str) -> GraphEdge:
    return GraphEdge(
        id=f"edge:{source_file}->{target_symbol}",
        source=f"file:{source_file}",
        target=target_symbol,
        kind="imports",
        evidence=[LS],
    )


class TestLayeringAudit:
    def test_upward_import_is_probable_drift(self) -> None:
        rule = LayeringRule(layers=["api", "cache", "storage"], module_root="kvstore/src")
        graph = _graph([_import("kvstore/src/storage.rs", "sym:scip/api/Response#")])
        result = audit_layering(_decision(), rule, graph)
        assert result.audit_result == "probable-drift"
        assert result.affected_node_ids
        assert any("storage.rs" in n for n in result.affected_node_ids)
        assert result.requires_human_decision is True

    def test_downward_import_is_conformant(self) -> None:
        rule = LayeringRule(layers=["api", "cache", "storage"], module_root="kvstore/src")
        graph = _graph(
            [
                GraphEdge(
                    id="edge:ok",
                    source="file:kvstore/src/api.rs",
                    target="file:kvstore/src/cache.rs",
                    kind="imports",
                    evidence=[LS],
                )
            ]
        )
        assert audit_layering(_decision(), rule, graph).audit_result == "conformant"

    def test_no_evidence_at_all_is_unverifiable_not_conformant(self) -> None:
        """An audit with nothing to inspect has not verified anything."""
        rule = LayeringRule(layers=["api", "cache", "storage"], module_root="nonexistent/path")
        result = audit_layering(_decision(), rule, _graph([]))
        assert result.audit_result == "unverifiable"

    def test_superseded_decision_is_not_drift(self) -> None:
        rule = LayeringRule(layers=["api", "cache", "storage"], module_root="kvstore/src")
        graph = _graph([_import("kvstore/src/storage.rs", "sym:scip/api/Response#")])
        result = audit_layering(_decision(status="superseded"), rule, graph)
        assert result.audit_result == "intentionally-superseded"
        assert result.requires_human_decision is False

    def test_proposed_decision_does_not_bind(self) -> None:
        rule = LayeringRule(layers=["api", "cache", "storage"], module_root="kvstore/src")
        graph = _graph([_import("kvstore/src/storage.rs", "sym:scip/api/Response#")])
        assert audit_layering(_decision(status="proposed"), rule, graph).audit_result == (
            "unverifiable"
        )

    def test_result_carries_graph_edge_evidence(self) -> None:
        rule = LayeringRule(layers=["api", "cache", "storage"], module_root="kvstore/src")
        graph = _graph([_import("kvstore/src/storage.rs", "sym:scip/api/Response#")])
        result = audit_layering(_decision(), rule, graph)
        assert result.evidence
        assert result.evidence[0]["kind"] == "project-graph-edge"

    def test_audit_never_mutates_decision_status(self) -> None:
        rule = LayeringRule(layers=["api", "cache", "storage"], module_root="kvstore/src")
        decision = _decision()
        graph = _graph([_import("kvstore/src/storage.rs", "sym:scip/api/Response#")])
        audit_layering(decision, rule, graph)
        assert decision.status == "accepted", "the audit proposes; only a human supersedes"


class TestClassification:
    def test_four_outcomes_only(self) -> None:
        for outcome in (
            "conformant",
            "probable-drift",
            "unverifiable",
            "intentionally-superseded",
        ):
            assert classify_assertion(outcome) == outcome

    def test_unknown_outcome_becomes_unverifiable(self) -> None:
        assert classify_assertion("looks-fine-to-me") == "unverifiable"
