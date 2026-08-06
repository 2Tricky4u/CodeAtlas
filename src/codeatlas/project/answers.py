"""Ask a question about one part of the code; get an answer you can check.

The fourth artifact under the narratives' rule, and the first produced on
demand rather than at run time. The scope is one module or symbol; the agent
gets that scope's graph slice, its source and the overview, and every claim in
its answer must resolve against them or be deleted. Answers are cached
content-addressed by (revision, scope, question), so a repeated question is
free and every answer is reproducible evidence like any other artifact.

Runs under ADR-0014: local analysis only — this module can store and index, and
has no path to any publication or approval code.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import Engine

from codeatlas.agents.budget import TokenBudget
from codeatlas.agents.dispatch import RunnableEngine, build_task, dispatch
from codeatlas.agents.registry import SkillRegistry
from codeatlas.artifacts.store import ArtifactStore
from codeatlas.core.logging import get_logger
from codeatlas.models.code_answer import AnswerClaim, CodeAnswer
from codeatlas.models.explanation import DroppedClaim
from codeatlas.models.graph import ProjectGraph
from codeatlas.project.narrative import ProjectCitationIndex, project_citation_problem
from codeatlas.review.citations import partition_claims

log = get_logger("codeatlas.project.answers")

SKILL_ID = "code-answerer"


def answer_role(revision: str, scope: str, question: str) -> str:
    """The artifact role an answer is cached under.

    Keyed by content so the same question about the same code at the same
    revision resolves to the same artifact, however many times it is asked.
    """
    digest = hashlib.sha256(f"{revision}\n{scope}\n{question}".encode()).hexdigest()[:16]
    return f"code-answer-{digest}"


def build_answer_index(graph: ProjectGraph, scope: str, paths: set[str]) -> ProjectCitationIndex:
    """The universe an answer may cite: the same shape the narrative validates
    against, so the same validator applies unchanged."""
    return ProjectCitationIndex(
        revision=graph.revision.head,
        paths=paths,
        module_keys={node.id for node in graph.nodes if node.kind == "file"}
        | {f"file:{scope}", scope},
        package_names=set(),
        cycles=set(),
    )


def validate_answer(
    answer: CodeAnswer, index: ProjectCitationIndex
) -> tuple[CodeAnswer, list[DroppedClaim]]:
    """Delete every claim whose citations do not resolve; disclose the deletion."""
    if answer.refused is not None:
        return answer, []

    # partition_claims wants sections; an answer is one section.
    class _Section:
        id = "answer"
        title = "answer"

        def __init__(self, claims: list[AnswerClaim]) -> None:
            self.claims = claims

    kept_sections, dropped = partition_claims(
        [_Section(answer.claims)],
        lambda citation: project_citation_problem(citation, index),
    )
    kept_claims = (
        [AnswerClaim(text=text, citations=citations) for text, citations in kept_sections[0].claims]
        if kept_sections
        else []
    )

    notes = list(answer.notes)
    if not kept_claims and answer.claims:
        notes.append(
            "no claim in this answer survived citation validation; "
            "nothing here is supported by the run's own evidence"
        )

    validated = CodeAnswer(
        question=answer.question,
        scope=answer.scope,
        answer=answer.answer if kept_claims else None,
        claims=kept_claims,
        refused=answer.refused
        if answer.refused
        else (None if kept_claims else "every claim failed citation validation"),
        dropped_claims=[*answer.dropped_claims, *dropped],
        notes=notes,
    )
    return validated, dropped


def answer_question(
    engine: RunnableEngine,
    registry: SkillRegistry,
    run_id: str,
    revision_sha: str,
    checkout: Path,
    db_engine: Engine,
    cas: ArtifactStore,
    scope: str,
    question: str,
    index: ProjectCitationIndex,
    budget: TokenBudget | None = None,
) -> tuple[CodeAnswer | None, list[DroppedClaim]]:
    """Dispatch the skill and validate what comes back."""
    inputs = {
        "question": cas.put_json({"question": question, "scope": scope}),
    }
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
        log.error("answers.failed", run_id=run_id, status=result.status, error=result.error)
        return None, []

    raw = CodeAnswer.model_validate(result.output)
    validated, dropped = validate_answer(raw, index)
    if dropped:
        log.info("answers.claims_dropped", run_id=run_id, dropped=len(dropped))
    return validated, dropped
