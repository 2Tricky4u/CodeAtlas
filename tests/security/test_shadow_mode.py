"""Shadow mode must produce the real payload and post nothing. Marker: pg."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from codeatlas.artifacts.store import ArtifactStore
from codeatlas.models.findings import Finding
from codeatlas.models.graph import Evidence, SourceLocation
from codeatlas.models.validation import ValidationEvidence, ValidationResult
from codeatlas.publication.shadow import run_shadow
from codeatlas.review.scope import ChangedScope
from codeatlas.review.synthesis import build_report

pytestmark = pytest.mark.pg

SHA = "d" * 40


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
def run_id(db_engine) -> str:  # type: ignore[no-untyped-def]
    from codeatlas.db import repositories as repo

    with Session(db_engine) as s:
        repository = repo.ensure_repository(s, repository_id="o/r", provider="github")
        revision = repo.ensure_revision(s, repository_id=repository.id, sha=SHA)
        run = repo.create_run(
            s, repository_id=repository.id, kind="pr", head_revision_id=revision.id, pr_number=5
        )
        s.commit()
        return run.id


def _pair(fid: str, path: str, line: int):  # type: ignore[no-untyped-def]
    finding = Finding(
        finding_id=fid,
        category="correctness",
        discovered_by_skill="reviewer-correctness",
        skill_version="1.0.0",
        severity="high",
        confidence=0.9,
        claim=f"claim {fid}",
        location=SourceLocation(path=path, start_line=line, end_line=line + 1),
        evidence=[Evidence(kind="llm-inference", producer="reviewer", confidence=0.9)],
    )
    validation = ValidationResult(
        finding_id=fid,
        status="validated",
        severity="high",
        confidence=0.95,
        introduced_by_change=True,
        location=finding.location,
        claim=finding.claim,
        evidence=[ValidationEvidence(kind="test", command=f"cargo test {fid}", exit_code=101)],
        counter_evidence_checked=["callers"],
        publication_eligible=True,
        reason=f"verdict reason for {fid}",
    )
    return finding, validation


def _shadow(db_engine, run_id: str, tmp_path):  # type: ignore[no-untyped-def]
    introduced = _pair("F-0001", "kvstore/src/api.rs", 26)
    pre_existing = _pair("F-0002", "kvstore/src/storage.rs", 20)
    findings = [introduced[0], pre_existing[0]]
    report = build_report(
        run_id=run_id,
        revision_sha=SHA,
        findings=findings,
        validations={f.finding_id: v for f, v in (introduced, pre_existing)},
        failed_skills=[],
    )
    scope = ChangedScope(
        changed_paths={"kvstore/src/api.rs"},
        added_lines={"kvstore/src/api.rs": {25, 26, 27}},
    )
    with Session(db_engine) as s:
        result = run_shadow(
            s,
            run_id=run_id,
            report=report,
            findings=findings,
            scope=scope,
            cas=ArtifactStore(tmp_path / "objects"),
            owner="o",
            repo="r",
            pr_number=5,
            commit_sha=SHA,
        )
        s.commit()
    return result


class TestShadowPublishesNothing:
    def test_no_approval_and_no_publication_are_created(self, db_engine, run_id, tmp_path) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.db.tables import ApprovalRow, PublicationRow

        _shadow(db_engine, run_id, tmp_path)
        with Session(db_engine) as s:
            assert s.scalar(select(ApprovalRow).where(ApprovalRow.run_id == run_id)) is None
            assert s.scalar(select(PublicationRow).where(PublicationRow.run_id == run_id)) is None

    def test_run_is_not_paused_for_approval(self, db_engine, run_id, tmp_path) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.db.tables import RunRow

        _shadow(db_engine, run_id, tmp_path)
        with Session(db_engine) as s:
            run = s.get(RunRow, run_id)
            assert run is not None and run.status != "paused_for_approval"


class TestShadowProducesTheRealPayload:
    def test_payload_is_content_addressed_and_indexed(self, db_engine, run_id, tmp_path) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.db.tables import ArtifactRow

        result = _shadow(db_engine, run_id, tmp_path)
        assert result.dry_run.payload_sha256.startswith("sha256:")
        with Session(db_engine) as s:
            assert s.get(ArtifactRow, result.dry_run.payload_sha256) is not None

    def test_inline_comments_are_limited_to_changed_files(
        self, db_engine, run_id, tmp_path
    ) -> None:  # type: ignore[no-untyped-def]
        # F-0001's whole span (26-27) consists of added lines, so it posts as
        # a range comment — GitHub anchors a range at its END line. F-0002's
        # file is untouched and appears in the body only.
        result = _shadow(db_engine, run_id, tmp_path)
        assert result.dry_run.would_comment_on == ["kvstore/src/api.rs:27"]

    def test_scope_split_is_reported(self, db_engine, run_id, tmp_path) -> None:  # type: ignore[no-untyped-def]
        result = _shadow(db_engine, run_id, tmp_path)
        assert result.blocking_ids == ["F-0001"]
        assert result.non_blocking_ids == ["F-0002"]
        assert result.scope_counts == {"introduced": 1, "pre-existing": 1}
        assert result.would_block is True

    def test_payload_is_secret_scanned_in_shadow_too(self, db_engine, run_id, tmp_path) -> None:  # type: ignore[no-untyped-def]
        result = _shadow(db_engine, run_id, tmp_path)
        assert result.dry_run.secrets_detected == []
        assert result.dry_run.safe is True
