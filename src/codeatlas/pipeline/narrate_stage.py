"""The narrate stage: say what this project is, checked against the overview.

Its own module and its own pipeline node, because project comprehension does not
depend on there being a change to review. It used to live inside `review`, which
meant narrating a repository also ran four reviewers, an adversarial validator
per finding, the C4 export and the ADR audit — or, with no agent engine at all,
produced nothing and said nothing about why.

The stage takes no `ReviewContext`: it has no findings, no report and no
validation to accumulate. What it needs is a run, a revision and a checkout.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from codeatlas.core.logging import get_logger
from codeatlas.db.tables import FileRow
from codeatlas.models.overview import ProjectOverview
from codeatlas.pipeline.artifacts_out import publish_artifact
from codeatlas.pipeline.deps import PipelineDeps

log = get_logger("codeatlas.pipeline.narrate")


@dataclass(frozen=True, slots=True)
class NarrationResult:
    """What the node hands back. `sha256` is None when nothing was produced."""

    sha256: str | None = None
    dropped: int = 0
    notes: list[str] = field(default_factory=list)


def narrate_project(
    deps: PipelineDeps,
    *,
    run_id: str,
    revision_sha: str,
    checkout: Path,
    repository_id: str,
    revision_db_id: int,
    project_overview_sha: str,
) -> NarrationResult:
    """Narrate the project, then delete every claim the overview does not support."""
    from codeatlas.pipeline.source import mirror_path
    from codeatlas.project.narrative import build_project_index, explain_project

    overview = ProjectOverview.model_validate(json.loads(deps.cas.get(project_overview_sha)))

    mirror = mirror_path(deps, repository_id)
    with Session(deps.engine) as session:
        rows = session.scalars(select(FileRow).where(FileRow.revision_id == revision_db_id)).all()
        blobs = {row.path: row.git_blob_sha for row in rows}

    index = build_project_index(overview, paths=set(blobs))

    def read_lines(path: str) -> int:
        blob_sha = blobs.get(path)
        if blob_sha is None:
            raise FileNotFoundError(path)
        return len(deps.git.cat_file(mirror, blob_sha).decode("utf-8", "replace").splitlines())

    explanation, dropped = explain_project(
        engine=deps.agent_engine,  # type: ignore[arg-type]
        registry=deps.registry(),
        run_id=run_id,
        revision_sha=revision_sha,
        checkout=checkout,
        db_engine=deps.engine,
        cas=deps.cas,
        overview=overview,
        index=index,
        budget=deps.budget,
        read_lines=read_lines,
    )
    if explanation is None:
        return NarrationResult(
            notes=["project explanation unavailable: the explainer did not complete"]
        )

    sha = publish_artifact(
        deps,
        run_id,
        "project-explanation",
        explanation.contract_dump(),
        schema_id="project-explanation.v1",
        producer="project-explainer",
    )
    notes = []
    if dropped:
        notes.append(
            f"{len(dropped)} project explanation claim(s) removed: their citations did "
            "not resolve against the deterministic overview"
        )
    log.info(
        "narrate.explained",
        run_id=run_id,
        claims=explanation.claim_count,
        dropped=len(dropped),
    )
    return NarrationResult(sha256=sha, dropped=len(dropped), notes=notes)
