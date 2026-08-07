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


def _deps(
    workdir: Path,
    test_db: bool,
    *,
    review: bool = False,
    narrate: bool | None = None,
    replay: bool = False,
    max_tokens: int = 2_000_000,
) -> PipelineDeps:
    """Build the dependency container.

    `narrate` is tri-state on purpose. Unset it follows `--review`, which is
    what the pipeline did when narration lived inside the review — so existing
    invocations behave exactly as before. Set explicitly it is independent, and
    `--narrate` alone gets you a described project with no reviewers run.
    """
    from codeatlas.artifacts.store import ArtifactStore
    from codeatlas.db.session import app_engine
    from codeatlas.pipeline.deps import PipelineDeps

    narration = review if narrate is None else narrate

    cas = ArtifactStore(workdir / "objects")
    agent_engine: object | None = None
    budget = None
    if review or narration:
        from codeatlas.agents.budget import TokenBudget

        if replay:
            from codeatlas.agents.replay_engine import ReplayEngine

            agent_engine = ReplayEngine(Path("tests") / "cassettes")
        else:
            from codeatlas.agents.claude_engine import ClaudeAgentEngine

            # The store is required: agents receive their inputs as content,
            # and without it they would get undereferenceable hashes.
            agent_engine = ClaudeAgentEngine(cas=cas)
        budget = TokenBudget(max_run_tokens=max_tokens, max_task_tokens=400_000)

    return PipelineDeps(
        engine=app_engine(test=test_db),
        workdir=workdir,
        cas=cas,
        checkpoint_path=workdir / "checkpoints" / "pipeline.sqlite",
        agent_engine=agent_engine,
        budget=budget,
        review_enabled=review,
        narration_enabled=narration,
    )


@app.command()
def run(
    repo: Annotated[str, typer.Option(help="Local repository path or clone URL")],
    repository_id: Annotated[str, typer.Option(help="Stable repository id, e.g. local/kvstore")],
    ref: Annotated[str, typer.Option(help="Ref or SHA to analyze")] = "HEAD",
    workdir: Annotated[
        Path, typer.Option(help="Working directory for mirrors/artifacts")
    ] = _DEFAULT_WORKDIR,
    review: Annotated[
        bool, typer.Option(help="Run the agent review stages (costs subscription quota)")
    ] = False,
    narrate: Annotated[
        bool | None,
        typer.Option(help="Explain what this project is. Defaults to following --review."),
    ] = None,
    replay: Annotated[
        bool, typer.Option(help="Use recorded cassettes instead of the live engine")
    ] = False,
    test_db: Annotated[bool, typer.Option(hidden=True)] = False,
) -> None:
    """Analyze a repository at a pinned revision.

    `--repo` takes a local path or anything git can clone. The pipeline has
    always handled both — it mirrors first and resolves from the mirror — but
    this command used to demand an existing directory, so the one thing you
    would try first on a public project failed at argument parsing.

    `--narrate` without `--review` describes the project without reviewing it:
    the two are separate questions and cost very different amounts.
    """
    configure_logging()
    from codeatlas.pipeline.runner import run_status, start_run
    from codeatlas.pipeline.source import is_remote

    if not is_remote(repo):
        local = Path(repo)
        if not local.is_dir():
            typer.echo(f"--repo {repo!r} is neither a directory nor a clone URL", err=True)
            raise typer.Exit(2)
        # Resolved because the mirror clone runs with its own working directory:
        # a relative path passes the check here and then fails to exist there.
        repo = str(local.resolve())

    deps = _deps(workdir, test_db, review=review, narrate=narrate, replay=replay)
    run_id = start_run(deps, repo_path=repo, repository_id=repository_id, ref=ref)
    status = run_status(deps, run_id)
    typer.echo(f"run {run_id} {status}")
    raise typer.Exit(0 if status in ("succeeded", "succeeded_with_gaps") else 1)


