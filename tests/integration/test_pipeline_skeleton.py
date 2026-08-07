"""Walking-skeleton pipeline e2e tests (M6). Markers: subproc + pg.

One CLI-equivalent invocation on the fixture repo must produce: a succeeded run
row, two extractor receipts, a persisted+validated graph snapshot, a Cytoscape
artifact, and a run manifest — and a crashed run must resume from its checkpoint
without re-running finished stages.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from codeatlas.artifacts.store import ArtifactStore
from codeatlas.pipeline.deps import PipelineDeps
from codeatlas.pipeline.runner import resume_run, run_status, start_run

pytestmark = [pytest.mark.subproc, pytest.mark.pg]

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_SRC = REPO_ROOT / "fixtures" / "rust-flawed-crate"

sys.path.insert(0, str(REPO_ROOT / "fixtures"))


@pytest.fixture(scope="module")
def test_engine():  # type: ignore[no-untyped-def]
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


@pytest.fixture(scope="module")
def fixture_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    from make_fixture_repos import build_fixture_repo

    dest = tmp_path_factory.mktemp("kvstore-repo")
    build_fixture_repo(FIXTURE_SRC, dest)
    return dest


def _deps(test_engine, tmp: Path, crash_stage: str | None = None) -> PipelineDeps:  # type: ignore[no-untyped-def]
    return PipelineDeps(
        engine=test_engine,
        workdir=tmp,
        cas=ArtifactStore(tmp / "objects"),
        checkpoint_path=tmp / "checkpoints" / "pipeline.sqlite",
        crash_stage=crash_stage,
    )


class TestFullRun:
    def test_one_invocation_produces_all_artifacts(
        self, test_engine, fixture_repo: Path, tmp_path: Path
    ) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.db.tables import ExtractorReceiptRow, GraphSnapshotRow, RunRow

        deps = _deps(test_engine, tmp_path)
        run_id = start_run(deps, repo_path=fixture_repo, repository_id="local/kvstore")
        assert run_status(deps, run_id) == "succeeded"

        with Session(test_engine) as s:
            receipts = s.scalars(
                select(ExtractorReceiptRow).where(ExtractorReceiptRow.run_id == run_id)
            ).all()
            assert {r.extractor for r in receipts} == {
                "cargo-metadata",
                "rust-analyzer-scip",
                "git-churn",
            }
            assert all(r.exit_code == 0 for r in receipts)

            snapshot = s.scalar(select(GraphSnapshotRow).where(GraphSnapshotRow.run_id == run_id))
            assert snapshot is not None
            assert snapshot.node_count > 10
            assert snapshot.canonical_sha256.startswith("sha256:")

            run_row = s.get(RunRow, run_id)
            assert run_row is not None and run_row.manifest_sha256 is not None
            manifest = json.loads(deps.cas.get(run_row.manifest_sha256))
            assert manifest["outputs"]["projectGraph"].startswith("sha256:")
            cyto = json.loads(deps.cas.get(manifest["outputs"]["cytoscape"]))
            assert len(cyto["elements"]["nodes"]) == snapshot.node_count

            # The llms-txt export exists on every run — with narration off it
            # falls back to the measured counts, never invented prose.
            llms = deps.cas.get(manifest["outputs"]["llms-txt"]).decode("utf-8")
            assert llms.startswith("# local/kvstore\n")
            assert "measured by CodeAtlas" in llms

            stages = {e.stage for e in run_row.events if e.event == "finished"}
            assert {
                "source_lock",
                "extract",
                "build_graph",
                "export_llms",
                "export_cytoscape",
                "finalize",
            } <= stages

            # The timing columns are written, not decorative: created at start,
            # stamped when the run reaches a terminal status.
            assert run_row.started_at is not None
            assert run_row.finished_at is not None
            assert run_row.finished_at >= run_row.started_at


class TestCrashAndResume:
    def test_resume_completes_without_rerunning_extract(
        self, test_engine, fixture_repo: Path, tmp_path: Path
    ) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.db.tables import ExtractorReceiptRow

        crashing = _deps(test_engine, tmp_path, crash_stage="export_cytoscape")
        run_id = start_run(crashing, repo_path=fixture_repo, repository_id="local/kvstore")
        assert run_status(crashing, run_id) == "failed"

        healthy = _deps(test_engine, tmp_path, crash_stage=None)
        resume_run(healthy, run_id)
        assert run_status(healthy, run_id) == "succeeded"

        with Session(test_engine) as s:
            receipt_count = s.scalar(
                select(func.count())
                .select_from(ExtractorReceiptRow)
                .where(ExtractorReceiptRow.run_id == run_id)
            )
            # Two extractors plus the churn measurement, each exactly once.
            assert receipt_count == 3, "extract and overview stages must not re-run on resume"


class TestFailurePath:
    def test_non_cargo_repo_fails_with_receipt_and_error_event(
        self, test_engine, tmp_path: Path
    ) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.db.tables import ExtractorReceiptRow, RunRow
        from codeatlas.vcs.git import GitClient

        plain = tmp_path / "plain-repo"
        plain.mkdir()
        (plain / "README.md").write_text("no cargo here\n", encoding="utf-8")
        g = GitClient()
        g.run(["init", "-b", "main"], cwd=plain)
        g.run(["add", "-A"], cwd=plain)
        g.run(["commit", "-m", "x"], cwd=plain)

        deps = _deps(test_engine, tmp_path / "wd")
        run_id = start_run(deps, repo_path=plain, repository_id="local/plain")
        assert run_status(deps, run_id) == "failed"

        with Session(test_engine) as s:
            run_row = s.get(RunRow, run_id)
            assert run_row is not None
            error_events = [e for e in run_row.events if e.level == "error"]
            assert error_events and error_events[0].stage == "extract"
            receipt = s.scalar(
                select(ExtractorReceiptRow).where(ExtractorReceiptRow.run_id == run_id)
            )
            assert receipt is not None and receipt.exit_code != 0


class TestFailureOutsideTheNodes:
    def test_an_invoke_level_failure_still_marks_the_run(
        self, test_engine, fixture_repo: Path, tmp_path: Path, monkeypatch
    ) -> None:  # type: ignore[no-untyped-def]
        """A crash *inside* a node is recorded by the node wrapper; a crash in
        LangGraph itself or the checkpointer used to be swallowed by a blanket
        suppress, leaving the run at `running` forever while start_run returned
        normally — the exact silent failure the rules forbid."""
        from codeatlas.db.tables import RunRow

        class ExplodingPipeline:
            def invoke(self, *args, **kwargs):  # type: ignore[no-untyped-def]
                raise RuntimeError("checkpointer exploded")

        monkeypatch.setattr(
            "codeatlas.pipeline.runner.build_pipeline", lambda deps: ExplodingPipeline()
        )
        deps = _deps(test_engine, tmp_path)
        run_id = start_run(deps, repo_path=fixture_repo, repository_id="local/outside-node")
        assert run_status(deps, run_id) == "failed"

        with Session(test_engine) as s:
            run_row = s.get(RunRow, run_id)
            assert run_row is not None
            errors = [e for e in run_row.events if e.level == "error"]
            assert errors, "the failure must leave a reason, not just a status"
            assert any("checkpointer exploded" in str(e.data) for e in errors)


class TestCli:
    def test_cli_run_on_fixture(self, test_engine, fixture_repo: Path, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        from typer.testing import CliRunner

        from codeatlas.cli.main import app

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "run",
                "--repo",
                str(fixture_repo),
                "--repository-id",
                "local/kvstore-cli",
                "--workdir",
                str(tmp_path / "cliwd"),
                "--test-db",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "succeeded" in result.output
