"""Cytoscape.js elements export: a pure projection of the project graph.

Every element keeps provenance attributes (evidence producers, max confidence)
so the dashboard can filter by evidence type and link back to pinned source.
"""

from __future__ import annotations

from typing import Any

from codeatlas.models.graph import ProjectGraph


def to_cytoscape(graph: ProjectGraph) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    for node in graph.nodes:
        data: dict[str, Any] = {
            "id": node.id,
            "label": node.label,
            "kind": node.kind,
            "producers": sorted({e.producer for e in node.evidence}),
            "maxConfidence": max((e.confidence or 1.0) for e in node.evidence),
        }
        if node.language:
            data["language"] = node.language
        if node.location:
            data["path"] = node.location.path
            if node.location.start_line is not None:
                data["startLine"] = node.location.start_line
            if node.location.end_line is not None:
                data["endLine"] = node.location.end_line
        if node.metrics is not None and "public" in node.metrics:
            data["public"] = bool(node.metrics["public"])
        nodes.append({"data": data})

    edges: list[dict[str, Any]] = []
    for edge in graph.edges:
        edata: dict[str, Any] = {
            "id": edge.id,
            "source": edge.source,
            "target": edge.target,
            "kind": edge.kind,
            "producers": sorted({e.producer for e in edge.evidence}),
            "maxConfidence": max((e.confidence or 1.0) for e in edge.evidence),
        }
        if edge.configuration:
            edata["configuration"] = edge.configuration
        edges.append({"data": edata})

    return {
        "revision": graph.revision.head,
        "repository": graph.repository.id,
        "elements": {"nodes": nodes, "edges": edges},
    }
