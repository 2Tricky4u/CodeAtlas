"""PostgreSQL evidence-store integration tests (pg marker).

Runs against the local codeatlas_test database. Each test runs inside a
transaction that is rolled back. Migration tests use their own schema lifecycle:
upgrade head -> downgrade base -> upgrade head must all succeed on the test DB.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from codeatlas.models.graph import (
    Evidence,
    GraphEdge,
    GraphNode,
    ProjectGraph,
    RepositoryRef,
    RevisionRef,
)
from codeatlas.models.receipts import ExtractorReceipt

pytestmark = pytest.mark.pg

SHA = "d" * 40
DET = Evidence(kind="build-system", producer="cargo", confidence=1.0)


@pytest.fixture(scope="module")
def migrated_engine():  # type: ignore[no-untyped-def]
    from codeatlas.db.migrate import downgrade_base, upgrade_head
    from codeatlas.db.session import migrator_engine, test_db_available

    if not test_db_available():
        pytest.skip("codeatlas_test PostgreSQL database not reachable")
    engine = migrator_engine(test=True)
    downgrade_base(engine)
    upgrade_head(engine)
    # exercise the full down/up cycle once per module
    downgrade_base(engine)
    upgrade_head(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def session(migrated_engine):  # type: ignore[no-untyped-def]
    from sqlalchemy.orm import Session

    with migrated_engine.connect() as conn:
        tx = conn.begin()
        s = Session(bind=conn)
        yield s
        s.close()
        if tx.is_active:
            tx.rollback()


def _mk_run(session):  # type: ignore[no-untyped-def]
    from codeatlas.db.repositories import create_run, ensure_repository, ensure_revision

    repo = ensure_repository(session, repository_id="local/kvstore", provider="local")
    rev = ensure_revision(session, repository_id=repo.id, sha=SHA)
    return create_run(session, repository_id=repo.id, kind="repository", head_revision_id=rev.id)


class TestRunPersistence:
    def test_run_round_trip_with_events_and_receipt(self, session) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.db.repositories import (
            add_run_event,
            get_run,
            record_receipt,
            set_run_status,
        )

        run = _mk_run(session)
        assert len(run.id) == 26

        add_run_event(session, run_id=run.id, stage="source_lock", event="started")
        add_run_event(session, run_id=run.id, stage="source_lock", event="finished")

        receipt = ExtractorReceipt(
            extractor="cargo-metadata",
            extractor_version="cargo 1.94.1",
            revision=SHA,
            configuration={"command": "cargo metadata"},
            started_at="2026-08-05T12:00:00Z",
            completed_at="2026-08-05T12:00:01Z",
            exit_code=0,
            stdout_sha256="sha256:" + "0" * 64,
            stderr_sha256="sha256:" + "0" * 64,
        )
        record_receipt(session, run_id=run.id, receipt=receipt)
        set_run_status(session, run_id=run.id, status="succeeded")
        session.flush()

        loaded = get_run(session, run.id)
        assert loaded is not None
        assert loaded.status == "succeeded"
        assert len(loaded.events) == 2
        assert loaded.receipts[0].extractor == "cargo-metadata"
        assert loaded.receipts[0].payload["exitCode"] == 0

    def test_unknown_status_rejected(self, session) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.db.repositories import set_run_status

        run = _mk_run(session)
        with pytest.raises(ValueError):
            set_run_status(session, run_id=run.id, status="not-a-status")


class TestGraphPersistence:
    def test_snapshot_projection_round_trip(self, session) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.db.repositories import (
            index_artifact,
            load_graph_snapshot,
            store_graph_snapshot,
        )
        from codeatlas.db.tables import GraphNodeRow

        run = _mk_run(session)
        index_artifact(
            session,
            sha256="sha256:" + "a" * 64,
            kind="project-graph",
            media_type="application/json",
            size_bytes=1,
            producer="test",
            produced_by_run_id=run.id,
        )
        graph = ProjectGraph(
            repository=RepositoryRef(id="local/kvstore"),
            revision=RevisionRef(head=SHA),
            nodes=[
                GraphNode(id="pkg:cargo/a@1", kind="package", label="a 1", evidence=[DET]),
                GraphNode(id="pkg:cargo/b@1", kind="package", label="b 1", evidence=[DET]),
            ],
            edges=[
                GraphEdge(
                    id="edge:x",
                    source="pkg:cargo/a@1",
                    target="pkg:cargo/b@1",
                    kind="depends-on",
                    evidence=[DET],
                )
            ],
        )
        snapshot = store_graph_snapshot(
            session,
            run_id=run.id,
            revision_id=run.head_revision_id,
            graph=graph,
            artifact_sha256="sha256:" + "a" * 64,
        )
        assert snapshot.node_count == 2
        assert snapshot.edge_count == 1
        assert snapshot.canonical_sha256.startswith("sha256:")

        node_count = session.scalar(
            select(func.count())
            .select_from(GraphNodeRow)
            .where(GraphNodeRow.snapshot_id == snapshot.id)
        )
        assert node_count == 2

        reloaded = load_graph_snapshot(session, snapshot.id)
        assert reloaded is not None
        edges = reloaded.edges
        assert edges[0].source_natural_id == "pkg:cargo/a@1"


class TestArtifactIndex:
    def test_artifact_index_dedupes_by_sha(self, session) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.db.repositories import index_artifact

        run = _mk_run(session)
        a1 = index_artifact(
            session,
            sha256="sha256:" + "b" * 64,
            kind="project-graph",
            media_type="application/json",
            size_bytes=10,
            producer="pipeline",
            produced_by_run_id=run.id,
        )
        a2 = index_artifact(
            session,
            sha256="sha256:" + "b" * 64,
            kind="project-graph",
            media_type="application/json",
            size_bytes=10,
            producer="pipeline",
            produced_by_run_id=run.id,
        )
        assert a1.sha256 == a2.sha256
