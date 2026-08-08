"""The publication gate: nothing reaches the outside world without approval.

Every test here is an attempted bypass. Control flow alone is not the gate — the
publish path re-checks the approval decision in the database, the config flag,
and the kill switch, and scans the payload for secrets, on every call.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from codeatlas.artifacts.store import ArtifactStore
from codeatlas.publication.gate import (
    PublicationBlocked,
    decide_approval,
    publish_approved,
    request_approval,
)
from codeatlas.publication.payload import ReviewComment, ReviewPayload, scan_for_secrets

pytestmark = pytest.mark.pg


class FakeGitHub:
    """Records what would have been posted; never touches the network."""

    def __init__(self, fail: bool = False) -> None:
        self.posted: list[ReviewPayload] = []
        self.fail = fail

    def create_review(self, payload: ReviewPayload) -> str:
        if self.fail:
            raise RuntimeError("github said no")
        self.posted.append(payload)
        return f"https://github.com/o/r/pull/{payload.pr_number}#pullrequestreview-1"


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
def context(db_engine, tmp_path):  # type: ignore[no-untyped-def]
    """(session-maker, run_id, cas, payload) with an approval already requested."""
    from codeatlas.db import repositories as repo

    cas = ArtifactStore(tmp_path / "objects")
    with Session(db_engine) as s:
        repository = repo.ensure_repository(s, repository_id="o/r", provider="github")
        revision = repo.ensure_revision(s, repository_id=repository.id, sha="c" * 40)
        run = repo.create_run(
            s,
            repository_id=repository.id,
            kind="pr",
            head_revision_id=revision.id,
            pr_number=7,
        )
        s.commit()
        run_id = run.id
    # Marker included: these tests exercise the gate's order, not provenance —
    # the builder always adds it, and only the dedicated test omits it.
    from codeatlas.publication.payload import PROVENANCE

    payload = ReviewPayload(
        owner="o",
        repo="r",
        pr_number=7,
        commit_sha="c" * 40,
        body=f"CodeAtlas review\n\n{PROVENANCE}",
        comments=[
            ReviewComment(
                path="src/a.rs",
                line=10,
                body=f"finding F-0001: something is wrong\n\n{PROVENANCE}",
            )
        ],
    )
    return db_engine, run_id, cas, payload


def _request(context) -> int:  # type: ignore[no-untyped-def]
    db_engine, run_id, cas, payload = context
    with Session(db_engine) as s:
        approval = request_approval(s, run_id=run_id, payload=payload, cas=cas)
        s.commit()
        return approval.id


class TestApprovalRequired:
    def test_pending_approval_cannot_publish(self, context) -> None:  # type: ignore[no-untyped-def]
        db_engine, _, cas, _ = context
        approval_id = _request(context)
        github = FakeGitHub()
        with Session(db_engine) as s, pytest.raises(PublicationBlocked, match="not approved"):
            publish_approved(s, approval_id=approval_id, github=github, cas=cas, enabled=True)
        assert github.posted == []

    def test_rejected_approval_cannot_publish(self, context) -> None:  # type: ignore[no-untyped-def]
        db_engine, _, cas, _ = context
        approval_id = _request(context)
        github = FakeGitHub()
        with Session(db_engine) as s:
            decide_approval(s, approval_id=approval_id, decision="rejected", decided_by="me")
            s.commit()
        with Session(db_engine) as s, pytest.raises(PublicationBlocked, match="not approved"):
            publish_approved(s, approval_id=approval_id, github=github, cas=cas, enabled=True)
        assert github.posted == []

    def test_unknown_approval_cannot_publish(self, context) -> None:  # type: ignore[no-untyped-def]
        db_engine, _, cas, _ = context
        github = FakeGitHub()
        with Session(db_engine) as s, pytest.raises(PublicationBlocked):
            publish_approved(s, approval_id=999_999, github=github, cas=cas, enabled=True)
        assert github.posted == []

    def test_approved_publishes_once(self, context) -> None:  # type: ignore[no-untyped-def]
        db_engine, _run_id, cas, _ = context
        approval_id = _request(context)
        github = FakeGitHub()
        with Session(db_engine) as s:
            decide_approval(s, approval_id=approval_id, decision="approved", decided_by="me")
            s.commit()
        with Session(db_engine) as s:
            publication = publish_approved(
                s, approval_id=approval_id, github=github, cas=cas, enabled=True
            )
            s.commit()
        assert len(github.posted) == 1
        assert publication.external_ref is not None
        assert publication.status == "published"


class TestKillSwitchAndConfig:
    def test_disabled_publication_blocks_even_when_approved(self, context) -> None:  # type: ignore[no-untyped-def]
        db_engine, _, cas, _ = context
        approval_id = _request(context)
        github = FakeGitHub()
        with Session(db_engine) as s:
            decide_approval(s, approval_id=approval_id, decision="approved", decided_by="me")
            s.commit()
        with Session(db_engine) as s, pytest.raises(PublicationBlocked, match="disabled"):
            publish_approved(s, approval_id=approval_id, github=github, cas=cas, enabled=False)
        assert github.posted == []

    def test_kill_switch_blocks_even_when_approved_and_enabled(self, context, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        db_engine, _, cas, _ = context
        approval_id = _request(context)
        github = FakeGitHub()
        monkeypatch.setenv("CODEATLAS_KILL_SWITCH", "1")
        with Session(db_engine) as s:
            decide_approval(s, approval_id=approval_id, decision="approved", decided_by="me")
            s.commit()
        with Session(db_engine) as s, pytest.raises(PublicationBlocked, match="kill switch"):
            publish_approved(s, approval_id=approval_id, github=github, cas=cas, enabled=True)
        assert github.posted == []


class TestIdempotency:
    def test_second_publish_does_not_post_again(self, context) -> None:  # type: ignore[no-untyped-def]
        db_engine, _, cas, _ = context
        approval_id = _request(context)
        github = FakeGitHub()
        with Session(db_engine) as s:
            decide_approval(s, approval_id=approval_id, decision="approved", decided_by="me")
            s.commit()
        with Session(db_engine) as s:
            first = publish_approved(
                s, approval_id=approval_id, github=github, cas=cas, enabled=True
            )
            s.commit()
            first_ref = first.external_ref
        with Session(db_engine) as s:
            second = publish_approved(
                s, approval_id=approval_id, github=github, cas=cas, enabled=True
            )
            s.commit()
        assert len(github.posted) == 1, "an approved payload must be posted exactly once"
        assert second.external_ref == first_ref

    def test_failed_publish_is_recorded_and_does_not_claim_success(self, context) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.db.tables import PublicationRow

        db_engine, _, cas, _ = context
        approval_id = _request(context)
        github = FakeGitHub(fail=True)
        with Session(db_engine) as s:
            decide_approval(s, approval_id=approval_id, decision="approved", decided_by="me")
            s.commit()
        with Session(db_engine) as s, pytest.raises(PublicationBlocked, match="github"):
            publish_approved(s, approval_id=approval_id, github=github, cas=cas, enabled=True)
        with Session(db_engine) as s:
            row = s.scalar(select(PublicationRow).where(PublicationRow.approval_id == approval_id))
            assert row is not None
            assert row.status == "failed"
            assert row.external_ref is None


class TestGateOrder:
    def test_kill_switch_outranks_the_already_published_short_circuit(
        self, context, monkeypatch
    ) -> None:  # type: ignore[no-untyped-def]
        """The kill switch means stop — even the idempotent "already published"
        return is answered with a refusal while it is set. Fail closed: no path
        through this function ignores the switch."""
        db_engine, _, cas, _ = context
        approval_id = _request(context)
        github = FakeGitHub()
        with Session(db_engine) as s:
            decide_approval(s, approval_id=approval_id, decision="approved", decided_by="me")
            s.commit()
        with Session(db_engine) as s:
            publish_approved(s, approval_id=approval_id, github=github, cas=cas, enabled=True)
            s.commit()
        assert len(github.posted) == 1

        monkeypatch.setenv("CODEATLAS_KILL_SWITCH", "1")
        with Session(db_engine) as s, pytest.raises(PublicationBlocked, match="kill switch"):
            publish_approved(s, approval_id=approval_id, github=github, cas=cas, enabled=True)
        assert len(github.posted) == 1


class TestSecretScanning:
    def test_payload_containing_a_token_is_refused(self, context) -> None:  # type: ignore[no-untyped-def]
        db_engine, run_id, cas, _ = context
        leaky = ReviewPayload(
            owner="o",
            repo="r",
            pr_number=7,
            commit_sha="c" * 40,
            body="review",
            comments=[
                ReviewComment(
                    path="src/a.rs",
                    line=1,
                    body="found a hardcoded token: "
                    "github_pat_11QK9mX2pT7vN4rW8zB3cD"
                    "_5fG0hJkR6sL1yU9aE4iO7qM2xC8nV5bZ3tP0wS6dH1jF9gK4lA7rT2uY5mB",
                )
            ],
        )
        github = FakeGitHub()
        with Session(db_engine) as s:
            approval = request_approval(s, run_id=run_id, payload=leaky, cas=cas)
            decide_approval(s, approval_id=approval.id, decision="approved", decided_by="me")
            s.commit()
            approval_id = approval.id
        with Session(db_engine) as s, pytest.raises(PublicationBlocked, match="secret"):
            publish_approved(s, approval_id=approval_id, github=github, cas=cas, enabled=True)
        assert github.posted == []

    def test_a_payload_without_the_provenance_marker_is_refused(self, context) -> None:  # type: ignore[no-untyped-def]
        """The builder always adds the marker; only a hand-built or tampered
        payload lacks it — and the gate is exactly where tampering must die."""
        db_engine, run_id, cas, _ = context
        unmarked = ReviewPayload(
            owner="o",
            repo="r",
            pr_number=7,
            commit_sha="c" * 40,
            body="review with no provenance",
            comments=[ReviewComment(path="src/a.rs", line=1, body="a bare comment")],
        )
        github = FakeGitHub()
        with Session(db_engine) as s:
            approval = request_approval(s, run_id=run_id, payload=unmarked, cas=cas)
            decide_approval(s, approval_id=approval.id, decision="approved", decided_by="me")
            s.commit()
            approval_id = approval.id
        with Session(db_engine) as s, pytest.raises(PublicationBlocked, match="provenance"):
            publish_approved(s, approval_id=approval_id, github=github, cas=cas, enabled=True)
        assert github.posted == []

    def test_scanner_finds_known_secret_shapes(self) -> None:
        assert scan_for_secrets("sk-ant-api03-x7K2mQ9pL4vN8rT3wY6zB1cD5fG0hJkMnPqR")
        assert scan_for_secrets("postgresql://user:hunter2secret@localhost/db")
        assert scan_for_secrets("ghp_x7K2mQ9pL4vN8rT3wY6zB1cD5fG0hJkMnPqR")

    def test_scanner_does_not_flag_ordinary_review_prose(self) -> None:
        assert scan_for_secrets("FileStore::read joins an untrusted key onto the root") == []
        assert scan_for_secrets("see postgresql://localhost/codeatlas for the dev database") == []
