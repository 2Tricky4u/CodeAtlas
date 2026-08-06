"""Narrate an already-analyzed run: project-explainer over its stored overview.

The pipeline runs this stage as part of `review`, which also runs the reviewers,
the validators and the ADR audit. This narrates a run that already exists,
without re-extracting anything and without paying for the rest of the review —
which is what makes it usable for checking the narrative against a real project
rather than a four-module fixture.

Writes are local: the explanation goes into the content store and is indexed as
this run's `project-explanation` artifact, which is what the dashboard reads.

Usage: uv run python scripts/narrate_run.py <run-id> [--workdir var]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument("--workdir", type=Path, default=Path("var"))
    parser.add_argument("--test-db", action="store_true", help="use the codeatlas_test database")
    args = parser.parse_args(argv)

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from codeatlas.agents.claude_engine import ClaudeAgentEngine
    from codeatlas.agents.registry import SkillRegistry
    from codeatlas.artifacts.store import ArtifactStore
    from codeatlas.core.logging import configure_logging
    from codeatlas.db import repositories as repo
    from codeatlas.db.session import app_engine
    from codeatlas.db.tables import FileRow, RevisionRow, RunRow
    from codeatlas.project.narrative import build_project_index, explain_project
    from codeatlas.vcs.git import GitClient

    configure_logging()
    repo_root = Path(__file__).resolve().parents[1]
    cas = ArtifactStore(args.workdir / "objects")
    db = app_engine(test=args.test_db)

    with Session(db) as session:
        run = session.get(RunRow, args.run_id)
        if run is None:
            print(f"unknown run {args.run_id}", file=sys.stderr)
            return 1
        overview_sha = repo.artifact_for_run(session, args.run_id, "project-overview")
        if overview_sha is None:
            print("this run has no project overview to narrate", file=sys.stderr)
            return 1
        repository_id = run.repository_id
        revision_id = run.head_revision_id
        revision_sha = session.get(RevisionRow, revision_id).sha  # type: ignore[union-attr]
        blobs = {
            row.path: row.git_blob_sha
            for row in session.scalars(select(FileRow).where(FileRow.revision_id == revision_id))
        }

    from codeatlas.models.overview import ProjectOverview

    overview = ProjectOverview.model_validate(json.loads(cas.get(overview_sha)))
    index = build_project_index(overview, paths=set(blobs))

    # Same layout the pipeline uses, so this reuses the checkout the run left
    # behind instead of materialising a second copy of the tree.
    git = GitClient()
    mirror = args.workdir / "mirrors" / (repository_id.replace("/", "_") + ".git")
    checkout = args.workdir / "checkouts" / revision_sha
    git.ensure_checkout(mirror, revision_sha, checkout)

    def read_lines(path: str) -> int:
        blob = blobs.get(path)
        if blob is None:
            raise FileNotFoundError(path)
        return len(git.cat_file(mirror, blob).decode("utf-8", "replace").splitlines())

    engine = ClaudeAgentEngine(cas=cas)
    health = engine.health_check()
    if not health.available:
        print(f"engine unavailable: {health.detail}", file=sys.stderr)
        return 1

    explanation, dropped = explain_project(
        engine=engine,
        registry=SkillRegistry.load(repo_root / ".agents" / "skills"),
        run_id=args.run_id,
        revision_sha=revision_sha,
        checkout=checkout,
        db_engine=db,
        cas=cas,
        overview=overview,
        index=index,
        read_lines=read_lines,
    )
    if explanation is None:
        print("the explainer did not complete", file=sys.stderr)
        return 2

    payload = explanation.contract_dump()
    sha = cas.put_json(payload)
    with Session(db) as session:
        repo.index_artifact(
            session,
            sha256=sha,
            kind="project-explanation",
            media_type="application/json",
            size_bytes=len(json.dumps(payload).encode("utf-8")),
            producer="project-explainer",
            produced_by_run_id=args.run_id,
            schema_id="project-explanation.v1",
        )
        session.commit()

    print(f"\n{explanation.summary}\n")
    for section in explanation.sections:
        print(f"[{section.id}] {section.title}")
        for claim in section.claims:
            print(f"  - {claim.text}")
            for citation in claim.citations:
                print(f"      {citation.contract_dump()}")
    print(f"\nkept {explanation.claim_count} claim(s), dropped {len(dropped)}")
    for drop in dropped:
        print(f"  DROPPED [{drop.section_id}] {drop.text}\n    reason: {drop.reason}")
    print(f"\nindexed as {sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
