"""The ADR audit as an artifact: decisions in the order they were taken.

Deterministic throughout — parsing the ADR directory and checking each decision
against the graph's import edges involves no model. It therefore belongs in the
deterministic half of the pipeline: whether the code still does what was decided
is a question about a repository, not about a change to it, and it should be
answerable on a run nobody paid to review.

The audit is pinned by `adr-audit.v1` like everything else the pipeline emits.
Before this it was a list of hand-built dictionaries, so its shape could change
under the dashboard without anything failing, and it dropped the two fields the
parser already had — the date and what superseded a decision. Without those an
ADR list is a set rather than a history, and a superseded decision looks like a
live one that happens to disagree with the code.
"""

from __future__ import annotations

from pathlib import Path

from codeatlas.adr.audit import AssertionAudit, LayeringRule, audit_layering
from codeatlas.adr.parser import Decision, parse_adr_directory
from codeatlas.models.adr_audit import AdrAudit, AuditedDecision
from codeatlas.models.graph import ProjectGraph


def audit_decisions(checkout: Path, graph: ProjectGraph, revision: str) -> AdrAudit:
    """Parse this repository's ADRs and check each against the graph."""
    from codeatlas.pipeline.review_stages import _infer_layers, _module_root

    decisions = parse_adr_directory(checkout / "docs" / "adr", root=checkout)
    rule = LayeringRule(layers=_infer_layers(graph), module_root=_module_root(graph))
    return build_adr_audit(revision, [(d, audit_layering(d, rule, graph)) for d in decisions])


def build_adr_audit(revision: str, audited: list[tuple[Decision, AssertionAudit]]) -> AdrAudit:
    """Assemble the audit artifact, ordered oldest decision first."""
    decisions = [
        AuditedDecision(
            adr=result.adr_path,
            label=result.adr_label,
            number=decision.number,
            title=decision.title,
            status=result.status,
            date=decision.date,
            superseded_by=decision.superseded_by,
            assertion=result.assertion,
            audit_result=result.audit_result,
            confidence=result.confidence,
            requires_human_decision=result.requires_human_decision,
            affected_nodes=list(result.affected_node_ids),
            evidence=list(result.evidence),
            detail=result.detail,
        )
        for decision, result in audited
    ]
    # Numbered decisions first in order, then anything unnumbered — an ADR
    # directory usually holds a README or a template, and sorting on a missing
    # number would either crash or silently interleave them.
    decisions.sort(key=lambda d: (d.number is None, d.number or 0, d.adr))

    notes: list[str] = []
    if not decisions:
        notes.append("no ADRs found; architecture conformance was not audited")
    drifting = [d for d in decisions if d.audit_result == "probable-drift"]
    if drifting:
        notes.append(f"{len(drifting)} decision(s) show probable drift from the code")
    unverifiable = [d for d in decisions if d.audit_result == "unverifiable"]
    if unverifiable:
        notes.append(
            f"{len(unverifiable)} decision(s) could not be checked: there was no evidence "
            "in the graph to check them against, which is not the same as conformance"
        )

    return AdrAudit(revision=revision, decisions=decisions, notes=notes)
