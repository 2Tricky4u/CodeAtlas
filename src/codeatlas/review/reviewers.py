"""Specialist reviewer fan-out with structurally isolated contexts.

Every reviewer receives the *same* evidence bundle — intent, the source paths in
scope, and a graph slice — and differs only in its instructions. Because a task's
inputs are explicit artifact references, a reviewer cannot reach a sibling's
conclusions: there is no channel, not merely a rule against it.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import Engine

from codeatlas.agents.budget import TokenBudget
from codeatlas.agents.dispatch import RunnableEngine, build_task, dispatch_with_retry
from codeatlas.agents.registry import SkillRegistry
from codeatlas.artifacts.store import ArtifactStore
from codeatlas.core.logging import get_logger
from codeatlas.models.agent import AgentTask
from codeatlas.models.findings import Finding
from codeatlas.models.graph import ProjectGraph
from codeatlas.models.intent import IntentPackage

log = get_logger("codeatlas.review.reviewers")

REVIEWER_SKILLS: tuple[str, ...] = (
    "reviewer-correctness",
    "reviewer-security",
    "reviewer-architecture",
)


@dataclass(frozen=True, slots=True)
class ReviewOutcome:
    findings: list[Finding]
    failed_skills: list[str]  # reviewers that did not complete; coverage is degraded
    # Per reviewer: files the engine measured it reading, or None when the
    # engine reported nothing (replay of older recordings). Never model-claimed.
    files_read: dict[str, list[str] | None] = field(default_factory=dict)


def build_reviewer_inputs(
    cas: ArtifactStore,
    intent: IntentPackage,
    source_paths: list[str],
    graph_slice: dict[str, Any],
    threat_focus: dict[str, Any] | None = None,
) -> dict[str, str]:
    """The evidence bundle every reviewer receives — and nothing else.

    `threatFocus` is added only when the repository's threat model actually
    found threats: the key is absent for a repo with no attack surface, so
    the bundle shape — and therefore the cassette key — is unchanged for those
    repos. A model that found threats aims the reviewers; one that found none
    tells them nothing, and pretending otherwise would be noise.
    """
    inputs = {
        "intent": cas.put_json(intent.contract_dump()),
        "sourcePaths": cas.put_json(sorted(source_paths)),
        "graphSlice": cas.put_json(graph_slice),
    }
    if threat_focus is not None:
        inputs["threatFocus"] = cas.put_json(threat_focus)
    return inputs


def threat_focus_for_reviewers(threat_model: object) -> dict[str, Any] | None:
    """The aiming subset of a threat model, or None when there is nothing to aim by.

    Reviewers get the focus paths, the attacker's non-capabilities (what keeps
    them from inflating severity) and the criticality calibration — never the
    whole model, which would bury the aim in detail they do not need.
    """
    from codeatlas.models.threat import ThreatModel

    if not isinstance(threat_model, ThreatModel) or not threat_model.threats:
        return None
    focus: dict[str, Any] = {
        "focusPaths": [f.contract_dump() for f in threat_model.focus_paths],
    }
    if threat_model.attacker is not None:
        focus["attackerCannot"] = list(threat_model.attacker.non_capabilities)
    if threat_model.criticality is not None:
        focus["criticality"] = threat_model.criticality.contract_dump()
    return focus


def slice_graph_for_review(graph: ProjectGraph, source_paths: list[str]) -> dict[str, Any]:
    """Graph nodes/edges touching the reviewed files, as plain evidence."""
    in_scope = set(source_paths)
    nodes = [
        n.contract_dump()
        for n in graph.nodes
        if n.location is not None and n.location.path in in_scope
    ]
    node_ids = {n["id"] for n in nodes}
    edges = [e.contract_dump() for e in graph.edges if e.source in node_ids or e.target in node_ids]
    return {"nodes": nodes, "edges": edges}


def renumber_findings(batches: list[list[Finding]]) -> list[Finding]:
    """Merge per-reviewer findings into one deterministic id space.

    Each reviewer numbers from F-0001 in its own context, so ids collide across
    reviewers. Ordering is by (skill, path, line) so the merge is reproducible.
    """
    flat = [f for batch in batches for f in batch]
    flat.sort(
        key=lambda f: (
            f.discovered_by_skill,
            f.location.path,
            f.location.start_line or 0,
            f.claim,
        )
    )
    return [
        f.model_copy(update={"finding_id": f"F-{index:04d}"})
        for index, f in enumerate(flat, start=1)
    ]


def run_reviewers(
    engine: RunnableEngine,
    registry: SkillRegistry,
    run_id: str,
    revision_sha: str,
    checkout: Path,
    inputs: dict[str, str],
    db_engine: Engine,
    cas: ArtifactStore,
    budget: TokenBudget | None = None,
    skills: tuple[str, ...] = REVIEWER_SKILLS,
) -> ReviewOutcome:
    """Fan out to every reviewer in parallel; merge their findings.

    A reviewer that fails does not fail the run: its skill is recorded in
    `failed_skills` so the report can state the coverage gap explicitly rather
    than silently presenting partial review as complete.
    """

    def _one(skill_id: str) -> tuple[str, list[Finding] | None, list[str] | None]:
        def task_factory() -> AgentTask:
            return build_task(
                skill=registry.get(skill_id),
                run_id=run_id,
                revision_sha=revision_sha,
                checkout=checkout,
                inputs=inputs,
            )

        try:
            result = dispatch_with_retry(
                engine=engine,
                registry=registry,
                skill_id=skill_id,
                task_factory=task_factory,
                db_engine=db_engine,
                cas=cas,
                budget=budget,
            )
        except Exception as exc:
            log.error("reviewer.dispatch_failed", skill=skill_id, error=str(exc))
            return skill_id, None, None
        if result.status != "succeeded" or result.output is None:
            log.error("reviewer.failed", skill=skill_id, status=result.status, error=result.error)
            return skill_id, None, result.files_read
        findings = [Finding.model_validate(item) for item in result.output.get("findings", [])]
        return skill_id, findings, result.files_read

    with ThreadPoolExecutor(max_workers=len(skills)) as pool:
        results = list(pool.map(_one, skills))

    batches: list[list[Finding]] = []
    failed: list[str] = []
    files_read: dict[str, list[str] | None] = {}
    for skill_id, findings, read in sorted(results, key=lambda r: r[0]):
        files_read[skill_id] = read
        if findings is None:
            failed.append(skill_id)
        else:
            batches.append(findings)

    merged = renumber_findings(batches)
    log.info(
        "reviewers.completed",
        run_id=run_id,
        findings=len(merged),
        failed_skills=failed,
    )
    return ReviewOutcome(findings=merged, failed_skills=failed, files_read=files_read)
