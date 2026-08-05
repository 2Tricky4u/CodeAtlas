"""End-to-end approval flow through the CLI (M12). Marker: pg.

Exercises the sequence a human actually performs: inspect the exact payload,
decide, and only then publish — plus the paths where that sequence is violated.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from codeatlas.artifacts.store import ArtifactStore
from codeatlas.cli.main import app
from codeatlas.publication.gate import request_approval
from codeatlas.publication.payload import ReviewComment, ReviewPayload

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


@pytest.fixture()
def pending(db_engine, tmp_path):  # type: ignore[no-untyped-def]
    """(approval_id, workdir) for a payload awaiting a decision."""
    from codeatlas.db import repositories as repo

    workdir = tmp_path / "wd"
    cas = ArtifactStore(workdir / "objects")
    with Session(db_engine) as s:
        repository = repo.ensure_repository(s, repository_id="o/r", provider="github")
        revision = repo.ensure_revision(s, repository_id=repository.id, sha="e" * 40)
        run = repo.create_run(
            s,
            repository_id=repository.id,
            kind="pr",
            head_revision_id=revision.id,
            pr_number=12,
        )
        s.commit()
        run_id = run.id
    payload = ReviewPayload(
        owner="o",
        repo="r",
        pr_number=12,
        commit_sha="e" * 40,
        body="## CodeAtlas review\n\n1 finding with deterministic evidence",
        comments=[
            ReviewComment(
                path="kvstore/src/api.rs",
                line=28,
                body="**HIGH · correctness** (`F-0001`)\n\nPanics on malformed input.",
            )
        ],
    )
    with Session(db_engine) as s:
        approval = request_approval(s, run_id=run_id, payload=payload, cas=cas)
        s.commit()
        approval_id = approval.id
    return approval_id, workdir, run_id


def _run(args: list[str], workdir) -> object:  # type: ignore[no-untyped-def]
    return CliRunner().invoke(app, [*args, "--workdir", str(workdir), "--test-db"])


class TestInspection:
    def test_show_approval_prints_the_exact_payload(self, pending) -> None:  # type: ignore[no-untyped-def]
        approval_id, workdir, _ = pending
        result = _run(["show-approval", str(approval_id)], workdir)
        assert result.exit_code == 0, result.output
        assert "PENDING" in result.output
        assert "o/r PR #12" in result.output
        assert "kvstore/src/api.rs:28" in result.output
        assert "Panics on malformed input." in result.output

    def test_show_unknown_approval_fails_clearly(self, pending) -> None:  # type: ignore[no-untyped-def]
        _, workdir, _ = pending
        result = _run(["show-approval", "999999"], workdir)
        assert result.exit_code == 1


class TestDecisions:
    def test_approve_records_who_and_does_not_publish_by_default(self, pending, db_engine) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.db.tables import ApprovalRow, PublicationRow

        approval_id, workdir, _ = pending
        result = _run(["approve", str(approval_id), "--by", "xaga"], workdir)
        assert result.exit_code == 0, result.output
        assert "not published" in result.output

        with Session(db_engine) as s:
            approval = s.get(ApprovalRow, approval_id)
            assert approval is not None
            assert approval.decision == "approved"
            assert approval.decided_by == "xaga"
            assert approval.decided_at is not None
            assert (
                s.scalar(select(PublicationRow).where(PublicationRow.approval_id == approval_id))
                is None
            ), "approving must not post anything on its own"

    def test_reject_is_recorded_and_final(self, pending, db_engine) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.db.tables import ApprovalRow

        approval_id, workdir, _ = pending
        assert _run(["reject", str(approval_id), "--by", "xaga"], workdir).exit_code == 0  # type: ignore[union-attr]

        with Session(db_engine) as s:
            approval = s.get(ApprovalRow, approval_id)
            assert approval is not None and approval.decision == "rejected"

        # A decided approval cannot be flipped afterwards.
        second = _run(["approve", str(approval_id), "--by", "someone-else"], workdir)
        assert second.exit_code == 1  # type: ignore[union-attr]
        with Session(db_engine) as s:
            approval = s.get(ApprovalRow, approval_id)
            assert approval is not None and approval.decision == "rejected"

    def test_double_approval_is_refused(self, pending) -> None:  # type: ignore[no-untyped-def]
        approval_id, workdir, _ = pending
        assert _run(["approve", str(approval_id), "--by", "a"], workdir).exit_code == 0  # type: ignore[union-attr]
        assert _run(["approve", str(approval_id), "--by", "b"], workdir).exit_code == 1  # type: ignore[union-attr]


class TestRunStatus:
    def test_requesting_approval_pauses_the_run(self, pending, db_engine) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.db.tables import RunRow

        _, _, run_id = pending
        with Session(db_engine) as s:
            run = s.get(RunRow, run_id)
            assert run is not None
            assert run.status == "paused_for_approval"
