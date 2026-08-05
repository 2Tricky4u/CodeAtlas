"""Run/resume entry points shared by the CLI and tests."""

from __future__ import annotations

import contextlib
from pathlib import Path

from sqlalchemy.orm import Session

from codeatlas.db import repositories as repo
from codeatlas.pipeline.deps import PipelineDeps
from codeatlas.pipeline.graph import build_pipeline


def start_run(deps: PipelineDeps, repo_path: Path, repository_id: str, ref: str = "HEAD") -> str:
    """Create the run row and execute the pipeline. Returns the run id."""
    head_sha = deps.git.resolve_sha(repo_path, ref)
    with Session(deps.engine) as session:
        repository = repo.ensure_repository(
            session, repository_id=repository_id, provider="local", remote_url=str(repo_path)
        )
        revision = repo.ensure_revision(session, repository_id=repository.id, sha=head_sha)
        run_row = repo.create_run(
            session,
            repository_id=repository.id,
            kind="repository",
            head_revision_id=revision.id,
        )
        session.commit()
        run_id = run_row.id

    pipeline = build_pipeline(deps)
    config = {"configurable": {"thread_id": run_id}}
    with contextlib.suppress(Exception):  # run status already recorded by the node wrapper
        pipeline.invoke(
            {
                "run_id": run_id,
                "repository_id": repository_id,
                "repo_path": str(repo_path),
                "ref": ref,
            },
            config=config,
        )
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
