"""Independently validate two-revision analysis against a real GitHub pull request.

Every integration this exercises is one the fixture suite cannot: an
authenticated mirror of a private repository, a pull-request head that is not on
any mirrored branch, a base ref resolved from the same mirror, and the graph
cache surviving a second run in a different working directory.

Runs the deterministic half only — no agent engine, no quota, nothing published.

    python scripts/validate_two_revisions.py owner/repo PR_NUMBER
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from codeatlas.artifacts.store import ArtifactStore
from codeatlas.core.logging import configure_logging
from codeatlas.db.repositories import artifact_for_run
from codeatlas.db.session import app_engine
from codeatlas.db.tables import GraphSnapshotRow, RevisionRow, RunEventRow, RunRow
from codeatlas.pipeline.deps import PipelineDeps
from codeatlas.pipeline.runner import run_status, start_run
from codeatlas.vcs.git import force_remove
from codeatlas.vcs.github.client import GitHubReader, token_from_keyring

WORKDIR = Path("var") / "validate-two-revisions"


def _deps(engine, workdir: Path, token: str) -> PipelineDeps:  # type: ignore[no-untyped-def]
    deps = PipelineDeps(
        engine=engine,
        workdir=workdir,
        cas=ArtifactStore(Path("var") / "objects"),  # shared: the cache points at content
        checkpoint_path=workdir / "checkpoints" / "pipeline.sqlite",
    )
    deps.git.github_token = token
    return deps


def _snapshots(session: Session, run_id: str) -> dict[str, GraphSnapshotRow]:
    rows = session.scalars(select(GraphSnapshotRow).where(GraphSnapshotRow.run_id == run_id)).all()
    return {row.role: row for row in rows}


def main() -> int:
    if len(sys.argv) != 3 or "/" not in sys.argv[1]:
        print(__doc__)
        return 2
    owner, repo_name = sys.argv[1].split("/", 1)
    pr_number = int(sys.argv[2])
    slug = f"{owner}/{repo_name}"

    configure_logging()
    token = token_from_keyring()
    pr = GitHubReader(token).pull_request(owner, repo_name, pr_number)
    print(f"PR #{pr.number}: {pr.title}")
    print(f"  base {pr.base_sha[:12]} -> head {pr.head_sha[:12]}")
    print(f"  {len(pr.changed_paths)} changed file(s)\n")

    engine = app_engine(test=False)
    clone_url = f"https://github.com/{slug}.git"
    failures: list[str] = []

    results = []
    for attempt, suffix in enumerate(("first", "second"), start=1):
        workdir = WORKDIR / suffix
        if workdir.exists():
            # Pinned checkouts are read-only on purpose; a plain rmtree leaves
            # half a mirror behind, which is precisely the state that used to
            # read as a healthy repository.
            force_remove(workdir)
        deps = _deps(engine, workdir, token)
        print(f"--- run {attempt} ({suffix}, fresh working directory) ---")
        run_id = start_run(
            deps,
            repo_path=clone_url,
            repository_id=slug,
            ref=pr.head_sha,
            base_ref=pr.base_sha,
            pr_number=pr_number,
        )
        status = run_status(deps, run_id)
        print(f"run {run_id} {status}")
        if not status.startswith("succeeded"):
            failures.append(f"run {attempt} status {status}")

        with Session(engine) as s:
            run = s.get(RunRow, run_id)
            assert run is not None
            base_rev = s.get(RevisionRow, run.base_revision_id) if run.base_revision_id else None
            head_rev = s.get(RevisionRow, run.head_revision_id)
            snaps = _snapshots(s, run_id)
            cache_hit = s.scalar(
                select(RunEventRow).where(
                    RunEventRow.run_id == run_id,
                    RunEventRow.event == "base_graph_cache_hit",
                )
            )
            head_artifact = artifact_for_run(s, run_id, "project-graph")
            base_artifact = artifact_for_run(s, run_id, "project-graph-base")

        print(f"  kind={run.kind} pr={run.pr_number}")
        print(f"  head revision {head_rev.sha[:12] if head_rev else '-'}")
        print(f"  base revision {base_rev.sha[:12] if base_rev else '-'}")
        for role in ("head", "base"):
            snap = snaps.get(role)
            if snap is None:
                failures.append(f"run {attempt}: no {role} snapshot")
                continue
            print(
                f"  {role:5} graph {snap.node_count:>5} nodes {snap.edge_count:>5} edges "
                f"{snap.canonical_sha256[7:19]}"
            )
        print(f"  base graph cache hit: {'yes' if cache_hit else 'no'}\n")

        if run.kind != "pr":
            failures.append(f"run {attempt}: kind is {run.kind!r}, expected 'pr'")
        if base_rev is None or base_rev.sha != pr.base_sha:
            failures.append(f"run {attempt}: base revision not pinned to the PR base")
        if head_artifact == base_artifact:
            failures.append(f"run {attempt}: head and base graphs are the same artifact")
        results.append(
            {
                "run_id": run_id,
                "head": snaps["head"].canonical_sha256 if "head" in snaps else None,
                "base": snaps["base"].canonical_sha256 if "base" in snaps else None,
                "cache_hit": cache_hit is not None,
            }
        )

    first, second = results
    print("--- cross-run checks ---")
    if first["head"] != second["head"]:
        failures.append("head graph is not reproducible across runs")
    if first["base"] != second["base"]:
        failures.append("base graph is not reproducible across runs")
    if first["cache_hit"]:
        failures.append("the first run reported a cache hit on a cold cache")
    if not second["cache_hit"]:
        failures.append("the second run re-extracted a base it had already analyzed")
    print(f"  head reproducible: {first['head'] == second['head']}")
    print(f"  base reproducible: {first['base'] == second['base']}")
    print(f"  cache: run 1 hit={first['cache_hit']}, run 2 hit={second['cache_hit']}")

    print()
    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        return 1
    print("all two-revision checks passed against the live pull request")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
