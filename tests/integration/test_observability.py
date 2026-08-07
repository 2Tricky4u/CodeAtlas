"""Run snapshots and comparison against the real store (M15). Marker: pg."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from codeatlas.observability.compare import compare_runs
from codeatlas.observability.snapshot import load_snapshot

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


def _seed(  # type: ignore[no-untyped-def]
    db_engine,
    sha: str,
    graph_hash: str,
    findings: list[tuple[str, bool]],
    status_overrides: dict[str, str] | None = None,
) -> str:
    """A run with a graph snapshot, receipts, findings and an agent invocation."""
    from codeatlas.core.ids import new_task_id
    from codeatlas.db import repositories as repo
    from codeatlas.db.tables import (
        AgentInvocationRow,
        ArtifactRow,
        FindingRow,
        GraphSnapshotRow,
    )
    from codeatlas.models.receipts import ExtractorReceipt

    with Session(db_engine) as s:
        repository = repo.ensure_repository(s, repository_id="local/kvstore", provider="local")
        revision = repo.ensure_revision(s, repository_id=repository.id, sha=sha)
        run = repo.create_run(
            s, repository_id=repository.id, kind="repository", head_revision_id=revision.id
        )
        run.skill_registry_sha256 = "sha256:" + "5" * 64
        repo.record_receipt(
            s,
            run_id=run.id,
            receipt=ExtractorReceipt(
                extractor="cargo-metadata",
                extractor_version="cargo 1.94.1",
                revision=sha,
                configuration={"command": "cargo metadata"},
                started_at="2026-08-05T12:00:00Z",
                completed_at="2026-08-05T12:00:01Z",
                exit_code=0,
                stdout_sha256="sha256:" + "0" * 64,
                stderr_sha256="sha256:" + "0" * 64,
            ),
        )
        artifact_sha = "sha256:" + "a" * 64
        if s.get(ArtifactRow, artifact_sha) is None:
            repo.index_artifact(
                s,
                sha256=artifact_sha,
                kind="project-graph",
                media_type="application/json",
                size_bytes=1,
                producer="test",
            )
        s.add(
            GraphSnapshotRow(
                run_id=run.id,
                revision_id=revision.id,
                schema_version="1.0.0",
                canonical_sha256=graph_hash,
                artifact_sha256=artifact_sha,
                node_count=10,
                edge_count=5,
            )
        )
        for finding_id, eligible in findings:
            status = (status_overrides or {}).get(
                finding_id, "validated" if eligible else "unresolved"
            )
            s.add(
                FindingRow(
                    run_id=run.id,
                    finding_id=finding_id,
                    category="correctness",
                    severity="high",
                    confidence=0.9,
                    claim="c",
                    path="a.rs",
                    status=status,
                    discovered_by_skill="reviewer-correctness",
                    skill_version="1.0.0",
                    publication_eligible=eligible,
                    payload={},
                )
            )
        s.add(
            AgentInvocationRow(
                run_id=run.id,
                task_id=new_task_id(),
                skill_id="reviewer-correctness",
                skill_version="1.0.0",
                engine="replay",
                status="succeeded",
                prompt_tokens=100,
                completion_tokens=50,
                duration_ms=10,
            )
        )
        s.commit()
        return run.id


class TestSnapshot:
    def test_snapshot_gathers_everything_needed_to_compare(self, db_engine) -> None:  # type: ignore[no-untyped-def]
        run_id = _seed(
            db_engine, "a" * 40, "sha256:" + "1" * 64, [("F-0001", True), ("F-0002", False)]
        )
        with Session(db_engine) as s:
            snapshot = load_snapshot(s, run_id)
        assert snapshot is not None
        assert snapshot.revision_sha == "a" * 40
        assert snapshot.graph_sha256 == "sha256:" + "1" * 64
        assert snapshot.toolchain == {"cargo-metadata": "cargo 1.94.1"}
        assert snapshot.finding_ids == ["F-0001", "F-0002"]
        assert snapshot.publishable_ids == ["F-0001"]
        assert snapshot.total_tokens == 150

    def test_unknown_run_returns_none(self, db_engine) -> None:  # type: ignore[no-untyped-def]
        with Session(db_engine) as s:
            assert load_snapshot(s, "01AAAAAAAAAAAAAAAAAAAAAAAA") is None


class TestMemoryFolding:
    """ADR-0016: run 2 suppresses what run 1 rejected — same verdict, cheaper
    path. The snapshot folds `suppressed` into `rejected` so the ADR-0007
    reproducibility promise survives the memory being useful."""

    def test_a_suppressed_second_run_compares_reproducible(self, db_engine) -> None:  # type: ignore[no-untyped-def]
        sha, graph = "c" * 40, "sha256:" + "3" * 64
        first = _seed(
            db_engine, sha, graph, [("F-0001", False)], status_overrides={"F-0001": "rejected"}
        )
        second = _seed(
            db_engine, sha, graph, [("F-0001", False)], status_overrides={"F-0001": "suppressed"}
        )
        with Session(db_engine) as s:
            left, right = load_snapshot(s, first), load_snapshot(s, second)
        assert left and right
        assert left.statuses == right.statuses == {"rejected": 1}
        assert left.suppressed_count == 0
        assert right.suppressed_count == 1
        result = compare_runs(left, right)
        assert result.reproducible is True, result.differences
        assert any("memory" in note.lower() for note in result.notes)


class TestComparison:
    def test_two_equivalent_runs_compare_as_reproducible(self, db_engine) -> None:  # type: ignore[no-untyped-def]
        findings = [("F-0001", True)]
        first = _seed(db_engine, "b" * 40, "sha256:" + "2" * 64, findings)
        second = _seed(db_engine, "b" * 40, "sha256:" + "2" * 64, findings)
        with Session(db_engine) as s:
            left, right = load_snapshot(s, first), load_snapshot(s, second)
        assert left and right
        result = compare_runs(left, right)
        assert result.reproducible is True, result.differences

    def test_a_different_graph_hash_is_caught(self, db_engine) -> None:  # type: ignore[no-untyped-def]
        findings = [("F-0001", True)]
        first = _seed(db_engine, "c" * 40, "sha256:" + "3" * 64, findings)
        second = _seed(db_engine, "c" * 40, "sha256:" + "4" * 64, findings)
        with Session(db_engine) as s:
            left, right = load_snapshot(s, first), load_snapshot(s, second)
        assert left and right
        result = compare_runs(left, right)
        assert result.reproducible is False
        assert "graph" in result.differences[0].lower()
