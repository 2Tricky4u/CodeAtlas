"""codeatlas CLI: run, resume, status."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

from codeatlas.core.logging import configure_logging

if TYPE_CHECKING:
    from codeatlas.pipeline.deps import PipelineDeps

app = typer.Typer(name="codeatlas", no_args_is_help=True, pretty_exceptions_enable=False)

_DEFAULT_WORKDIR = Path("var")


def _deps(workdir: Path, test_db: bool) -> PipelineDeps:
    from codeatlas.artifacts.store import ArtifactStore
    from codeatlas.db.session import app_engine
    from codeatlas.pipeline.deps import PipelineDeps

    return PipelineDeps(
        engine=app_engine(test=test_db),
        workdir=workdir,
        cas=ArtifactStore(workdir / "objects"),
        checkpoint_path=workdir / "checkpoints" / "pipeline.sqlite",
    )


@app.command()
def run(
    repo: Annotated[Path, typer.Option(exists=True, help="Path to the git repository")],
    repository_id: Annotated[str, typer.Option(help="Stable repository id, e.g. local/kvstore")],
    ref: Annotated[str, typer.Option(help="Ref or SHA to analyze")] = "HEAD",
    workdir: Annotated[
        Path, typer.Option(help="Working directory for mirrors/artifacts")
    ] = _DEFAULT_WORKDIR,
    test_db: Annotated[bool, typer.Option(hidden=True)] = False,
) -> None:
    """Analyze a repository at a pinned revision."""
    configure_logging()
    from codeatlas.pipeline.runner import run_status, start_run

    deps = _deps(workdir, test_db)
    run_id = start_run(deps, repo_path=repo, repository_id=repository_id, ref=ref)
    status = run_status(deps, run_id)
    typer.echo(f"run {run_id} {status}")
    raise typer.Exit(0 if status in ("succeeded", "succeeded_with_gaps") else 1)


@app.command()
def resume(
    run_id: str,
    workdir: Annotated[Path, typer.Option()] = _DEFAULT_WORKDIR,
    test_db: Annotated[bool, typer.Option(hidden=True)] = False,
) -> None:
    """Resume a failed or interrupted run from its last checkpoint."""
    configure_logging()
    from codeatlas.pipeline.runner import resume_run, run_status

    deps = _deps(workdir, test_db)
    try:
        resume_run(deps, run_id)
    except Exception as exc:
        typer.echo(f"resume error: {exc}", err=True)
    status = run_status(deps, run_id)
    typer.echo(f"run {run_id} {status}")
    raise typer.Exit(0 if status in ("succeeded", "succeeded_with_gaps") else 1)


@app.command()
def status(
    run_id: str,
    workdir: Annotated[Path, typer.Option()] = _DEFAULT_WORKDIR,
    test_db: Annotated[bool, typer.Option(hidden=True)] = False,
) -> None:
    """Print a run's status."""
    from codeatlas.pipeline.runner import run_status

    deps = _deps(workdir, test_db)
    typer.echo(run_status(deps, run_id))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
