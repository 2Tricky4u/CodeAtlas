"""The threat model, cached across two full pipeline runs. Markers: subproc + pg.

`test_threat_stage` proves the cache lifecycle through the stage function in
isolation, and `test_full_pipeline_wiring` proves one full run owns the
threat-model artifact. Neither exercises the thing the feature is *for*: a
second run on the same repository reusing the first's model through the real
graph, paying nothing. This runs the whole pipeline twice on one repository id
and asserts run two adopted run one's model — a `threat_model_cache_hit` event,
the identical artifact sha, and no second dispatch of the threat-modeler.

Replay-backed, so it costs no quota; the point is the graph wiring of the cache,
not the model's prose.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from codeatlas.artifacts.store import ArtifactStore
from codeatlas.pipeline.deps import PipelineDeps
from codeatlas.pipeline.runner import run_status, start_run

pytestmark = [pytest.mark.subproc, pytest.mark.pg, pytest.mark.timeout(1800)]

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_SRC = REPO_ROOT / "fixtures" / "rust-flawed-crate"
CASSETTES = REPO_ROOT / "tests" / "cassettes"
sys.path.insert(0, str(REPO_ROOT / "fixtures"))

REPOSITORY_ID = "local/kvstore"


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


@pytest.fixture(scope="module")
def two_runs(db_engine, tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    """Two full reviewed runs over the same repository, sharing one workdir/DB."""
    from make_fixture_repos import build_fixture_repo

    from codeatlas.agents.replay_engine import ReplayEngine

    root = tmp_path_factory.mktemp("threat-cache")
    repo = root / "repo"
    build_fixture_repo(FIXTURE_SRC, repo)

    deps = PipelineDeps(
        engine=db_engine,
        workdir=root / "wd",
        cas=ArtifactStore(root / "wd" / "objects"),
        checkpoint_path=root / "wd" / "checkpoints" / "p.sqlite",
        agent_engine=ReplayEngine(CASSETTES),
    )
    first = start_run(deps, repo_path=repo, repository_id=REPOSITORY_ID)
    assert run_status(deps, first) in ("succeeded", "succeeded_with_gaps")
    second = start_run(deps, repo_path=repo, repository_id=REPOSITORY_ID)
    assert run_status(deps, second) in ("succeeded", "succeeded_with_gaps")
    return first, second, deps


def _artifact_sha(db_engine, run_id: str, role: str) -> str | None:  # type: ignore[no-untyped-def]
    from codeatlas.db.tables import RunArtifactRow

    with Session(db_engine) as session:
        return session.scalar(
            select(RunArtifactRow.sha256).where(
                RunArtifactRow.run_id == run_id, RunArtifactRow.role == role
            )
        )


def _threat_events(db_engine, run_id: str, event: str) -> list[dict]:  # type: ignore[no-untyped-def]
    from codeatlas.db.tables import RunEventRow

    with Session(db_engine) as session:
        rows = session.scalars(
            select(RunEventRow).where(RunEventRow.run_id == run_id, RunEventRow.event == event)
        ).all()
        return [dict(r.data or {}) for r in rows]


def _threat_dispatches(db_engine, run_id: str) -> int:  # type: ignore[no-untyped-def]
    from codeatlas.db.tables import AgentInvocationRow

    with Session(db_engine) as session:
        return len(
            session.scalars(
                select(AgentInvocationRow).where(
                    AgentInvocationRow.run_id == run_id,
                    AgentInvocationRow.skill_id == "threat-modeler",
                )
            ).all()
        )


class TestTheFirstRunBuilds:
    def test_it_dispatched_the_modeler_and_owns_the_artifact(self, two_runs, db_engine) -> None:  # type: ignore[no-untyped-def]
        first, _, _ = two_runs
        assert _threat_dispatches(db_engine, first) == 1
        assert _artifact_sha(db_engine, first, "threat-model") is not None
        assert _threat_events(db_engine, first, "threat_model_cache_hit") == []


class TestTheSecondRunReuses:
    def test_it_hit_the_cache_without_dispatching(self, two_runs, db_engine) -> None:  # type: ignore[no-untyped-def]
        _, second, _ = two_runs
        assert _threat_dispatches(db_engine, second) == 0, (
            "the second run must not pay to re-model what the first already did"
        )

    def test_it_owns_the_identical_artifact_the_first_run_produced(
        self, two_runs, db_engine
    ) -> None:  # type: ignore[no-untyped-def]
        first, second, _ = two_runs
        first_sha = _artifact_sha(db_engine, first, "threat-model")
        second_sha = _artifact_sha(db_engine, second, "threat-model")
        assert second_sha is not None
        assert second_sha == first_sha

    def test_the_cache_hit_is_a_recorded_event_naming_the_paying_run(
        self, two_runs, db_engine
    ) -> None:  # type: ignore[no-untyped-def]
        """An invisible cache is one nobody can check (the base_graph rule)."""
        first, second, _ = two_runs
        events = _threat_events(db_engine, second, "threat_model_cache_hit")
        assert len(events) == 1
        assert events[0]["producedByRunId"] == first
        assert events[0]["artifact"] == _artifact_sha(db_engine, first, "threat-model")

    def test_the_api_can_serve_the_reused_artifact(self, two_runs, db_engine) -> None:  # type: ignore[no-untyped-def]
        """Adoption is not just a membership row: the reused model is fetchable
        under the second run, which is what the threats tab depends on."""
        from fastapi.testclient import TestClient

        from codeatlas.api.main import create_app

        _, second, deps = two_runs
        client = TestClient(create_app(engine=db_engine, cas=deps.cas, mirrors=deps.mirrors))
        response = client.get(f"/api/runs/{second}/artifact/threat-model")
        assert response.status_code == 200
        assert response.json()["summary"]