@app.command()
def serve(
    workdir: Annotated[Path, typer.Option()] = _DEFAULT_WORKDIR,
    host: Annotated[str, typer.Option()] = "127.0.0.1",
    port: Annotated[int, typer.Option()] = 8000,
    ask: Annotated[
        bool,
        typer.Option(help="Enable POST /ask: cited answers about specific code (costs quota)"),
    ] = False,
    test_db: Annotated[bool, typer.Option(hidden=True)] = False,
) -> None:
    """Serve the API the dashboard reads.

    Bound to loopback by default. Under ADR-0014 the application performs no
    external writes and no approval decisions: approval and publication happen
    through the CLI. `--ask` opts in to the one local-analysis endpoint —
    without it the app is GET-only exactly as before. Serving does expose
    pinned source for every analyzed revision, which is why the default host is
    not 0.0.0.0.
    """
    configure_logging()
    import uvicorn

    from codeatlas.api.main import create_app

    deps = _deps(workdir, test_db)
    ask_deps = _deps(workdir, test_db, review=True) if ask else None
    application = create_app(
        engine=deps.engine, cas=deps.cas, mirrors=deps.mirrors, ask_deps=ask_deps
    )
    mode = "with /ask" if ask else "read-only"
    typer.echo(f"{mode} API on http://{host}:{port}/api  (docs at /api/docs)")
    uvicorn.run(application, host=host, port=port, log_level="info")


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
    try:
        status = run_status(deps, run_id)
    except ValueError as exc:
        # An unknown id already failed above; this keeps the failure typed
        # instead of letting the status lookup re-raise as a traceback.
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
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
    try:
        typer.echo(run_status(deps, run_id))
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc


@app.command("review-pr")
def review_pr(
    slug: Annotated[str, typer.Argument(help="owner/repo")],
    pr_number: Annotated[int, typer.Argument(help="Pull request number")],
    workdir: Annotated[Path, typer.Option()] = _DEFAULT_WORKDIR,
    narrate: Annotated[
        bool, typer.Option(help="Also explain what the project is, not just the change")
    ] = True,
    replay: Annotated[bool, typer.Option(help="Use recorded cassettes")] = False,
    test_db: Annotated[bool, typer.Option(hidden=True)] = False,
) -> None:
    """Review a GitHub pull request in shadow mode — analyze and post NOTHING.

    Fetches the PR, pins base and head SHAs, analyzes *both* revisions, and
    prepares the exact review payload. Publishing it is a separate, explicit act
    (`codeatlas approve --publish`), so this command can never surprise anyone.
    """
    configure_logging()
    from codeatlas.pipeline.runner import run_status, start_run
    from codeatlas.vcs.github.client import GitHubError, GitHubReader, token_from_keyring

    if "/" not in slug:
        typer.echo(f"expected owner/repo, got {slug!r}", err=True)
        raise typer.Exit(2)
    owner, repo_name = slug.split("/", 1)

    try:
        reader = GitHubReader(token_from_keyring())
        pr = reader.pull_request(owner, repo_name, pr_number)
    except GitHubError as exc:
        typer.echo(f"GitHub error: {exc}", err=True)
        raise typer.Exit(1) from exc

    typer.echo(f"PR #{pr.number}: {pr.title}")
    typer.echo(f"  base {pr.base_sha[:12]} -> head {pr.head_sha[:12]}")
    typer.echo(f"  {len(pr.changed_paths)} changed file(s)")

    deps = _deps(workdir, test_db, review=True, narrate=narrate, replay=replay)
    deps.github_owner = owner
    deps.github_repo = repo_name
    deps.pr_number = pr_number
    # Private repositories need an authenticated clone. The token is injected
    # through git's environment config, never written to .git/config.
    deps.git.github_token = token_from_keyring()

    clone_url = f"https://github.com/{owner}/{repo_name}.git"
    run_id = start_run(
        deps,
        repo_path=clone_url,
        repository_id=slug,
        ref=pr.head_sha,
        base_ref=pr.base_sha,
        pr_number=pr_number,
    )
    status = run_status(deps, run_id)
    typer.echo(f"run {run_id} {status}")
    typer.echo("nothing was published; review the payload with `codeatlas show-approval`")
    raise typer.Exit(0 if status.startswith("succeeded") else 1)


