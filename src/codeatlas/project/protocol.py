"""The protocol model: read out of the source, then checked back against it.

The third artifact under the rule the two narratives already follow, and the one
where inventing is easiest. A sequence diagram is the most confident picture
this tool can draw — named participants, ordered arrows, timeouts — and almost
none of it is visible in a dependency graph. It has to be read out of the code,
which is exactly why every element carries the source range it was read from and
why anything that does not resolve is deleted.

Two rules beyond the narratives':

**A message cannot outlive its participants.** An arrow leaving a box that was
not drawn is worse than a missing arrow — the reader sees a relationship with
one end unexplained and assumes they have missed something.

**A protocol with nothing left becomes a refusal, not a small diagram.** If
every participant was dropped there is no smaller honest picture to fall back
on; the model says there is no protocol here instead of drawing an empty one.
"""

from __future__ import annotations

import json
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
from codeatlas.models.protocol import (
    DroppedElement,
    Protocol,
    ProtocolEvidence,
    ProtocolModel,
)

log = get_logger("codeatlas.project.protocol")

SKILL_ID = "protocol-modeler"

NO_PROTOCOL = "no protocol interactions were found in this project"
NOTHING_SURVIVED = (
    "no participant in this protocol survived validation, so nothing is drawn; "
    "an empty diagram would claim a protocol exists"
)


@dataclass(frozen=True, slots=True)
class ProtocolIndex:
    """Everything a protocol element is allowed to point at."""

    revision: str
    paths: set[str]
    symbols: set[str]
    line_counts: dict[str, int] = field(default_factory=dict)


def build_protocol_index(
    graph: ProjectGraph, paths: set[str], line_counts: dict[str, int] | None = None
) -> ProtocolIndex:
    """The universe an element may point at: exactly what this run measured."""
    return ProtocolIndex(
        revision=graph.revision.head,
        paths=paths,
        symbols={node.id for node in graph.nodes},
        line_counts=dict(line_counts or {}),
    )


def evidence_problem(evidence: ProtocolEvidence, index: ProtocolIndex) -> str | None:
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


def validate_protocol_model(
    model: ProtocolModel, index: ProtocolIndex
) -> tuple[ProtocolModel, list[DroppedElement]]:
    """Return the model with only checkable elements, plus what was removed."""
    if model.protocol is None:
        return model, []

    protocol = model.protocol
    dropped: list[DroppedElement] = []

    participants = []
    for party in protocol.participants:
        problem = evidence_problem(party.evidence, index)
        if problem is None:
            participants.append(party)
        else:
            dropped.append(DroppedElement(kind="participant", name=party.name, reason=problem))
    surviving = {p.name for p in participants}

    messages = []
    for message in protocol.messages:
        problem = evidence_problem(message.evidence, index)
        if problem is None:
            # An arrow leaving a box that was not drawn is worse than no arrow.
            missing = [n for n in (message.producer, message.consumer) if n not in surviving]
            if missing:
                problem = f"its participant {missing[0]!r} did not survive validation"
        if problem is None:
            messages.append(message)
        else:
            dropped.append(DroppedElement(kind="message", name=message.name, reason=problem))

    states = set(protocol.states)
    timeouts = []
    for timeout in protocol.timeouts:
        problem = (
            evidence_problem(timeout.evidence, index) if timeout.evidence is not None else None
        )
        if problem is None and timeout.state not in states:
            problem = f"its state {timeout.state!r} is not one this protocol declares"
        if problem is None:
            timeouts.append(timeout)
        else:
            dropped.append(DroppedElement(kind="timeout", name=timeout.state, reason=problem))

    notes = list(model.notes)
    if not participants:
        notes.append(NOTHING_SURVIVED)
        return (
            ProtocolModel(
                protocol=None,
                dropped_elements=[*model.dropped_elements, *dropped],
                notes=notes,
            ),
            dropped,
        )

    validated = ProtocolModel(
        protocol=Protocol(
            id=protocol.id,
            version=protocol.version,
            transport=protocol.transport,
            framing=protocol.framing,
            participants=participants,
            states=protocol.states,
            messages=messages,
            timeouts=timeouts,
            evidence=protocol.evidence,
        ),
        dropped_elements=[*model.dropped_elements, *dropped],
        notes=notes,
    )
    return validated, dropped


def measure_cited_files(model: ProtocolModel, read_lines: object) -> dict[str, int]:
    """Line counts for the files this model actually cites."""
    if model.protocol is None:
        return {}
    protocol = model.protocol
    wanted = {
        *(p.evidence.path for p in protocol.participants),
        *(m.evidence.path for m in protocol.messages),
        *(t.evidence.path for t in protocol.timeouts if t.evidence),
        *(e.path for e in protocol.evidence),
    }
    counts: dict[str, int] = {}
    for path in sorted(wanted):
        try:
            counts[path] = read_lines(path)  # type: ignore[operator]
        except Exception as exc:  # an unreadable file costs a check, not the run
            log.info("protocol.line_count_unavailable", path=path, error=str(exc))
    return counts


def model_protocol(
    engine: RunnableEngine,
    registry: SkillRegistry,
    run_id: str,
    revision_sha: str,
    checkout: Path,
    db_engine: Engine,
    cas: ArtifactStore,
    graph: ProjectGraph,
    overview: ProjectOverview,
    index: ProtocolIndex,
    budget: TokenBudget | None = None,
    read_lines: object | None = None,
) -> tuple[ProtocolModel | None, list[DroppedElement]]:
    """Produce a validated protocol model, or None if the skill did not complete."""
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
        log.error("protocol.failed", run_id=run_id, status=result.status, error=result.error)
        return None, []

    raw = ProtocolModel.model_validate(result.output)
    if read_lines is not None:
        index = ProtocolIndex(
            revision=index.revision,
            paths=index.paths,
            symbols=index.symbols,
            line_counts=measure_cited_files(raw, read_lines),
        )

    validated, dropped = validate_protocol_model(raw, index)
    if dropped:
        log.info("protocol.elements_dropped", run_id=run_id, dropped=len(dropped))
    return validated, dropped


def load_graph(cas: ArtifactStore, sha: str) -> ProjectGraph:
    return ProjectGraph.model_validate(json.loads(cas.get(sha)))
