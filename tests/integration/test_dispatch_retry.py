"""The bounded retry ADR-0005 always described and the code never had. Marker: pg.

One retry, only for the two typed failures observed live at real size
(`schema_invalid`, `timeout`), only on live engines — replay must fail loudly
(ADR-0012), and raised exceptions keep propagating. Both attempts land in the
invocation ledger: a rescued run is visibly a rescue, never a clean first try.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from codeatlas.agents.dispatch import build_task, dispatch_with_retry
from codeatlas.agents.registry import SkillRegistry
from codeatlas.artifacts.store import ArtifactStore
from codeatlas.db.tables import AgentInvocationRow

pytestmark = pytest.mark.pg

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / ".agents" / "skills"
sys.path.insert(0, str(REPO_ROOT / "tests"))

from support.engines import FlakyEngine, ScriptedEngine  # noqa: E402

SHA = "c" * 40
ECHO_OUTPUT = {"revision": SHA, "rustFileCount": 1}


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
def registry() -> SkillRegistry:
    return SkillRegistry.load(SKILLS_DIR)


def _run_id(db_engine) -> str:  # type: ignore[no-untyped-def]
    from codeatlas.db import repositories as repo

    with Session(db_engine) as s:
        repository = repo.ensure_repository(s, repository_id="local/retry", provider="local")
        revision = repo.ensure_revision(s, repository_id=repository.id, sha=SHA)
        run = repo.create_run(
            s, repository_id=repository.id, kind="repository", head_revision_id=revision.id
        )
        s.commit()
        return run.id


def _factory(registry: SkillRegistry, run_id: str, checkout: Path):  # type: ignore[no-untyped-def]
    skill = registry.get("echo-skill")

    def make():  # type: ignore[no-untyped-def]
        return build_task(
            skill=skill, run_id=run_id, revision_sha=SHA, checkout=checkout, inputs={}
        )

    return make


def _rows(db_engine, run_id: str) -> list[AgentInvocationRow]:  # type: ignore[no-untyped-def]
    with Session(db_engine) as s:
        return list(
            s.scalars(
                select(AgentInvocationRow)
                .where(AgentInvocationRow.run_id == run_id)
                .order_by(AgentInvocationRow.id)
            ).all()
        )


class TestRetry:
    def test_schema_invalid_is_retried_with_the_error_quoted(
        self, db_engine, registry: SkillRegistry, tmp_path: Path
    ) -> None:  # type: ignore[no-untyped-def]
        run_id = _run_id(db_engine)
        engine = FlakyEngine("schema_invalid", ECHO_OUTPUT)
        result = dispatch_with_retry(
            engine=engine,
            registry=registry,
            skill_id="echo-skill",
            task_factory=_factory(registry, run_id, tmp_path),
            db_engine=db_engine,
            cas=ArtifactStore(tmp_path / "objects"),
        )
        assert result.status == "succeeded"
        assert len(engine.calls) == 2
        first_task, first_instructions = engine.calls[0]
        second_task, second_instructions = engine.calls[1]
        assert first_task.task_id != second_task.task_id
        assert "previous attempt" in second_instructions.lower()
        assert engine.error in second_instructions
        assert "previous attempt" not in first_instructions.lower()
        statuses = [(r.status, r.task_id) for r in _rows(db_engine, run_id)]
        assert [s for s, _ in statuses] == ["schema_invalid", "succeeded"]
        assert statuses[0][1] != statuses[1][1]

    def test_timeout_is_retried_without_a_suffix(
        self, db_engine, registry: SkillRegistry, tmp_path: Path
    ) -> None:  # type: ignore[no-untyped-def]
        run_id = _run_id(db_engine)
        engine = FlakyEngine("timeout", ECHO_OUTPUT, error="wall-clock timeout")
        result = dispatch_with_retry(
            engine=engine,
            registry=registry,
            skill_id="echo-skill",
            task_factory=_factory(registry, run_id, tmp_path),
            db_engine=db_engine,
            cas=ArtifactStore(tmp_path / "objects"),
        )
        assert result.status == "succeeded"
        assert len(engine.calls) == 2
        # A timeout carries no schema errors worth quoting; the instructions
        # are identical both times.
        assert engine.calls[0][1] == engine.calls[1][1]

    def test_two_failures_stay_failed_with_both_on_the_ledger(
        self, db_engine, registry: SkillRegistry, tmp_path: Path
    ) -> None:  # type: ignore[no-untyped-def]
        run_id = _run_id(db_engine)
        engine = FlakyEngine("schema_invalid", ECHO_OUTPUT, failures=5)
        result = dispatch_with_retry(
            engine=engine,
            registry=registry,
            skill_id="echo-skill",
            task_factory=_factory(registry, run_id, tmp_path),
            db_engine=db_engine,
            cas=ArtifactStore(tmp_path / "objects"),
        )
        assert result.status == "schema_invalid"
        assert len(engine.calls) == 2, "exactly one retry, never a loop"
        assert [r.status for r in _rows(db_engine, run_id)] == [
            "schema_invalid",
            "schema_invalid",
        ]

    def test_a_replay_engine_is_never_retried(
        self, db_engine, registry: SkillRegistry, tmp_path: Path
    ) -> None:  # type: ignore[no-untyped-def]
        """ADR-0012: replay fails loudly; a retry would only mask a stale cassette."""
        run_id = _run_id(db_engine)
        engine = FlakyEngine("schema_invalid", ECHO_OUTPUT)
        engine.name = "replay"
        result = dispatch_with_retry(
            engine=engine,
            registry=registry,
            skill_id="echo-skill",
            task_factory=_factory(registry, run_id, tmp_path),
            db_engine=db_engine,
            cas=ArtifactStore(tmp_path / "objects"),
        )
        assert result.status == "schema_invalid"
        assert len(engine.calls) == 1

    def test_a_raised_exception_propagates_unretried(
        self, db_engine, registry: SkillRegistry, tmp_path: Path
    ) -> None:  # type: ignore[no-untyped-def]
        run_id = _run_id(db_engine)
        engine = ScriptedEngine({"echo-skill": RuntimeError("engine exploded")})
        with pytest.raises(RuntimeError, match="engine exploded"):
            dispatch_with_retry(
                engine=engine,
                registry=registry,
                skill_id="echo-skill",
                task_factory=_factory(registry, run_id, tmp_path),
                db_engine=db_engine,
                cas=ArtifactStore(tmp_path / "objects"),
            )
        assert len(engine.seen) == 1
        assert _rows(db_engine, run_id) == []
