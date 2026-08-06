"""Project comprehension does not require a review (G2). Markers: subproc + pg.

Phase 2 promised two independent capabilities: "a repo with no PR still gets a
full map; a PR review works without anyone opening the map." The implementation
did not deliver that. `stage_explain_project` sat inside the `review` node, so
narrating a project meant also running four reviewers, an adversarial validator
per finding, the C4 export and the ADR audit — or getting nothing.

The two are now separate nodes with separate flags. What follows is the claim
the plan made, asserted.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from codeatlas.artifacts.store import ArtifactStore

pytestmark = [pytest.mark.subproc, pytest.mark.pg, pytest.mark.timeout(1800)]

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_SRC = REPO_ROOT / "fixtures" / "rust-flawed-crate"
CASSETTES = REPO_ROOT / "tests" / "cassettes"
sys.path.insert(0, str(REPO_ROOT / "fixtures"))


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


def _deps(db_engine, tmp: Path, **overrides):  # type: ignore[no-untyped-def]
    from codeatlas.agents.replay_engine import ReplayEngine
    from codeatlas.pipeline.deps import PipelineDeps

    return PipelineDeps(
        engine=db_engine,
        workdir=tmp / "wd",
        cas=ArtifactStore(tmp / "wd" / "objects"),
        checkpoint_path=tmp / "wd" / "checkpoints" / "p.sqlite",
        agent_engine=ReplayEngine(CASSETTES),
        **overrides,
    )


def _run(deps, tmp: Path) -> str:  # type: ignore[no-untyped-def]
    from make_fixture_repos import build_fixture_repo

    from codeatlas.pipeline.runner import start_run

    source = tmp / "repo"
    build_fixture_repo(FIXTURE_SRC, source)
    run_id: str = start_run(deps, repo_path=source, repository_id="local/kvstore")
    return run_id


def _roles(db_engine, run_id: str) -> set[str]:  # type: ignore[no-untyped-def]
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from codeatlas.db.tables import RunArtifactRow

    with Session(db_engine) as session:
        return set(
            session.scalars(select(RunArtifactRow.role).where(RunArtifactRow.run_id == run_id))
        )


class TestNarrationWithoutReview:
    def test_a_run_with_review_off_still_explains_the_project(self, db_engine, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """The half of the plan's independence claim that was false."""
        deps = _deps(db_engine, tmp_path, review_enabled=False)
        run_id = _run(deps, tmp_path)
        roles = _roles(db_engine, run_id)
        assert "project-explanation" in roles
        # and none of the review's own output. `architecture` and `adr-audit`
        # are deliberately absent from this set: they need no agent, so they are
        # produced deterministically and are present on every run.
        assert not roles & {"candidate-findings", "review-markdown", "intent"}

    def test_the_deterministic_project_artifacts_do_not_wait_for_a_review(
        self, db_engine, tmp_path
    ) -> None:  # type: ignore[no-untyped-def]
        """Whether the code still matches its ADRs is a question about a
        repository, not about a change to it."""
        deps = _deps(db_engine, tmp_path, review_enabled=False, narration_enabled=False)
        run_id = _run(deps, tmp_path)
        assert {"architecture", "structurizr-dsl", "adr-audit"} <= _roles(db_engine, run_id)

    def test_no_findings_are_recorded_when_review_is_off(self, db_engine, tmp_path) -> None:  # type: ignore[no-untyped-def]
        from sqlalchemy import func, select
        from sqlalchemy.orm import Session

        from codeatlas.db.tables import FindingRow

        deps = _deps(db_engine, tmp_path, review_enabled=False)
        run_id = _run(deps, tmp_path)
        with Session(db_engine) as session:
            count = session.scalar(
                select(func.count()).select_from(FindingRow).where(FindingRow.run_id == run_id)
            )
        assert count == 0


class TestReviewWithoutNarration:
    def test_a_run_with_narration_off_still_reviews(self, db_engine, tmp_path) -> None:  # type: ignore[no-untyped-def]
        deps = _deps(db_engine, tmp_path, narration_enabled=False)
        run_id = _run(deps, tmp_path)
        roles = _roles(db_engine, run_id)
        assert "project-explanation" not in roles
        assert "intent" in roles


class TestBothOff:
    def test_the_deterministic_half_still_completes(self, db_engine, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A deterministic-only run is a supported mode, not a degraded one."""
        from sqlalchemy.orm import Session

        from codeatlas.db.tables import RunRow

        deps = _deps(db_engine, tmp_path, narration_enabled=False, review_enabled=False)
        run_id = _run(deps, tmp_path)
        with Session(db_engine) as session:
            assert session.get(RunRow, run_id).status == "succeeded"  # type: ignore[union-attr]
        roles = _roles(db_engine, run_id)
        assert {"project-graph", "project-overview", "graph-views"} <= roles

    def test_a_run_with_no_engine_says_why_there_is_no_narrative(self, db_engine, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """Silence would read as "this project has nothing worth saying"."""
        from sqlalchemy import select
        from sqlalchemy.orm import Session

        from codeatlas.pipeline.deps import PipelineDeps

        deps = PipelineDeps(
            engine=db_engine,
            workdir=tmp_path / "wd",
            cas=ArtifactStore(tmp_path / "wd" / "objects"),
            checkpoint_path=tmp_path / "wd" / "checkpoints" / "p.sqlite",
        )
        run_id = _run(deps, tmp_path)
        with Session(db_engine) as session:
            from codeatlas.db.tables import RunEventRow

            events = session.scalars(
                select(RunEventRow).where(
                    RunEventRow.run_id == run_id, RunEventRow.stage == "narrate"
                )
            ).all()
        assert any("skipped" in e.event for e in events), [e.event for e in events]
