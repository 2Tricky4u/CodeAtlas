"""Post-schema graph constraints the JSON Schema cannot express.

From the research doc (~line 392): endpoint existence, ID uniqueness, line
ordering, non-LLM evidence on deterministic edges, path existence at the
analyzed revision. Violations are returned as human-readable strings; an empty
list means the graph passes. (Double-run reproducibility is a test-level gate;
extractor-conflict reconciliation arrives with multi-extractor overlap.)
"""

from __future__ import annotations

from codeatlas.models.graph import DETERMINISTIC_EVIDENCE_KINDS, ProjectGraph


def validate_graph(graph: ProjectGraph, valid_paths: set[str] | None = None) -> list[str]:
    violations: list[str] = []

    node_ids: set[str] = set()
    for node in graph.nodes:
        if node.id in node_ids:
            violations.append(f"duplicate node id: {node.id}")
        node_ids.add(node.id)
        loc = node.location
        if loc is not None:
            if (
                loc.start_line is not None
                and loc.end_line is not None
                and loc.start_line > loc.end_line
            ):
                violations.append(
                    f"node {node.id}: startLine {loc.start_line} > endLine {loc.end_line}"
                )
            if valid_paths is not None and loc.path not in valid_paths:
                violations.append(
                    f"node {node.id}: path {loc.path} does not exist at the analyzed revision"
                )

    edge_ids: set[str] = set()
    for edge in graph.edges:
        if edge.id in edge_ids:
            violations.append(f"duplicate edge id: {edge.id}")
        edge_ids.add(edge.id)
        if edge.source not in node_ids:
            violations.append(f"edge {edge.id}: source endpoint {edge.source} does not exist")
        if edge.target not in node_ids:
            violations.append(f"edge {edge.id}: target endpoint {edge.target} does not exist")
        # The evidence-discipline allowlist, load-bearing: an edge must carry
        # at least one measured kind. (Equivalent to "not all llm-inference"
        # while the vocabulary is the deterministic set plus llm-inference —
        # but the allowlist is the rule, so it is what the check reads.)
        if not any(ev.kind in DETERMINISTIC_EVIDENCE_KINDS for ev in edge.evidence):
            violations.append(
                f"edge {edge.id}: no deterministic evidence on a graph edge "
                "(every edge requires at least one measured evidence item)"
            )

    return violations
