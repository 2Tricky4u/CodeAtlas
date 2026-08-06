"""Run/resume entry points shared by the CLI and tests."""

from __future__ import annotations

import contextlib
from pathlib import Path

from sqlalchemy.orm import Session

from codeatlas.db import repositories as repo
from codeatlas.pipeline.deps import PipelineDeps
from codeatlas.pipeline.graph import build_pipeline


def start_run(
    deps: PipelineDeps,
    repo_path: Path | str,
    repository_id: str,
    ref: str = "HEAD",
    base_ref: str | None = None,
    pr_number: int | None = None,
) -> str:
    """Create the run row and execute the pipeline. Returns the run id.

    `repo_path` may be a local repository or a clone URL; both are mirrored
    first and resolved from the mirror. Passing `base_ref` makes this a
    pull-request run: both revisions are analyzed, findings are scoped to what
    the change introduced, and the run can say what the code did before.
    """
    from codeatlas.pipeline.source import prepare_source

    source = str(repo_path)
    prepared = prepare_source(deps, source, repository_id, ref)
    head_sha = prepared.head_sha
    with Session(deps.engine) as session:
        repository = repo.ensure_repository(
            session,
            repository_id=repository_id,
            provider=prepared.provider,
            remote_url=prepared.remote_url or source,
        )
        revision = repo.ensure_revision(session, repository_id=repository.id, sha=head_sha)
        run_row = repo.create_run(
            session,
            repository_id=repository.id,
            kind="pr" if base_ref else "repository",
            head_revision_id=revision.id,
            pr_number=pr_number,
        )
        session.commit()
        run_id = run_row.id

    initial: dict[str, object] = {
        "run_id": run_id,
        "repository_id": repository_id,
        "repo_path": str(repo_path),
        "ref": ref,
    }
    if base_ref:
        initial["base_ref"] = base_ref
    if pr_number is not None:
        initial["pr_number"] = pr_number

    pipeline = build_pipeline(deps)
    config = {"configurable": {"thread_id": run_id}}
    with contextlib.suppress(Exception):  # run status already recorded by the node wrapper
        pipeline.invoke(initial, config=config)
    return run_id


def resume_run(deps: PipelineDeps, run_id: str) -> None:
    """Resume a failed/interrupted run from its last checkpoint."""
    pipeline = build_pipeline(deps)
    config = {"configurable": {"thread_id": run_id}}
    with Session(deps.engine) as session:
        repo.set_run_status(session, run_id=run_id, status="running")
        repo.add_run_event(session, run_id=run_id, stage="pipeline", event="resumed")
        session.commit()
    pipeline.invoke(None, config=config)


def run_status(deps: PipelineDeps, run_id: str) -> str:
    with Session(deps.engine) as session:
        run_row = repo.get_run(session, run_id)
        if run_row is None:
            raise ValueError(f"unknown run {run_id}")
        return run_row.status
