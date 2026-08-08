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
    from codeatlas.publication.payload import PROVENANCE

    payload = ReviewPayload(
        owner="o",
        repo="r",
        pr_number=12,
        commit_sha="e" * 40,
        body=f"## CodeAtlas review\n\n1 finding with deterministic evidence\n\n{PROVENANCE}",
        comments=[
            ReviewComment(
                path="kvstore/src/api.rs",
                line=28,
                body=(
                    "**HIGH · correctness** (`F-0001`)\n\n"
                    f"Panics on malformed input.\n\n{PROVENANCE}"
                ),
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


def _prefix(db_engine, approval_id: int) -> str:  # type: ignore[no-untyped-def]
    """The proof-of-reading string: first 12 chars of the payload sha."""
    from codeatlas.db.tables import ApprovalRow

    with Session(db_engine) as s:
        approval = s.get(ApprovalRow, approval_id)
        assert approval is not None
        return approval.payload_sha256.removeprefix("sha256:")[:12]


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


class TestProofOfReading:
    """You cannot approve a payload you have not at least fetched: the flag
    value only exists in `show-approval` output or the dashboard."""

    def test_approve_without_the_payload_prefix_is_refused(self, pending, db_engine) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.db.tables import ApprovalRow

        approval_id, workdir, _ = pending
        result = _run(["approve", str(approval_id), "--by", "xaga"], workdir)
        assert result.exit_code == 1, result.output
        assert "show-approval" in result.output
        with Session(db_engine) as s:
            approval = s.get(ApprovalRow, approval_id)
            assert approval is not None and approval.decision is None

    def test_a_wrong_prefix_is_refused_without_leaking_the_right_one(
        self, pending, db_engine
    ) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.db.tables import ApprovalRow

        approval_id, workdir, _ = pending
        right = _prefix(db_engine, approval_id)
        result = _run(
            ["approve", str(approval_id), "--by", "xaga", "--payload", "000000000000"], workdir
        )
        assert result.exit_code == 1, result.output
        assert right not in result.output
        with Session(db_engine) as s:
            approval = s.get(ApprovalRow, approval_id)
            assert approval is not None and approval.decision is None


class TestDecisions:
    def test_approve_records_who_and_does_not_publish_by_default(self, pending, db_engine) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.db.tables import ApprovalRow, PublicationRow

        approval_id, workdir, _ = pending
        result = _run(
            [
                "approve",
                str(approval_id),
                "--by",
                "xaga",
                "--payload",
                _prefix(db_engine, approval_id),
            ],
            workdir,
        )
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

        # A decided approval cannot be flipped afterwards — even with the
        # correct proof-of-reading prefix.
        second = _run(
            [
                "approve",
                str(approval_id),
                "--by",
                "someone-else",
                "--payload",
                _prefix(db_engine, approval_id),
            ],
            workdir,
        )
        assert second.exit_code == 1  # type: ignore[union-attr]
        with Session(db_engine) as s:
            approval = s.get(ApprovalRow, approval_id)
            assert approval is not None and approval.decision == "rejected"

    def test_double_approval_is_refused(self, pending, db_engine) -> None:  # type: ignore[no-untyped-def]
        approval_id, workdir, _ = pending
        prefix = _prefix(db_engine, approval_id)
        first = _run(["approve", str(approval_id), "--by", "a", "--payload", prefix], workdir)
        assert first.exit_code == 0  # type: ignore[union-attr]
        second = _run(["approve", str(approval_id), "--by", "b", "--payload", prefix], workdir)
        assert second.exit_code == 1  # type: ignore[union-attr]


class TestRunStatus:
    def test_requesting_approval_pauses_the_run(self, pending, db_engine) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.db.tables import RunRow

        _, _, run_id = pending
        with Session(db_engine) as s:
            run = s.get(RunRow, run_id)
            assert run is not None
            assert run.status == "paused_for_approval"


class FakeWriter:
    """Stands in for GitHubWriter; records what the CLI would have posted."""

    def __init__(self, posted: list[ReviewPayload]) -> None:
        self.posted = posted

    def create_review(self, payload: ReviewPayload) -> str:
        self.posted.append(payload)
        return f"https://github.com/o/r/pull/{payload.pr_number}#pullrequestreview-9"


class TestPublishing:
    """The CLI publication path — the only production caller of the gate.

    These run the real commands, not the gate function: the audit found the
    call site hard-coding `enabled=True`, which every gate-level test missed
    because they all passed `enabled=` by hand.
    """

    @pytest.fixture(autouse=True)
    def _github(self, monkeypatch):  # type: ignore[no-untyped-def]
        self.posted: list[ReviewPayload] = []
        posted = self.posted
        monkeypatch.setattr(
            "codeatlas.vcs.github.client.GitHubWriter", lambda token: FakeWriter(posted)
        )
        monkeypatch.setattr("codeatlas.vcs.github.client.token_from_keyring", lambda: "test-token")
        monkeypatch.delenv("CODEATLAS_PUBLISH_ENABLED", raising=False)
        monkeypatch.delenv("CODEATLAS_KILL_SWITCH", raising=False)

    def test_publish_without_the_config_flag_is_blocked(self, pending, db_engine) -> None:  # type: ignore[no-untyped-def]
        approval_id, workdir, _ = pending
        result = _run(
            [
                "approve",
                str(approval_id),
                "--by",
                "xaga",
                "--payload",
                _prefix(db_engine, approval_id),
                "--publish",
            ],
            workdir,
        )
        assert result.exit_code == 1, result.output  # type: ignore[union-attr]
        assert self.posted == [], "the config flag must be able to say no at the CLI"

    def test_kill_switch_blocks_even_with_the_flag_set(
        self, pending, db_engine, monkeypatch
    ) -> None:  # type: ignore[no-untyped-def]
        approval_id, workdir, _ = pending
        monkeypatch.setenv("CODEATLAS_PUBLISH_ENABLED", "1")
        monkeypatch.setenv("CODEATLAS_KILL_SWITCH", "1")
        result = _run(
            [
                "approve",
                str(approval_id),
                "--by",
                "xaga",
                "--payload",
                _prefix(db_engine, approval_id),
                "--publish",
            ],
            workdir,
        )
        assert result.exit_code == 1  # type: ignore[union-attr]
        assert self.posted == []

    def test_flag_plus_approval_posts_through_the_gate(
        self, pending, db_engine, monkeypatch
    ) -> None:  # type: ignore[no-untyped-def]
        approval_id, workdir, _ = pending
        monkeypatch.setenv("CODEATLAS_PUBLISH_ENABLED", "1")
        result = _run(
            [
                "approve",
                str(approval_id),
                "--by",
                "xaga",
                "--payload",
                _prefix(db_engine, approval_id),
                "--publish",
            ],
            workdir,
        )
        assert result.exit_code == 0, result.output  # type: ignore[union-attr]
        assert "published:" in result.output  # type: ignore[union-attr]
        assert len(self.posted) == 1

    def test_publish_command_posts_an_already_approved_payload(
        self, pending, db_engine, monkeypatch
    ) -> None:  # type: ignore[no-untyped-def]
        # The two-step flow the approve hint promises: approve now, publish later.
        approval_id, workdir, _ = pending
        monkeypatch.setenv("CODEATLAS_PUBLISH_ENABLED", "1")
        approve = _run(
            [
                "approve",
                str(approval_id),
                "--by",
                "xaga",
                "--payload",
                _prefix(db_engine, approval_id),
            ],
            workdir,
        )
        assert approve.exit_code == 0  # type: ignore[union-attr]
        assert self.posted == []
        result = _run(["publish", str(approval_id)], workdir)
        assert result.exit_code == 0, result.output  # type: ignore[union-attr]
        assert len(self.posted) == 1

    def test_the_not_published_hint_names_a_command_that_exists(self, pending, db_engine) -> None:  # type: ignore[no-untyped-def]
        approval_id, workdir, _ = pending
        result = _run(
            [
                "approve",
                str(approval_id),
                "--by",
                "xaga",
                "--payload",
                _prefix(db_engine, approval_id),
            ],
            workdir,
        )
        assert "codeatlas publish" in result.output  # type: ignore[union-attr]
        helped = CliRunner().invoke(app, ["publish", "--help"])
        assert helped.exit_code == 0, "the hint points at a command that does not exist"
