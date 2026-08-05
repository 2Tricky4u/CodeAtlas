"""ADR conformance audit: is the code still doing what was decided?

Four outcomes, and only four: `conformant`, `probable-drift`, `unverifiable`,
`intentionally-superseded`. The important one is `unverifiable` — when there is
no evidence to check against, saying so is the honest answer, and reporting
conformance would be a claim the audit did not earn.

The audit **never changes a decision's lifecycle**. Superseding a decision is a
human act; this code produces findings and proposals, nothing more.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from codeatlas.adr.parser import Decision
from codeatlas.core.logging import get_logger
from codeatlas.models.graph import ProjectGraph

log = get_logger("codeatlas.adr.audit")

AuditResult = Literal["conformant", "probable-drift", "unverifiable", "intentionally-superseded"]

_VALID_RESULTS = frozenset(
    {"conformant", "probable-drift", "unverifiable", "intentionally-superseded"}
)


def classify_assertion(value: str) -> AuditResult:
    """Coerce a claimed outcome into the closed set; anything else is unverifiable."""
    return value if value in _VALID_RESULTS else "unverifiable"  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class LayeringRule:
    """Layers named outermost-first: each may depend downward, never upward."""

    layers: list[str]
    module_root: str  # e.g. "kvstore/src"

    def layer_of(self, path: str) -> str | None:
        if not path.startswith(self.module_root.rstrip("/") + "/"):
            return None
        tail = path[len(self.module_root.rstrip("/")) + 1 :]
        stem = tail.split("/")[0].removesuffix(".rs")
        return stem if stem in self.layers else None

    def rank(self, layer: str) -> int:
        return self.layers.index(layer)


@dataclass(frozen=True, slots=True)
class AssertionAudit:
    adr_path: str
    adr_label: str
    status: str
    assertion: str
    audit_result: AuditResult
    confidence: float
    requires_human_decision: bool
    affected_node_ids: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    detail: str = ""


def _layer_of_target(rule: LayeringRule, target_id: str, graph: ProjectGraph) -> str | None:
    """Resolve an edge target (file or symbol node) to its layer."""
    node = next((n for n in graph.nodes if n.id == target_id), None)
    if node is not None and node.location is not None:
        layer = rule.layer_of(node.location.path)
        if layer is not None:
            return layer
    # SCIP symbols encode their module: "... kvstore 0.1.0 api/Response#"
    for layer in rule.layers:
        if f" {layer}/" in target_id or target_id.endswith(f"/{layer}"):
            return layer
    return None


def audit_layering(decision: Decision, rule: LayeringRule, graph: ProjectGraph) -> AssertionAudit:
    """Check a layering decision against the graph's import edges."""
    assertion = (
        f"Dependencies flow downward through {' -> '.join(rule.layers)}; "
        "upward imports are prohibited."
    )

    def outcome(
        audit_result: AuditResult,
        confidence: float,
        requires_human_decision: bool,
        detail: str,
        affected_node_ids: list[str] | None = None,
        evidence: list[dict[str, Any]] | None = None,
    ) -> AssertionAudit:
        return AssertionAudit(
            adr_path=decision.path,
            adr_label=decision.label,
            status=decision.status,
            assertion=assertion,
            audit_result=audit_result,
            confidence=confidence,
            requires_human_decision=requires_human_decision,
            affected_node_ids=affected_node_ids or [],
            evidence=evidence or [],
            detail=detail,
        )

    if decision.status in ("superseded", "deprecated", "rejected"):
        return outcome(
            "intentionally-superseded",
            1.0,
            False,
            f"decision status is {decision.status}; it no longer binds",
        )

    if not decision.is_binding:
        return outcome(
            "unverifiable",
            1.0,
            False,
            f"decision is {decision.status}, not accepted, so it does not bind",
        )

    # Is there anything to check? A rule whose layers appear nowhere in the graph
    # has verified nothing, and must not report conformance.
    inspected = 0
    violations: list[tuple[str, str, str, str]] = []  # (edge_id, src_path, src_layer, dst_layer)

    for edge in graph.edges:
        if edge.kind not in ("imports", "calls", "depends-on"):
            continue
        source_node = next((n for n in graph.nodes if n.id == edge.source), None)
        if source_node is None or source_node.location is None:
            continue
        source_layer = rule.layer_of(source_node.location.path)
        if source_layer is None:
            continue
        target_layer = _layer_of_target(rule, edge.target, graph)
        if target_layer is None:
            continue
        inspected += 1
        if rule.rank(target_layer) < rule.rank(source_layer):
            violations.append((edge.id, source_node.location.path, source_layer, target_layer))

    if inspected == 0:
        return outcome(
            "unverifiable",
            1.0,
            False,
            f"no dependency edges between the layers {rule.layers} were found under "
            f"{rule.module_root!r}; nothing could be checked",
        )

    if not violations:
        return outcome(
            "conformant",
            0.9,
            False,
            f"{inspected} inter-layer edges inspected; all flow downward",
        )

    log.info(
        "adr.drift_detected",
        adr=decision.label,
        violations=len(violations),
        inspected=inspected,
    )
    return outcome(
        "probable-drift",
        0.93,
        True,
        f"{len(violations)} upward dependency edge(s) of {inspected} inspected: "
        + "; ".join(f"{path} ({s} -> {t})" for _, path, s, t in sorted(violations)[:5]),
        affected_node_ids=sorted({f"file:{path}" for _, path, _, _ in violations}),
        evidence=[
            {
                "kind": "project-graph-edge",
                "edge": edge_id,
                "path": path,
                "from": source_layer,
                "to": target_layer,
            }
            for edge_id, path, source_layer, target_layer in sorted(violations)
        ],
    )
