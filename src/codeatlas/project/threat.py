"""The threat model: hypotheses about attack, checked claims about defense.

Fourth artifact under the rule the narratives and the protocol model follow,
with one asymmetry the others do not have. A threat is a question the model
asks of the code — "an attacker could send an oversized frame" needs no
citation, and deleting it for want of one would delete exactly the doubts a
reviewer should keep. A control is an answer: "the length is capped before
allocation" reassures, and reassurance nobody can point at is the one thing
this artifact must never carry. So threats survive validation untouched, while
a control whose evidence does not resolve keeps its text, loses its evidence,
and is marked unverified.

Structural rules, in the protocol model's mold:

**A boundary cannot outlive its components.** A trust boundary with one end
unexplained tells the reader less than no boundary at all.

**Focus paths aim the reviewers, so each must name a file this revision has** —
and a model left with exactly one loses that too, because the contract forbids
a single "focus": it is a token gesture, not aiming.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import Engine

from codeatlas.agents.budget import TokenBudget
from codeatlas.agents.dispatch import RunnableEngine, build_task, dispatch
from codeatlas.agents.registry import SkillRegistry
from codeatlas.artifacts.store import ArtifactStore
from codeatlas.core.logging import get_logger
from codeatlas.models.graph import ProjectGraph
from codeatlas.models.overview import ProjectOverview
from codeatlas.models.threat import (
    FocusPath,
    Threat,
    ThreatBoundary,
    ThreatComponent,
    ThreatControl,
    ThreatDroppedElement,
    ThreatEvidence,
    ThreatModel,
)

log = get_logger("codeatlas.project.threat")

SKILL_ID = "threat-modeler"

LONE_FOCUS = (
    "a single focus path is a token gesture, not aiming; its companions did not survive validation"
)


@dataclass(frozen=True, slots=True)
class ThreatIndex:
    """Everything a threat-model element is allowed to point at."""

    revision: str
    paths: set[str]
    symbols: set[str]
    line_counts: dict[str, int] = field(default_factory=dict)


def build_threat_index(
    graph: ProjectGraph, paths: set[str], line_counts: dict[str, int] | None = None
) -> ThreatIndex:
    """The universe an element may point at: exactly what this run measured."""
    return ThreatIndex(
        revision=graph.revision.head,
        paths=paths,
        symbols={node.id for node in graph.nodes},
        line_counts=dict(line_counts or {}),
    )


def evidence_problem(evidence: ThreatEvidence, index: ThreatIndex) -> str | None:
    """The reason this evidence does not resolve, or None if it does."""
    if evidence.path not in index.paths:
        return f"{evidence.path} does not exist at this revision"
    if evidence.symbol is not None and evidence.symbol not in index.symbols:
        return f"{evidence.symbol} is not a symbol this run's graph contains"
    start, end = evidence.start_line, evidence.end_line
    if start is not None and end is not None and end < start:
        return f"{evidence.path}:{start}-{end} ends before it begins"
    total = index.line_counts.get(evidence.path)
    if total is None:
        return None  # the path checks out; line bounds were not measured
    for line in (start, end):
        if line is not None and line > total:
            return f"{evidence.path}:{line} is past the end of the file ({total} lines)"
    return None


def _validate_controls(
    threat: Threat, index: ThreatIndex, dropped: list[ThreatDroppedElement]
) -> Threat:
    """Re-measure every control claim. `verified` is set here and only here —
    whatever the agent wrote, a control is verified iff its evidence resolves."""
    controls: list[ThreatControl] = []
    for control in threat.existing_controls:
        problem = (
            evidence_problem(control.evidence, index) if control.evidence is not None else None
        )
        if control.evidence is not None and problem is None:
            controls.append(control.model_copy(update={"verified": True}))
        elif problem is not None:
            # The text stays — the claim was made — but the authority goes.
            controls.append(control.model_copy(update={"evidence": None, "verified": False}))
            dropped.append(
                ThreatDroppedElement(
                    kind="control", name=f"{threat.id}: {control.description}", reason=problem
                )
            )
        else:
            controls.append(control.model_copy(update={"verified": False}))
    return threat.model_copy(update={"existing_controls": controls})


def validate_threat_model(
    model: ThreatModel, index: ThreatIndex
) -> tuple[ThreatModel, list[ThreatDroppedElement]]:
    """Return the model with only checkable elements, plus what was removed."""
    dropped: list[ThreatDroppedElement] = []

    components: list[ThreatComponent] = []
    for comp in model.components:
        problem = evidence_problem(comp.evidence, index)
        if problem is None:
            components.append(comp)
        else:
            dropped.append(ThreatDroppedElement(kind="component", name=comp.name, reason=problem))
    surviving = {c.name for c in components}

    boundaries: list[ThreatBoundary] = []
    for bound in model.boundaries:
        # A trust boundary with one end unexplained is worse than none.
        missing = [name for name in bound.between if name not in surviving]
        if missing:
            dropped.append(
                ThreatDroppedElement(
                    kind="boundary",
                    name=bound.name,
                    reason=f"its component {missing[0]!r} did not survive validation",
                )
            )
            continue
        kept_evidence = [e for e in bound.evidence if evidence_problem(e, index) is None]
        if not kept_evidence:
            first_problem = evidence_problem(bound.evidence[0], index)
            dropped.append(
                ThreatDroppedElement(
                    kind="boundary", name=bound.name, reason=first_problem or "no evidence"
                )
            )
            continue
        boundaries.append(bound.model_copy(update={"evidence": kept_evidence}))

    # Threats are hypotheses and survive untouched; their controls are claims
    # and are re-measured.
    threats = [_validate_controls(threat, index, dropped) for threat in model.threats]
    threat_ids = {t.id for t in threats}

    focus_paths: list[FocusPath] = []
    for focus in model.focus_paths:
        if focus.path not in index.paths:
            dropped.append(
                ThreatDroppedElement(
                    kind="focusPath",
                    name=focus.path,
                    reason=f"{focus.path} does not exist at this revision",
                )
            )
            continue
        known = [tid for tid in focus.threat_ids if tid in threat_ids]
        focus_paths.append(
            focus if known == focus.threat_ids else focus.model_copy(update={"threat_ids": known})
        )
    if len(focus_paths) == 1:
        # The contract forbids exactly one, and validation must not hand the
        # model a shape the model itself refuses.
        dropped.append(
            ThreatDroppedElement(kind="focusPath", name=focus_paths[0].path, reason=LONE_FOCUS)
        )
        focus_paths = []

    validated = ThreatModel(
        modeled_at_revision=model.modeled_at_revision,
        summary=model.summary,
        components=components,
        boundaries=boundaries,
        assets=model.assets,
        attacker=model.attacker,
        threats=threats,
        criticality=model.criticality,
        focus_paths=focus_paths,
        dropped_elements=[*model.dropped_elements, *dropped],
        notes=model.notes,
    )
    return validated, dropped


def measure_cited_files(model: ThreatModel, read_lines: object) -> dict[str, int]:
    """Line counts for the files this model actually cites."""
    wanted = {
        *(c.evidence.path for c in model.components),
        *(e.path for b in model.boundaries for e in b.evidence),
        *(
            c.evidence.path
            for t in model.threats
            for c in t.existing_controls
            if c.evidence is not None
        ),
    }
    counts: dict[str, int] = {}
    for path in sorted(wanted):
        try:
            counts[path] = read_lines(path)  # type: ignore[operator]
        except Exception as exc:  # an unreadable file costs a check, not the run
            log.info("threat.line_count_unavailable", path=path, error=str(exc))
    return counts


def model_threats(
    engine: RunnableEngine,
    registry: SkillRegistry,
    run_id: str,
    revision_sha: str,
    checkout: Path,
    db_engine: Engine,
    cas: ArtifactStore,
    graph: ProjectGraph,
    overview: ProjectOverview,
    index: ThreatIndex,
    budget: TokenBudget | None = None,
    read_lines: object | None = None,
) -> tuple[ThreatModel | None, list[ThreatDroppedElement]]:
    """Produce a validated threat model, or None if the skill did not complete."""
    inputs = {"overview": cas.put_json(overview.contract_dump())}

    skill = registry.get(SKILL_ID)
    task = build_task(
        skill=skill, run_id=run_id, revision_sha=revision_sha, checkout=checkout, inputs=inputs
    )
    result = dispatch(
        engine=engine,
        registry=registry,
        skill_id=SKILL_ID,
        task=task,
        db_engine=db_engine,
        cas=cas,
        budget=budget,
    )
    if result.status != "succeeded" or result.output is None:
        log.error("threat.failed", run_id=run_id, status=result.status, error=result.error)
        return None, []

    raw = ThreatModel.model_validate(result.output)
    # The revision is measured, not taken from the agent: whatever it wrote,
    # this model describes the revision this run checked it against.
    raw = raw.model_copy(update={"modeled_at_revision": index.revision})
    if read_lines is not None:
        index = ThreatIndex(
            revision=index.revision,
            paths=index.paths,
            symbols=index.symbols,
            line_counts=measure_cited_files(raw, read_lines),
        )

    validated, dropped = validate_threat_model(raw, index)
    if dropped:
        log.info("threat.elements_dropped", run_id=run_id, dropped=len(dropped))
    return validated, dropped
