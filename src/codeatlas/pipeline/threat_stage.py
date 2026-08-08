"""The threat stage: model what the system is, cache it, aim the reviewers.

Runs first inside the review node because its focus paths are a reviewer
input — a threat model computed after the reviewers would aim nobody. It is
the one agent artifact cached **per repository** rather than per revision:
what a system is, attack-surface-wise, changes far more slowly than its code,
and re-deriving it every run would spend agent budget re-learning a fact.

The cache row is replaceable (`--refresh-threat-model`), the opposite trade
from `graph_cache` — a graph is a deterministic function of named producers, a
threat model is the current understanding. Reuse and refresh are both recorded
as run events, because an invisible cache is one nobody can check.

Everything here fails open: a modeler that does not complete leaves a note and
the reviewers run unaimed, exactly as they did before this stage existed. The
model's own notes stay in the artifact rather than being copied to the run
report — the threats tab serves them; the report gets the operational facts.
"""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from codeatlas.core.logging import get_logger
from codeatlas.db import repositories as repo
from codeatlas.db.tables import FileRow, ThreatModelCacheRow
from codeatlas.models.threat import ThreatModel
from codeatlas.pipeline.deps import PipelineDeps

log = get_logger("codeatlas.pipeline.threat")


def stage_threat_model(
    deps: PipelineDeps,
    ctx: object,
    *,
    repository_id: str,
    revision_db_id: int,
    project_overview_sha: str,
) -> None:
    """Reuse the repository's threat model or build one; either way, say which.

    `ctx` is the ReviewContext (typed loosely to avoid an import cycle with
    review_stages). On success `ctx.threat_model` holds the validated model and
    the run owns a `threat-model` artifact; on failure `ctx.notes` says so.
    """
    from codeatlas.pipeline.review_stages import ReviewContext

    assert isinstance(ctx, ReviewContext)

    with Session(deps.engine) as session:
        row = session.scalar(
            select(ThreatModelCacheRow).where(ThreatModelCacheRow.repository_id == repository_id)
        )
        cached = (
            (row.artifact_sha256, row.modeled_at_revision, row.produced_by_run_id)
            if row is not None
            else None
        )

    if cached is not None and not deps.refresh_threat_model:
        sha, modeled_at, produced_by = cached
        try:
            model = ThreatModel.model_validate(json.loads(deps.cas.get(sha)))
        except Exception as exc:
            # A cache pointing at content this store cannot produce fails open
            # into a rebuild — the pointer is stale, not the run.
            log.warning("threat.cache_unreadable", repository_id=repository_id, error=str(exc))
            ctx.notes.append("threat model cache was unreadable; rebuilding")
        else:
            ctx.adopt(deps, "threat-model", sha)
            with Session(deps.engine) as session:
                repo.add_run_event(
                    session,
                    run_id=ctx.run_id,
                    stage="review",
                    event="threat_model_cache_hit",
                    data={
                        "artifact": sha,
                        "modeledAtRevision": modeled_at,
                        "producedByRunId": produced_by,
                    },
                )
                session.commit()
            ctx.notes.append(f"threat model reused: modeled at revision {modeled_at[:12]}")
            ctx.threat_model = model
            log.info("threat.cache_hit", run_id=ctx.run_id, artifact=sha)
            return

    _build(
        deps,
        ctx,
        repository_id=repository_id,
        revision_db_id=revision_db_id,
        project_overview_sha=project_overview_sha,
        refreshing=cached is not None and deps.refresh_threat_model,
    )


def _build(
    deps: PipelineDeps,
    ctx: object,
    *,
    repository_id: str,
    revision_db_id: int,
    project_overview_sha: str,
    refreshing: bool,
) -> None:
    from codeatlas.models.overview import ProjectOverview
    from codeatlas.pipeline.review_stages import ReviewContext
    from codeatlas.pipeline.source import mirror_path
    from codeatlas.project.threat import build_threat_index, model_threats

    assert isinstance(ctx, ReviewContext)
    overview = ProjectOverview.model_validate(json.loads(deps.cas.get(project_overview_sha)))

    mirror = mirror_path(deps, repository_id)
    with Session(deps.engine) as session:
        rows = session.scalars(select(FileRow).where(FileRow.revision_id == revision_db_id)).all()
        blobs = {row.path: row.git_blob_sha for row in rows}

    index = build_threat_index(ctx.graph, paths=set(blobs))

    def read_lines(path: str) -> int:
        blob_sha = blobs.get(path)
        if blob_sha is None:
            raise FileNotFoundError(path)
        return len(deps.git.cat_file(mirror, blob_sha).decode("utf-8", "replace").splitlines())

    try:
        model, dropped = model_threats(
            engine=deps.agent_engine,  # type: ignore[arg-type]
            registry=deps.registry(),
            run_id=ctx.run_id,
            revision_sha=ctx.revision_sha,
            checkout=ctx.checkout,
            db_engine=deps.engine,
            cas=deps.cas,
            graph=ctx.graph,
            overview=overview,
            index=index,
            budget=deps.budget,
            read_lines=read_lines,
        )
    except Exception as exc:
        # Fail open: the reviewers run unaimed, exactly as before this stage.
        log.error("threat.stage_failed", run_id=ctx.run_id, error=str(exc))
        ctx.notes.append(f"threat model unavailable: {exc}")
        return
    if model is None:
        ctx.notes.append("threat model unavailable: the modeler did not complete")
        return

    sha = ctx.publish(
        deps,
        "threat-model",
        model.contract_dump(),
        schema_id="threat-model.v1",
        producer="threat-modeler",
    )
    ctx.threat_model = model

    if dropped:
        ctx.notes.append(
            f"{len(dropped)} threat-model element(s) removed: their evidence did not "
            "resolve against this revision"
        )
    if not model.threats:
        ctx.notes.append("threat model: no meaningful attack surface recorded")

    # Remember only after the artifact is indexed (ctx.publish did), never
    # before: the cache points at an artifact row, and remembering content the
    # artifact table does not know about would leave a dangling reference.
    with Session(deps.engine) as session:
        row = session.scalar(
            select(ThreatModelCacheRow).where(ThreatModelCacheRow.repository_id == repository_id)
        )
        if row is None:
            session.add(
                ThreatModelCacheRow(
                    repository_id=repository_id,
                    artifact_sha256=sha,
                    modeled_at_revision=ctx.revision_sha,
                    produced_by_run_id=ctx.run_id,
                )
            )
        elif refreshing:
            superseded = row.artifact_sha256
            row.artifact_sha256 = sha
            row.modeled_at_revision = ctx.revision_sha
            row.produced_by_run_id = ctx.run_id
            repo.add_run_event(
                session,
                run_id=ctx.run_id,
                stage="review",
                event="threat_model_refreshed",
                data={"superseded": superseded, "artifact": sha},
            )
        # else: another run raced us here since the lookup; leave its row —
        # this run's membership row already records what it used.
        session.commit()

    log.info(
        "threat.modelled",
        run_id=ctx.run_id,
        threats=len(model.threats),
        focusPaths=len(model.focus_paths),
        dropped=len(dropped),
        refreshed=refreshing,
    )
