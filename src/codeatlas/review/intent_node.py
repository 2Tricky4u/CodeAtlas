"""The intent reconstruction stage: collect documents, infer, then verify.

Order matters. Document collection is deterministic; the agent only interprets
what was collected; citation verification runs *after* the agent and downgrades
anything it cannot confirm. If the repository states nothing, the stage records
`unavailable` without dispatching an agent at all — there is nothing to infer
from, and inventing requirements would be worse than admitting the gap.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine

from codeatlas.agents.budget import TokenBudget
from codeatlas.agents.dispatch import RunnableEngine, build_task, dispatch
from codeatlas.agents.registry import SkillRegistry
from codeatlas.artifacts.store import ArtifactStore
from codeatlas.core.logging import get_logger
from codeatlas.models.intent import IntentPackage, Requirement
from codeatlas.review.intent import collect_intent_sources, verify_citations

log = get_logger("codeatlas.review.intent")

SKILL_ID = "intent-reconstructor"


class IntentUnavailable(IntentPackage):
    """Marker subclass is unnecessary; kept as documentation of the shape."""


def _unavailable_package(reason: str) -> IntentPackage:
    return IntentPackage(
        requirements=[
            Requirement(
                id="REQ-001",
                source_kind="unavailable",
                source_ref=None,
                text=reason,
                acceptance_criteria=[],
            )
        ],
        non_goals=[],
        compatibility_obligations=[],
        unresolved_questions=["No stated intent was found in the repository."],
    )


def reconstruct_intent(
    engine: RunnableEngine,
    registry: SkillRegistry,
    run_id: str,
    revision_sha: str,
    checkout: Path,
    db_engine: Engine,
    cas: ArtifactStore,
    budget: TokenBudget | None = None,
) -> tuple[IntentPackage, list[str], str]:
    """Returns (verified intent package, citation problems, artifact sha256)."""
    sources = collect_intent_sources(checkout)

    if not sources:
        package = _unavailable_package(
            "No specification, ADR, or repository rule document exists at this revision."
        )
        log.info("intent.unavailable", run_id=run_id, revision=revision_sha)
        return package, [], cas.put_json(package.contract_dump())

    skill = registry.get(SKILL_ID)
    inputs = {"documents": cas.put_json([s.path for s in sources])}
    task = build_task(
        skill=skill,
        run_id=run_id,
        revision_sha=revision_sha,
        checkout=checkout,
        inputs=inputs,
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
        # A failed inference is not a licence to invent: record the gap instead.
        detail = result.error or "no output"
        package = _unavailable_package(
            f"Intent reconstruction did not complete ({result.status}): {detail}"
        )
        log.error("intent.failed", run_id=run_id, status=result.status, error=result.error)
        return package, [], cas.put_json(package.contract_dump())

    raw = IntentPackage.model_validate(result.output)
    valid_paths = {s.path for s in sources}
    package, problems = verify_citations(raw, valid_paths=valid_paths)
    if problems:
        log.info("intent.citations_downgraded", run_id=run_id, problems=problems)

    return package, problems, cas.put_json(package.contract_dump())
