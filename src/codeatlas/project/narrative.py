"""The project-explanation stage: describe, then verify, then keep what survived.

`overview.py` already established, without a model, what this project contains
at this revision — its packages, its modules and their levels, its cycles, its
orphans, where execution starts. That is the whole universe a narrative claim
may point at. The agent's job is to say what those facts *mean* to someone
opening the repository for the first time; anything it says that cannot be
resolved back to them is deleted.

This matters more here than for a change. A change explanation is read beside a
diff, which contradicts it if it is wrong. A project explanation is read by
someone with no independent picture of the project at all — it is the picture.
CodeWikiBench measured un-provenanced LLM architecture narration at 64-69%
quality, with DeepWiki inventing installation methods and omitting whole
compiler passes; a newcomer has nothing to check that against.
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
from codeatlas.models.explanation import DroppedClaim
from codeatlas.models.overview import ProjectOverview
from codeatlas.models.project_explanation import (
    CycleCitation,
    ModuleCitation,
    PackageCitation,
    ProjectCitation,
    ProjectClaim,
    ProjectExplanation,
    ProjectSection,
    ProjectSourceCitation,
)
from codeatlas.review.citations import NOTHING_SURVIVED, partition_claims

log = get_logger("codeatlas.project.narrative")

SKILL_ID = "project-explainer"


@dataclass(frozen=True, slots=True)
class ProjectCitationIndex:
    """Everything a project claim is allowed to point at."""

    revision: str
    paths: set[str]
    module_keys: set[str]
    package_names: set[str]
    #: Member sets of the cycles the deterministic pass found, order-insensitive.
    cycles: set[frozenset[str]]
    line_counts: dict[str, int] = field(default_factory=dict)


def build_project_index(
    overview: ProjectOverview,
    paths: set[str],
    line_counts: dict[str, int] | None = None,
) -> ProjectCitationIndex:
    """The universe a citation may point at: exactly what this run measured."""
    return ProjectCitationIndex(
        revision=overview.revision,
        paths=paths,
        module_keys={module.key for module in overview.modules},
        package_names={package.name for package in overview.packages},
        cycles={frozenset(cycle.members) for cycle in overview.cycles},
        line_counts=dict(line_counts or {}),
    )


def project_citation_problem(citation: ProjectCitation, index: ProjectCitationIndex) -> str | None:
    """The reason this citation does not resolve, or None if it does."""
    if isinstance(citation, ModuleCitation):
        if citation.key not in index.module_keys:
            return f"{citation.key} is not a module this overview measured"
        return None
    if isinstance(citation, PackageCitation):
        if citation.name not in index.package_names:
            return f"{citation.name!r} is not a package this overview measured"
        return None
    if isinstance(citation, CycleCitation):
        if frozenset(citation.members) not in index.cycles:
            named = ", ".join(sorted(citation.members))
            return f"no cycle with exactly these members was found: {named}"
        return None
    assert isinstance(citation, ProjectSourceCitation)
    # The union is closed and discriminated, so this is the last arm.
    return _source_problem(citation, index)


def _source_problem(citation: ProjectSourceCitation, index: ProjectCitationIndex) -> str | None:
    if citation.path not in index.paths:
        return f"{citation.path} does not exist at this revision"
    start, end = citation.start_line, citation.end_line
    if start is not None and end is not None and end < start:
        return f"{citation.path}:{start}-{end} ends before it begins"
    total = index.line_counts.get(citation.path)
    if total is None:
        return None  # the path checks out; line bounds were not measured
    for line in (start, end):
        if line is not None and line > total:
            return f"{citation.path}:{line} is past the end of the file ({total} lines)"
    return None


def validate_project_explanation(
    explanation: ProjectExplanation, index: ProjectCitationIndex
) -> tuple[ProjectExplanation, list[DroppedClaim]]:
    """Return the explanation with only checkable claims, plus what was removed."""
    kept, dropped = partition_claims(
        explanation.sections, lambda citation: project_citation_problem(citation, index)
    )
    sections = [
        ProjectSection(
            id=section.id,  # type: ignore[arg-type]
            title=section.title,
            claims=[
                ProjectClaim(text=text, citations=citations) for text, citations in section.claims
            ],
        )
        for section in kept
    ]

    notes = list(explanation.notes)
    if not sections and not any("no claim" in note.lower() for note in notes):
        notes.append(NOTHING_SURVIVED)

    validated = ProjectExplanation(
        summary=explanation.summary,
        sections=sections,
        dropped_claims=[*explanation.dropped_claims, *dropped],
        notes=notes,
    )
    return validated, dropped


def measure_cited_files(explanation: ProjectExplanation, read_lines: object) -> dict[str, int]:
    """Line counts for the files this explanation actually cites.

    Measured lazily and only for cited paths: a plausible path with an invented
    line number is the most convincing kind of wrong claim, and checking it is
    cheap when the set is the handful of files a narrative mentions rather than
    the whole tree.
    """
    wanted = {
        citation.path
        for section in explanation.sections
        for claim in section.claims
        for citation in claim.citations
        if isinstance(citation, ProjectSourceCitation)
    }
    counts: dict[str, int] = {}
    for path in sorted(wanted):
        try:
            counts[path] = read_lines(path)  # type: ignore[operator]
        except Exception as exc:  # an unreadable file costs a check, not the run
            log.info("narrative.line_count_unavailable", path=path, error=str(exc))
    return counts


def explain_project(
    engine: RunnableEngine,
    registry: SkillRegistry,
    run_id: str,
    revision_sha: str,
    checkout: Path,
    db_engine: Engine,
    cas: ArtifactStore,
    overview: ProjectOverview,
    index: ProjectCitationIndex,
    budget: TokenBudget | None = None,
    read_lines: object | None = None,
) -> tuple[ProjectExplanation | None, list[DroppedClaim]]:
    """Produce a citation-validated project explanation, or None if none could be made."""
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
        log.error("narrative.failed", run_id=run_id, status=result.status, error=result.error)
        return None, []

    raw = ProjectExplanation.model_validate(result.output)
    if read_lines is not None:
        index = ProjectCitationIndex(
            revision=index.revision,
            paths=index.paths,
            module_keys=index.module_keys,
            package_names=index.package_names,
            cycles=index.cycles,
            line_counts=measure_cited_files(raw, read_lines),
        )

    validated, dropped = validate_project_explanation(raw, index)
    if dropped:
        log.info(
            "narrative.claims_dropped",
            run_id=run_id,
            dropped=len(dropped),
            kept=validated.claim_count,
        )
    return validated, dropped


def load_overview(cas: ArtifactStore, sha: str | None) -> ProjectOverview | None:
    """Load the overview this narrative must be checked against."""
    if sha is None:
        return None
    return ProjectOverview.model_validate(json.loads(cas.get(sha)))
