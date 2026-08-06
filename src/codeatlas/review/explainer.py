"""The change-explanation stage: infer, then verify, then keep only what survived.

Same order as intent reconstruction, for the same reason. Everything the agent is
given is deterministic and already computed — the diff, the structural delta, the
API delta, the impact set. The agent's job is to say what those mean. Citation
validation then runs *after* it and deletes anything that cannot be resolved
against the same artifacts.

Without a base revision there is nothing to explain the change against, and the
stage does not dispatch an agent at all.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from codeatlas.agents.budget import TokenBudget
from codeatlas.agents.dispatch import RunnableEngine, build_task, dispatch
from codeatlas.agents.registry import SkillRegistry
from codeatlas.artifacts.store import ArtifactStore
from codeatlas.core.logging import get_logger
from codeatlas.models.api import ApiChange
from codeatlas.models.diff import GraphDiff
from codeatlas.models.explanation import ChangeExplanation, DroppedClaim
from codeatlas.models.impact import ChangeImpact
from codeatlas.review.citations import CitationIndex, validate_explanation

log = get_logger("codeatlas.review.explainer")

SKILL_ID = "change-explainer"


def build_index(
    db_engine: Engine,
    base_revision_id: int,
    head_revision_id: int,
    base_sha: str,
    head_sha: str,
    diff: GraphDiff,
    api_change: ApiChange | None,
    impact: ChangeImpact | None,
) -> CitationIndex:
    """The universe a citation may point at: exactly what this run measured."""
    from sqlalchemy import select

    from codeatlas.db.tables import FileRow

    paths: dict[str, set[str]] = {}
    with Session(db_engine) as session:
        for sha, revision_id in ((base_sha, base_revision_id), (head_sha, head_revision_id)):
            paths[sha] = set(
                session.scalars(select(FileRow.path).where(FileRow.revision_id == revision_id))
            )

    api_items: set[str] = set()
    if api_change is not None:
        for package in api_change.packages:
            api_items.update(package.added)
            api_items.update(package.removed)

    return CitationIndex(
        base_revision=base_sha,
        head_revision=head_sha,
        paths_by_revision=paths,
        edge_ids={e.id for e in [*diff.edges.added, *diff.edges.removed]},
        api_items=api_items,
        impact_keys={i.stable_key for i in impact.impacted} if impact else set(),
    )


def measure_cited_files(
    index: CitationIndex,
    explanation: ChangeExplanation,
    read_lines: object,
) -> dict[tuple[str, str], int]:
    """Line counts for the files this explanation actually cites.

    Measured lazily and only for cited paths: a plausible path with an invented
    line number is the most convincing kind of wrong claim, and checking it is
    cheap when the set is the handful of files a narrative mentions rather than
    the whole tree.
    """
    from codeatlas.models.explanation import SourceCitation

    wanted: set[tuple[str, str]] = set()
    for section in explanation.sections:
        for claim in section.claims:
            for citation in claim.citations:
                if isinstance(citation, SourceCitation):
                    wanted.add((index.revision_sha(citation.revision), citation.path))

    counts: dict[tuple[str, str], int] = {}
    for revision, path in sorted(wanted):
        try:
            counts[(revision, path)] = read_lines(revision, path)  # type: ignore[operator]
        except Exception as exc:  # an unreadable file costs a check, not the run
            log.info("explainer.line_count_unavailable", path=path, error=str(exc))
    return counts


def explain_change(
    engine: RunnableEngine,
    registry: SkillRegistry,
    run_id: str,
    head_sha: str,
    checkout: Path,
    db_engine: Engine,
    cas: ArtifactStore,
    diff_text: str,
    diff: GraphDiff,
    api_change: ApiChange | None,
    impact: ChangeImpact | None,
    index: CitationIndex,
    budget: TokenBudget | None = None,
    read_lines: object | None = None,
) -> tuple[ChangeExplanation | None, list[DroppedClaim]]:
    """Produce a citation-validated explanation, or None if none could be made."""
    inputs = {
        "unifiedDiff": cas.put(diff_text.encode("utf-8")),
        "structuralDiff": cas.put_json(diff.contract_dump()),
    }
    if api_change is not None:
        inputs["apiChange"] = cas.put_json(api_change.contract_dump())
    if impact is not None:
        inputs["impact"] = cas.put_json(impact.contract_dump())

    skill = registry.get(SKILL_ID)
    task = build_task(
        skill=skill, run_id=run_id, revision_sha=head_sha, checkout=checkout, inputs=inputs
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
        log.error("explainer.failed", run_id=run_id, status=result.status, error=result.error)
        return None, []

    raw = ChangeExplanation.model_validate(result.output)
    if read_lines is not None:
        measured = measure_cited_files(index, raw, read_lines)
        index = CitationIndex(
            base_revision=index.base_revision,
            head_revision=index.head_revision,
            paths_by_revision=index.paths_by_revision,
            edge_ids=index.edge_ids,
            api_items=index.api_items,
            impact_keys=index.impact_keys,
            line_counts=measured,
        )

    validated, dropped = validate_explanation(raw, index)
    if dropped:
        log.info(
            "explainer.claims_dropped",
            run_id=run_id,
            dropped=len(dropped),
            kept=validated.claim_count,
        )
    return validated, dropped


def condensed_markdown(explanation: ChangeExplanation, limit: int = 6) -> str:
    """The short form for a pull-request comment.

    A review comment competes with everything else in a reviewer's inbox, so it
    carries the summary and the strongest few claims; the dashboard has the rest.
    Truncation is stated rather than silent.
    """
    lines = [explanation.summary, ""]
    shown = 0
    for section in explanation.sections:
        if shown >= limit:
            break
        lines.append(f"**{section.title}**")
        for claim in section.claims:
            if shown >= limit:
                break
            lines.append(f"- {claim.text} {_cite_suffix(claim)}".rstrip())
            shown += 1
        lines.append("")

    total = explanation.claim_count
    if shown < total:
        lines.append(f"_{total - shown} further point(s) in the CodeAtlas run._")
    if explanation.dropped_claims:
        lines.append(
            f"_{len(explanation.dropped_claims)} statement(s) were removed because their "
            "citations did not resolve against this revision._"
        )
    return "\n".join(lines).strip()


def _cite_suffix(claim: object) -> str:
    from codeatlas.models.explanation import ApiCitation, Claim, ImpactCitation, SourceCitation

    if not isinstance(claim, Claim):  # pragma: no cover - defensive
        return ""
    parts: list[str] = []
    for citation in claim.citations:
        if isinstance(citation, SourceCitation):
            where = citation.path
            if citation.start_line:
                where += f":{citation.start_line}"
            parts.append(where)
        elif isinstance(citation, ApiCitation):
            parts.append("public API")
        elif isinstance(citation, ImpactCitation):
            parts.append("impact set")
    unique = sorted(set(parts))
    return f"({', '.join(unique)})" if unique else ""
