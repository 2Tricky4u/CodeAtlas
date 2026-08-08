"""The M12 live posting test — the only test that writes to GitHub. Markers: pg + github_live.

Runs only when everything is deliberately armed: a PAT in the keyring, a
scratch PR in CODEATLAS_SCRATCH_REPO (seeded by scripts/seed_scratch_pr.py),
and CODEATLAS_PUBLISH_ENABLED=1 in this shell. Anything missing → skip, never
a partial post. The payload is hand-built (no agent cost); the point is the
posting path: request → proof-of-reading approve → publish through the real
CLI and the real gate, then read the review back and prove exactly-once.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from codeatlas.artifacts.store import ArtifactStore
from codeatlas.cli.main import app
from codeatlas.publication.gate import request_approval
from codeatlas.publication.payload import PROVENANCE, ReviewComment, ReviewPayload

pytestmark = [pytest.mark.pg, pytest.mark.github_live, pytest.mark.timeout(300)]

SCRATCH_ENV = "CODEATLAS_SCRATCH_REPO"


def _armed() -> tuple[str, str] | None:
    """(owner, repo) when every safety is deliberately off; None otherwise."""
    slug = os.environ.get(SCRATCH_ENV, "")
    if "/" not in slug:
        return None
    if os.environ.get("CODEATLAS_PUBLISH_ENABLED") != "1":
        return None
    if os.environ.get("CODEATLAS_KILL_SWITCH"):
        return None
    try:
        from codeatlas.vcs.github.client import token_from_keyring

        token_from_keyring()
    except Exception:
        return None
    owner, repo = slug.split("/", 1)
    return owner, repo


@pytest.fixture(scope="module")
def armed() -> tuple[str, str]:
    target = _armed()
    if target is None:
        pytest.skip(
            f"live posting not armed: needs {SCRATCH_ENV}=owner/repo, "
            "CODEATLAS_PUBLISH_ENABLED=1, no kill switch, and a PAT in the keyring"
        )
    return target


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


def test_the_first_real_publication(armed, db_engine, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Request → approve (with proof of reading) → publish → verify → re-publish."""
    from codeatlas.db import repositories as repo
    from codeatlas.db.tables import ApprovalRow, PublicationRow
    from codeatlas.vcs.github.client import GitHubReader, token_from_keyring

    owner, repo_name = armed
    reader = GitHubReader(token_from_keyring())
    pr = reader.pull_request(owner, repo_name, 1)
    assert pr.state == "open", "the scratch PR must be open; re-run seed_scratch_pr.py"

    # The seeded PR adds lines to its known file; anchor the inline comment at
    # the first changed file's first line — the diff is entirely additions.
    anchor_path = pr.changed_paths[0]

    workdir = tmp_path / "wd"
    cas = ArtifactStore(workdir / "objects")
    with Session(db_engine) as s:
        repository = repo.ensure_repository(
            s, repository_id=f"{owner}/{repo_name}", provider="github"
        )
        revision = repo.ensure_revision(s, repository_id=repository.id, sha=pr.head_sha)
        run = repo.create_run(
            s, repository_id=repository.id, kind="pr", head_revision_id=revision.id, pr_number=1
        )
        s.commit()
        run_id = run.id

    payload = ReviewPayload(
        owner=owner,
        repo=repo_name,
        pr_number=1,
        commit_sha=pr.head_sha,
        body=(
            "## CodeAtlas review (live posting test)\n\n"
            "This is M12: the first real publication, against a scratch PR.\n\n"
            f"{PROVENANCE}"
        ),
        comments=[
            ReviewComment(
                path=anchor_path,
                line=1,
                body=f"Anchored inline comment from the live posting test.\n\n{PROVENANCE}",
            )
        ],
    )
    with Session(db_engine) as s:
        approval = request_approval(s, run_id=run_id, payload=payload, cas=cas)
        s.commit()
        approval_id = approval.id
        prefix = approval.payload_sha256.removeprefix("sha256:")[:12]

    runner = CliRunner()

    def cli(*args: str):  # type: ignore[no-untyped-def]
        return runner.invoke(app, [*args, "--workdir", str(workdir), "--test-db"])

    shown = cli("show-approval", str(approval_id))
    assert shown.exit_code == 0, shown.output
    assert prefix in shown.output

    published = cli(
        "approve", str(approval_id), "--by", "live-test", "--payload", prefix, "--publish"
    )
    assert published.exit_code == 0, published.output
    assert "published:" in published.output

    with Session(db_engine) as s:
        rows = list(
            s.scalars(select(PublicationRow).where(PublicationRow.approval_id == approval_id)).all()
        )
    assert len(rows) == 1
    assert rows[0].status == "published"
    external_ref = rows[0].external_ref
    assert external_ref

    # The review is really there, marker and all, comment at the right line.
    posted = reader.review_comments(owner, repo_name, 1)
    ours = [c for c in posted if PROVENANCE in c["body"]]
    assert any(c["path"] == anchor_path and c["line"] == 1 for c in ours), posted

    # Exactly-once, live: a second publish returns the same external ref and
    # creates no second review.
    again = cli("publish", str(approval_id))
    assert again.exit_code == 0, again.output
    assert external_ref in again.output
    with Session(db_engine) as s:
        count = len(
            list(
                s.scalars(
                    select(PublicationRow).where(
                        PublicationRow.approval_id == approval_id,
                        PublicationRow.status == "published",
                    )
                ).all()
            )
        )
    assert count == 1

    # Approval bookkeeping survived it all.
    with Session(db_engine) as s:
        approval_row = s.get(ApprovalRow, approval_id)
        assert approval_row is not None
        assert approval_row.decision == "approved"
        assert approval_row.decided_by == "live-test"
