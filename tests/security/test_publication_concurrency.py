"""Exactly-once under concurrency: two publishers, one post.

The exactly-once guard is a check-then-act — SELECT for a published row, then
INSERT and post. Two processes racing through it is the precise scenario the
guard exists for, and a sequential test cannot catch the interleaving. The fix
is a row lock on the approval (serialising publishers) plus a partial unique
index as the database-level backstop.
"""

from __future__ import annotations

import threading
import time

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from codeatlas.artifacts.store import ArtifactStore
from codeatlas.db.tables import PublicationRow
from codeatlas.publication.gate import (
    decide_approval,
    publish_approved,
    request_approval,
)
from codeatlas.publication.payload import ReviewComment, ReviewPayload

pytestmark = pytest.mark.pg


class SlowGitHub:
    """Records posts; slow enough that a racing publisher can catch up."""

    def __init__(self) -> None:
        self.posted: list[ReviewPayload] = []
        self._lock = threading.Lock()

    def create_review(self, payload: ReviewPayload) -> str:
        # Long enough for the second thread to pass the (unlocked) check
        # before the first commits — the window the guard must close.
        time.sleep(0.3)
        with self._lock:
            self.posted.append(payload)
        return f"https://github.com/o/r/pull/{payload.pr_number}#review-{len(self.posted)}"


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


def test_two_racing_publishers_post_exactly_once(db_engine, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from codeatlas.db import repositories as repo

    cas = ArtifactStore(tmp_path / "objects")
    with Session(db_engine) as s:
        repository = repo.ensure_repository(s, repository_id="o/r", provider="github")
        revision = repo.ensure_revision(s, repository_id=repository.id, sha="d" * 40)
        run = repo.create_run(
            s, repository_id=repository.id, kind="pr", head_revision_id=revision.id, pr_number=9
        )
        s.commit()
        run_id = run.id
    payload = ReviewPayload(
        owner="o",
        repo="r",
        pr_number=9,
        commit_sha="d" * 40,
        body="review",
        comments=[ReviewComment(path="src/a.rs", line=3, body="F-0001")],
    )
    with Session(db_engine) as s:
        approval = request_approval(s, run_id=run_id, payload=payload, cas=cas)
        decide_approval(s, approval_id=approval.id, decision="approved", decided_by="me")
        s.commit()
        approval_id = approval.id

    github = SlowGitHub()
    barrier = threading.Barrier(2, timeout=10)
    outcomes: list[object] = []

    def publisher() -> None:
        barrier.wait()
        try:
            with Session(db_engine) as s:
                record = publish_approved(
                    s, approval_id=approval_id, github=github, cas=cas, enabled=True
                )
                s.commit()
                outcomes.append(record)
        except Exception as exc:  # the exception *is* the outcome under test
            outcomes.append(exc)

    threads = [threading.Thread(target=publisher) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert len(github.posted) == 1, "an approved payload must reach GitHub exactly once"

    # Both callers got an answer, and neither invented a second publication:
    # the loser either received the winner's record or a typed refusal.
    assert len(outcomes) == 2
    with Session(db_engine) as s:
        published = s.scalars(
            select(PublicationRow).where(
                PublicationRow.approval_id == approval_id,
                PublicationRow.status == "published",
            )
        ).all()
        assert len(published) == 1