@app.command()
def compare(
    left_run: str,
    right_run: str,
    workdir: Annotated[Path, typer.Option()] = _DEFAULT_WORKDIR,
    test_db: Annotated[bool, typer.Option(hidden=True)] = False,
) -> None:
    """Compare two runs. Exits nonzero if they are not reproducible."""
    from sqlalchemy.orm import Session

    from codeatlas.observability.compare import compare_runs
    from codeatlas.observability.snapshot import load_snapshot

    deps = _deps(workdir, test_db)
    with Session(deps.engine) as session:
        left = load_snapshot(session, left_run)
        right = load_snapshot(session, right_run)
    if left is None or right is None:
        missing = left_run if left is None else right_run
        typer.echo(f"unknown run {missing}", err=True)
        raise typer.Exit(2)

    result = compare_runs(left, right)
    if result.reproducible:
        typer.echo(f"REPRODUCIBLE: {result.left} and {result.right} agree")
    else:
        typer.echo(f"NOT REPRODUCIBLE: {result.left} vs {result.right}")
        for difference in result.differences:
            typer.echo(f"  - {difference}")
    for note in result.notes:
        typer.echo(f"  note: {note}")
    raise typer.Exit(0 if result.reproducible else 1)


@app.command("request-approval")
def request_approval_cmd(
    run_id: str,
    workdir: Annotated[Path, typer.Option()] = _DEFAULT_WORKDIR,
    test_db: Annotated[bool, typer.Option(hidden=True)] = False,
) -> None:
    """Open an approval for a completed run's review payload.

    Separated from analysis on purpose: producing a payload and proposing to
    publish it are different acts, and only the second one starts a countdown to
    something leaving the machine.
    """
    configure_logging()
    import json

    from sqlalchemy.orm import Session

    from codeatlas.db.tables import RunRow
    from codeatlas.publication.gate import request_approval
    from codeatlas.publication.payload import ReviewPayload

    deps = _deps(workdir, test_db)
    with Session(deps.engine) as session:
        run = session.get(RunRow, run_id)
        if run is None:
            typer.echo(f"unknown run {run_id}", err=True)
            raise typer.Exit(1)
        from codeatlas.db.repositories import artifact_for_run

        sha = artifact_for_run(session, run_id, "review-payload-dry-run")
        if sha is None:
            typer.echo(
                f"run {run_id} has no review payload; it was not a pull-request review",
                err=True,
            )
            raise typer.Exit(1)
        payload = ReviewPayload.model_validate(json.loads(deps.cas.get(sha)))
        approval = request_approval(session, run_id=run_id, payload=payload, cas=deps.cas)
        session.commit()
        approval_id = approval.id

    typer.echo(f"approval {approval_id} opened for run {run_id}")
    typer.echo(f"  target: {payload.owner}/{payload.repo} PR #{payload.pr_number}")
    typer.echo(f"  inline comments: {len(payload.comments)}")
    typer.echo(f"\nreview it:  uv run codeatlas show-approval {approval_id}")
    typer.echo(f'then:       uv run codeatlas approve {approval_id} --by "<you>" --publish')


@app.command("show-approval")
def show_approval(
    approval_id: int,
    workdir: Annotated[Path, typer.Option()] = _DEFAULT_WORKDIR,
    test_db: Annotated[bool, typer.Option(hidden=True)] = False,
) -> None:
    """Print the exact payload awaiting approval — review this before approving."""
    import json

    from sqlalchemy.orm import Session

    from codeatlas.db.tables import ApprovalRow

    deps = _deps(workdir, test_db)
    with Session(deps.engine) as session:
        approval = session.get(ApprovalRow, approval_id)
        if approval is None:
            typer.echo(f"unknown approval {approval_id}", err=True)
            raise typer.Exit(1)
        payload = json.loads(deps.cas.get(approval.payload_sha256))
        typer.echo(f"approval {approval_id} · run {approval.run_id} · {approval.action_kind}")
        typer.echo(f"decision: {approval.decision or 'PENDING'}")
        typer.echo(f"payload:  {approval.payload_sha256}")
        typer.echo("")
        typer.echo(f"target: {payload['owner']}/{payload['repo']} PR #{payload['prNumber']}")
        typer.echo(f"commit: {payload['commitSha']}")
        typer.echo(f"inline comments: {len(payload['comments'])}")
        typer.echo("")
        typer.echo(payload["body"])
        for comment in payload["comments"]:
            typer.echo(f"\n--- {comment['path']}:{comment['line']} ---\n{comment['body']}")


