"""The ask endpoint's worker: cached answer, or dispatch and validate.

Separated from `main.py` so the read-only routes never import agent machinery —
a server started without `--ask` cannot even reach this module.
"""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from codeatlas.core.logging import get_logger
from codeatlas.db import repositories as repo
from codeatlas.db.tables import FileRow
from codeatlas.models.graph import ProjectGraph
from codeatlas.pipeline.artifacts_out import publish_artifact
from codeatlas.pipeline.deps import PipelineDeps
from codeatlas.project.answers import (
    answer_question,
    answer_role,
    build_answer_index,
)

log = get_logger("codeatlas.api.ask")


def answer_or_cached(
    deps: PipelineDeps,
    *,
    run_id: str,
    revision_sha: str,
    revision_db_id: int,
    repository_id: str,
    scope: str,
    question: str,
) -> dict[str, object]:
    """Serve the cached answer if this exact question was asked before."""
    role = answer_role(revision_sha, scope, question)

    with Session(deps.engine) as session:
        cached = repo.artifact_for_run(session, run_id, role)
    if cached is not None:
        payload = json.loads(deps.cas.get(cached))
        payload["cached"] = True
        return payload  # type: ignore[no-any-return]

    from codeatlas.pipeline.source import mirror_path

    graph_sha = _graph_sha(deps, run_id)
    graph = ProjectGraph.model_validate(json.loads(deps.cas.get(graph_sha)))
    with Session(deps.engine) as session:
        paths = set(
            session.scalars(select(FileRow.path).where(FileRow.revision_id == revision_db_id))
        )
    index = build_answer_index(graph, scope, paths)

    mirror = mirror_path(deps, repository_id)
    checkout = deps.checkouts / revision_sha
    deps.git.ensure_checkout(mirror, revision_sha, checkout)

    answer, _dropped = answer_question(
        engine=deps.agent_engine,  # type: ignore[arg-type]
        registry=deps.registry(),
        run_id=run_id,
        revision_sha=revision_sha,
        checkout=checkout,
        db_engine=deps.engine,
        cas=deps.cas,
        scope=scope,
        question=question,
        index=index,
        budget=deps.budget,
    )
    if answer is None:
        return {
            "question": question,
            "scope": scope,
            "answer": None,
            "claims": [],
            "refused": "the answerer did not complete; nothing was produced",
            "cached": False,
        }

    payload = answer.contract_dump()
    publish_artifact(
        deps, run_id, role, payload, schema_id="code-answer.v1", producer="code-answerer"
    )
    log.info("ask.answered", run_id=run_id, scope=scope, refused=answer.refused is not None)
    payload["cached"] = False
    return payload


def _graph_sha(deps: PipelineDeps, run_id: str) -> str:
    with Session(deps.engine) as session:
        sha = repo.artifact_for_run(session, run_id, "project-graph")
    if sha is None:
        raise RuntimeError(f"run {run_id} has no project graph to answer against")
    return sha
