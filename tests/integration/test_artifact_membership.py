"""Repeat runs must not lose their artifacts to content-addressed dedup. Marker: pg.

Regression found by running the same pull request twice: artifacts are shared
when their content is identical (that is the point of the store), so attributing
one to a single `produced_by_run_id` made the second run look as though it had
produced nothing. `GET /api/runs/{id}/graph` returned 404 for a graph that
plainly existed. Membership is a relation.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

pytestmark = pytest.mark.pg


@pytest.fixture(scope="module")
def db_engine():  # type: ignore[no-untyped-def]
    from codeatlas.db.migrate import downgrade_base, upgrade_head
    from codeatlas.db.session import app_engine, migrator_engine, test_db_available

    if not test_db_available():
        pytest.skip("codeatlas_test PostgreSQL database not reachable")
    mig = migrator_engine(test=True)
    downgrade_base(mig)
    upgrade_head(mig)
    mig.dispose()
    engine = app_engine(test=True)
    yield engine
    engine.dispose()


def _run(session, sha: str = "a" * 40) -> str:  # type: ignore[no-untyped-def]
    from codeatlas.db import repositories as repo

    repository = repo.ensure_repository(session, repository_id="o/r", provider="github")
    revision = repo.ensure_revision(session, repository_id=repository.id, sha=sha)
    run = repo.create_run(
        session, repository_id=repository.id, kind="repository", head_revision_id=revision.id
    )
    session.flush()
    return run.id


IDENTICAL = "sha256:" + "c" * 64


def test_two_runs_producing_identical_content_both_own_it(db_engine) -> None:  # type: ignore[no-untyped-def]
    from codeatlas.db.repositories import artifact_for_run, index_artifact

    with Session(db_engine) as s:
        first = _run(s)
        second = _run(s)
        for run_id in (first, second):
            index_artifact(
                s,
                sha256=IDENTICAL,
                kind="cytoscape-elements",
                media_type="application/json",
                size_bytes=10,
                producer="pipeline",
                produced_by_run_id=run_id,
            )
        s.commit()

        assert artifact_for_run(s, first, "cytoscape-elements") == IDENTICAL
        assert artifact_for_run(s, second, "cytoscape-elements") == IDENTICAL, (
            "the second run must own the shared artifact too"
        )


def test_the_artifact_row_itself_is_still_deduplicated(db_engine) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy import func, select

    from codeatlas.db.repositories import index_artifact
    from codeatlas.db.tables import ArtifactRow

    sha = "sha256:" + "d" * 64
    with Session(db_engine) as s:
        for _ in range(3):
            run_id = _run(s)
            index_artifact(
                s,
                sha256=sha,
                kind="project-graph",
                media_type="application/json",
                size_bytes=10,
                producer="pipeline",
                produced_by_run_id=run_id,
            )
        s.commit()
        count = s.scalar(
            select(func.count()).select_from(ArtifactRow).where(ArtifactRow.sha256 == sha)
        )
        assert count == 1, "content-addressed storage must still store one row"


def test_membership_is_idempotent_within_a_run(db_engine) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy import func, select

    from codeatlas.db.repositories import index_artifact
    from codeatlas.db.tables import RunArtifactRow

    sha = "sha256:" + "e" * 64
    with Session(db_engine) as s:
        run_id = _run(s)
        for _ in range(3):
            index_artifact(
                s,
                sha256=sha,
                kind="run-manifest",
                media_type="application/json",
                size_bytes=10,
                producer="pipeline",
                produced_by_run_id=run_id,
            )
        s.commit()
        count = s.scalar(
            select(func.count())
            .select_from(RunArtifactRow)
            .where(RunArtifactRow.run_id == run_id, RunArtifactRow.sha256 == sha)
        )
        assert count == 1


def test_unknown_role_returns_none(db_engine) -> None:  # type: ignore[no-untyped-def]
    from codeatlas.db.repositories import artifact_for_run

    with Session(db_engine) as s:
        run_id = _run(s)
        s.commit()
        assert artifact_for_run(s, run_id, "nonexistent-role") is None
