"""Invariants that make one run holding two graphs safe (P1). Marker: pg.

These are cheap DB-level checks for the rules the two-revision pipeline relies
on. `test_two_revisions.py` proves the pipeline produces both graphs; this file
proves the storage layer cannot quietly lose or confuse them.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from codeatlas.models.graph import (
    Evidence,
    GraphNode,
    ProjectGraph,
    RepositoryRef,
    RevisionRef,
)

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


def _graph(sha: str, label: str = "kvstore") -> ProjectGraph:
    evidence = Evidence(kind="build-system", producer="cargo", confidence=1.0)
    return ProjectGraph(
        repository=RepositoryRef(id="o/r"),
        revision=RevisionRef(head=sha),
        nodes=[
            GraphNode(
                id=f"pkg:cargo/{label}@1.0.0", kind="package", label=label, evidence=[evidence]
            )
        ],
        edges=[],
    )


def _fixture_run(session: Session) -> tuple[str, int, int]:
    """A run with two revisions to hang snapshots off. Returns (run_id, base, head)."""
    from codeatlas.core.ids import new_run_id
    from codeatlas.db import repositories as repo

    unique = new_run_id()
    repository = repo.ensure_repository(session, repository_id=f"o/{unique}", provider="github")
    base = repo.ensure_revision(session, repository_id=repository.id, sha="b" * 40)
    head = repo.ensure_revision(session, repository_id=repository.id, sha="a" * 40)
    run = repo.create_run(
        session,
        repository_id=repository.id,
        kind="pr",
        head_revision_id=head.id,
        base_revision_id=base.id,
        pr_number=1,
    )
    session.flush()
    return run.id, base.id, head.id


def _artifact(session: Session, run_id: str, sha: str, role: str) -> None:
    from codeatlas.db.repositories import index_artifact

    index_artifact(
        session,
        sha256=sha,
        kind="project-graph",
        media_type="application/json",
        size_bytes=1,
        producer="pipeline",
        produced_by_run_id=run_id,
        role=role,
    )


class TestIndexArtifactRole:
    def test_one_run_can_hold_two_artifacts_of_the_same_kind(self, db_engine) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.db.repositories import artifact_for_run

        head_sha, base_sha = "sha256:" + "1" * 64, "sha256:" + "2" * 64
        with Session(db_engine) as s:
            run_id, _, _ = _fixture_run(s)
            _artifact(s, run_id, head_sha, "project-graph")
            _artifact(s, run_id, base_sha, "project-graph-base")
            s.commit()

            assert artifact_for_run(s, run_id, "project-graph") == head_sha
            assert artifact_for_run(s, run_id, "project-graph-base") == base_sha

    def test_role_defaults_to_kind_so_existing_callers_are_unaffected(self, db_engine) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.db.repositories import artifact_for_run, index_artifact

        sha = "sha256:" + "3" * 64
        with Session(db_engine) as s:
            run_id, _, _ = _fixture_run(s)
            index_artifact(
                s,
                sha256=sha,
                kind="cytoscape-elements",
                media_type="application/json",
                size_bytes=1,
                producer="pipeline",
                produced_by_run_id=run_id,
            )
            s.commit()
            assert artifact_for_run(s, run_id, "cytoscape-elements") == sha


class TestSnapshotRoles:
    def test_base_and_head_snapshots_coexist_and_are_fetched_by_role(self, db_engine) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.db.repositories import graph_snapshot_for_run, store_graph_snapshot

        head_art, base_art = "sha256:" + "4" * 64, "sha256:" + "5" * 64
        with Session(db_engine) as s:
            run_id, base_id, head_id = _fixture_run(s)
            _artifact(s, run_id, head_art, "project-graph")
            _artifact(s, run_id, base_art, "project-graph-base")
            store_graph_snapshot(
                s, run_id, head_id, _graph("a" * 40, "after"), head_art, role="head"
            )
            store_graph_snapshot(
                s, run_id, base_id, _graph("b" * 40, "before"), base_art, role="base"
            )
            s.commit()

            head = graph_snapshot_for_run(s, run_id, "head")
            base = graph_snapshot_for_run(s, run_id, "base")
        assert head is not None and base is not None
        assert head.revision_id == head_id and base.revision_id == base_id
        assert head.canonical_sha256 != base.canonical_sha256

    def test_restoring_the_identical_graph_is_a_no_op(self, db_engine) -> None:  # type: ignore[no-untyped-def]
        """A resumed run reaches the stage twice; the second visit changes nothing."""
        from sqlalchemy import func, select

        from codeatlas.db.repositories import store_graph_snapshot
        from codeatlas.db.tables import GraphNodeRow, GraphSnapshotRow

        artifact = "sha256:" + "6" * 64
        with Session(db_engine) as s:
            run_id, _, head_id = _fixture_run(s)
            _artifact(s, run_id, artifact, "project-graph")
            graph = _graph("a" * 40)
            first = store_graph_snapshot(s, run_id, head_id, graph, artifact)
            second = store_graph_snapshot(s, run_id, head_id, graph, artifact)
            s.commit()

            assert first.id == second.id
            snapshots = s.scalar(
                select(func.count())
                .select_from(GraphSnapshotRow)
                .where(GraphSnapshotRow.run_id == run_id)
            )
            nodes = s.scalar(
                select(func.count())
                .select_from(GraphNodeRow)
                .where(GraphNodeRow.snapshot_id == first.id)
            )
        assert snapshots == 1
        assert nodes == 1, "re-storing must not duplicate the projected rows"

    def test_a_contradicting_graph_for_the_same_role_is_refused(self, db_engine) -> None:  # type: ignore[no-untyped-def]
        """One run cannot have analyzed one revision two different ways."""
        from codeatlas.db.repositories import store_graph_snapshot

        artifact = "sha256:" + "7" * 64
        with Session(db_engine) as s:
            run_id, _, head_id = _fixture_run(s)
            _artifact(s, run_id, artifact, "project-graph")
            store_graph_snapshot(s, run_id, head_id, _graph("a" * 40, "one"), artifact)
            with pytest.raises(ValueError, match="already has a different head graph"):
                store_graph_snapshot(s, run_id, head_id, _graph("a" * 40, "another"), artifact)
            s.rollback()