@app.command()
def approve(
    approval_id: int,
    by: Annotated[str, typer.Option(help="Who is approving (recorded in the audit trail)")],
    note: Annotated[str | None, typer.Option()] = None,
    publish: Annotated[bool, typer.Option(help="Publish immediately after approving")] = False,
    workdir: Annotated[Path, typer.Option()] = _DEFAULT_WORKDIR,
    test_db: Annotated[bool, typer.Option(hidden=True)] = False,
) -> None:
    """Approve a pending payload. Approval decisions are CLI-only by design."""
    configure_logging()
    from sqlalchemy.orm import Session

    from codeatlas.publication.gate import decide_approval

    deps = _deps(workdir, test_db)
    with Session(deps.engine) as session:
        try:
            decide_approval(
                session, approval_id=approval_id, decision="approved", decided_by=by, note=note
            )
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        session.commit()
    typer.echo(f"approval {approval_id} approved by {by}")

    if not publish:
        typer.echo("not published (pass --publish, or run `codeatlas publish`)")
        return

    _publish(deps, approval_id)


def _publish(deps: PipelineDeps, approval_id: int) -> None:
    """The one production path to GitHub. The gate re-checks everything —
    including the config flag, which comes from the environment here, never
    from a literal: a flag hard-coded open is a flag that cannot say no."""
    from sqlalchemy.orm import Session

    from codeatlas.publication.gate import (
        PublicationBlocked,
        publication_enabled,
        publish_approved,
    )
    from codeatlas.vcs.github.client import GitHubWriter, token_from_keyring

    with Session(deps.engine) as session:
        try:
            record = publish_approved(
                session,
                approval_id=approval_id,
                github=GitHubWriter(token_from_keyring()),
                cas=deps.cas,
                enabled=publication_enabled(),
            )
            session.commit()
        except PublicationBlocked as exc:
            typer.echo(f"publication blocked: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"published: {record.external_ref}")


@app.command()
def publish(
    approval_id: int,
    workdir: Annotated[Path, typer.Option()] = _DEFAULT_WORKDIR,
    test_db: Annotated[bool, typer.Option(hidden=True)] = False,
) -> None:
    """Publish an already-approved payload — the second half of the two-step
    flow `approve` suggests. Requires CODEATLAS_PUBLISH_ENABLED=1 and an
    unset kill switch; both are re-checked at post time."""
    configure_logging()
    deps = _deps(workdir, test_db)
    _publish(deps, approval_id)


@app.command()
def reject(
    approval_id: int,
    by: Annotated[str, typer.Option(help="Who is rejecting (recorded in the audit trail)")],
    note: Annotated[str | None, typer.Option()] = None,
    workdir: Annotated[Path, typer.Option()] = _DEFAULT_WORKDIR,
    test_db: Annotated[bool, typer.Option(hidden=True)] = False,
) -> None:
    """Reject a pending payload. It can never be published afterwards."""
    configure_logging()
    from sqlalchemy.orm import Session

    from codeatlas.publication.gate import decide_approval

    deps = _deps(workdir, test_db)
    with Session(deps.engine) as session:
        try:
            decide_approval(
                session, approval_id=approval_id, decision="rejected", decided_by=by, note=note
            )
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        session.commit()
    typer.echo(f"approval {approval_id} rejected by {by}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
