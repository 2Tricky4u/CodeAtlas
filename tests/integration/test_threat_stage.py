"""The threat stage's cache: one model per repository, reused until refreshed.

The first artifact reused *across* runs through `adopt_artifact` — the base
graph is reused via its own cache table and the dry-run payload is adopted
within a run, so this is the path that proves cross-run adoption works: the
second run owns a `threat-model` membership row it never paid for, a
`threat_model_cache_hit` event says where it came from, and the engine is
provably never dispatched.

Markers: pg. The engine is scripted — cache behavior is wiring, not prose.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from codeatlas.artifacts.store import ArtifactStore
from codeatlas.models.graph import ProjectGraph
from codeatlas.pipeline.deps import PipelineDeps
from codeatlas.pipeline.review_stages import ReviewContext
from codeatlas.pipeline.threat_stage import stage_threat_model

pytestmark = [pytest.mark.pg, pytest.mark.timeout(120)]

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests"))

from support.engines import ScriptedEngine  # noqa: E402

HEAD = "b" * 40

GRAPH: dict[str, Any] = {
    "schemaVersion": "1.0.0",
    "repository": {"id": "local/threatcache", "url": "https://example.org/tc.git"},
    "revision": {"head": HEAD},
    "nodes": [
        {
            "id": "pkg:cargo/tc@0.1.0",
            "kind": "package",
            "label": "tc 0.1.0",
            "language": "rust",
            "evidence": [{"kind": "build-system", "producer": "cargo"}],
        },
        {
            "id": "file:src/lib.rs",
            "kind": "file",
            "label": "src/lib.rs",
            "location": {"path": "src/lib.rs"},
            "evidence": [{"kind": "language-server", "producer": "rust-analyzer"}],
        },
        {
            "id": "file:src/main.rs",
            "kind": "file",
            "label": "src/main.rs",
            "location": {"path": "src/main.rs"},
            "evidence": [{"kind": "language-server", "producer": "rust-analyzer"}],
        },
    ],
    "edges": [],
}

THREAT_OUT: dict[str, Any] = {
    "schemaVersion": "1.0.0",
    # Deliberately wrong: the pipeline must overwrite it with the measured head.
    "modeledAtRevision": "0" * 40,
    "summary": "a stdin-fed store; whoever writes to stdin drives the parser",
    "components": [{"name": "parser", "evidence": {"path": "src/lib.rs"}}],
    "attacker": {
        "capabilities": ["controls stdin"],
        "nonCapabilities": ["no network access to the process"],
    },
    "threats": [
        {
            "id": "TM-001",
            "title": "Oversized command",
            "source": "stdin",
            "action": "send an oversized line",
            "impact": "unbounded buffer growth",
            "existingControls": [
                {"description": "length capped", "evidence": {"path": "src/lib.rs"}}
            ],
            "likelihood": "medium",
            "severity": "medium",
        }
    ],
    "focusPaths": [
        {"path": "src/lib.rs", "reason": "parses untrusted input", "threatIds": ["TM-001"]},
        {"path": "src/main.rs", "reason": "wires stdin to the parser"},
    ],
    "notes": [],
}


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


def _new_run(db_engine, repository_id: str) -> tuple[str, int]:  # type: ignore[no-untyped-def]
    """A run over `repository_id` at HEAD, with the file table populated."""
    from codeatlas.db import repositories as repo
    from codeatlas.db.tables import FileRow

    with Session(db_engine) as session:
        repository = repo.ensure_repository(session, repository_id=repository_id, provider="local")
        revision = repo.ensure_revision(session, repository_id=repository.id, sha=HEAD)
        existing = session.scalar(select(FileRow).where(FileRow.revision_id == revision.id))
        if existing is None:
            for path in ("src/lib.rs", "src/main.rs"):
                session.add(FileRow(revision_id=revision.id, path=path, git_blob_sha="c" * 40))
        run = repo.create_run(
            session, repository_id=repository.id, kind="repository", head_revision_id=revision.id
        )
        session.commit()
        return run.id, revision.id


def _stage(  # type: ignore[no-untyped-def]
    db_engine,
    tmp_path: Path,
    repository_id: str,
    script: dict[str, object],
    *,
    refresh: bool = False,
) -> tuple[ReviewContext, ScriptedEngine, str]:
    """Run stage_threat_model once with a fresh run and a scripted engine."""
    from codeatlas.project.overview import build_overview

    run_id, revision_db_id = _new_run(db_engine, repository_id)
    graph = ProjectGraph.model_validate(GRAPH)
    engine = ScriptedEngine(script)
    deps = PipelineDeps(
        engine=db_engine,
        workdir=tmp_path / "wd",
        cas=ArtifactStore(tmp_path / "wd" / "objects"),
        checkpoint_path=tmp_path / "wd" / "checkpoints" / "p.sqlite",
        agent_engine=engine,
        refresh_threat_model=refresh,
    )
    overview_sha = deps.cas.put_json(
        build_overview(graph, repository_id=repository_id).contract_dump()
    )
    ctx = ReviewContext(
        run_id=run_id, revision_sha=HEAD, checkout=tmp_path / "checkout", graph=graph
    )
    stage_threat_model(
        deps,
        ctx,
        repository_id=repository_id,
        revision_db_id=revision_db_id,
        project_overview_sha=overview_sha,
    )
    return ctx, engine, run_id


def _cache_row(db_engine, repository_id: str):  # type: ignore[no-untyped-def]
    from codeatlas.db.tables import ThreatModelCacheRow

    with Session(db_engine) as session:
        return session.scalar(
            select(ThreatModelCacheRow).where(ThreatModelCacheRow.repository_id == repository_id)
        )


def _events(db_engine, run_id: str, event: str) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    from codeatlas.db.tables import RunEventRow

    with Session(db_engine) as session:
        rows = session.scalars(
            select(RunEventRow).where(RunEventRow.run_id == run_id, RunEventRow.event == event)
        ).all()
        return [dict(row.data or {}) for row in rows]


class TestTheFirstRunPays:
    def test_a_fresh_build_publishes_and_remembers(self, db_engine, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        ctx, engine, run_id = _stage(
            db_engine, tmp_path, "local/tc-fresh", {"threat-modeler": THREAT_OUT}
        )
        assert [t.skill_id for t in engine.seen] == ["threat-modeler"]
        assert "threat-model" in ctx.artifacts
        row = _cache_row(db_engine, "local/tc-fresh")
        assert row is not None
        assert row.artifact_sha256 == ctx.artifacts["threat-model"]
        assert row.modeled_at_revision == HEAD
        assert row.produced_by_run_id == run_id

    def test_the_revision_is_measured_not_taken_from_the_agent(
        self, db_engine, tmp_path: Path
    ) -> None:  # type: ignore[no-untyped-def]
        """The scripted output claims revision 000…0; the artifact must not."""
        ctx, _, _ = _stage(db_engine, tmp_path, "local/tc-rev", {"threat-modeler": THREAT_OUT})
        assert ctx.threat_model is not None
        assert ctx.threat_model.modeled_at_revision == HEAD

    def test_an_honest_empty_model_is_cached_too(self, db_engine, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        """ "No meaningful attack surface" is a durable answer, not a failure."""
        empty = {
            "schemaVersion": "1.0.0",
            "modeledAtRevision": "0" * 40,
            "summary": "a batch tool",
            "threats": [],
            "notes": ["nothing crosses a trust boundary"],
        }
        ctx, _, _ = _stage(db_engine, tmp_path, "local/tc-empty", {"threat-modeler": empty})
        assert _cache_row(db_engine, "local/tc-empty") is not None
        assert any("no meaningful attack surface" in n for n in ctx.notes)


class TestTheSecondRunDoesNot:
    def test_a_cache_hit_adopts_without_dispatching(self, db_engine, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        first, _, _ = _stage(db_engine, tmp_path, "local/tc-hit", {"threat-modeler": THREAT_OUT})
        # An empty script would raise on any dispatch — reuse must never ask.
        second, engine, _run_id = _stage(db_engine, tmp_path, "local/tc-hit", {})
        assert engine.seen == []
        assert second.threat_model is not None
        assert second.threat_model.summary == first.threat_model.summary  # type: ignore[union-attr]
        assert second.artifacts["threat-model"] == first.artifacts["threat-model"]
        assert any("reused" in n for n in second.notes)

    def test_the_reuse_is_a_recorded_event_with_provenance(self, db_engine, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        """An invisible cache is one nobody can check."""
        _, _, paying_run = _stage(
            db_engine, tmp_path, "local/tc-event", {"threat-modeler": THREAT_OUT}
        )
        _, _, run_id = _stage(db_engine, tmp_path, "local/tc-event", {})
        events = _events(db_engine, run_id, "threat_model_cache_hit")
        assert len(events) == 1
        assert events[0]["modeledAtRevision"] == HEAD
        assert events[0]["producedByRunId"] == paying_run

    def test_the_adopted_artifact_is_this_runs_membership_row(
        self, db_engine, tmp_path: Path
    ) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.db.tables import RunArtifactRow

        _stage(db_engine, tmp_path, "local/tc-member", {"threat-modeler": THREAT_OUT})
        _ctx, _, run_id = _stage(db_engine, tmp_path, "local/tc-member", {})
        with Session(db_engine) as session:
            roles = set(
                session.scalars(
                    select(RunArtifactRow.role).where(RunArtifactRow.run_id == run_id)
                ).all()
            )
        assert "threat-model" in roles


class TestRefresh:
    def test_refresh_rebuilds_and_logs_the_supersession(self, db_engine, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        first, _, _ = _stage(
            db_engine, tmp_path, "local/tc-refresh", {"threat-modeler": THREAT_OUT}
        )
        rewritten = dict(THREAT_OUT, summary="the parser moved; the model follows")
        ctx, engine, run_id = _stage(
            db_engine,
            tmp_path,
            "local/tc-refresh",
            {"threat-modeler": rewritten},
            refresh=True,
        )
        assert [t.skill_id for t in engine.seen] == ["threat-modeler"]
        row = _cache_row(db_engine, "local/tc-refresh")
        assert row is not None
        assert row.produced_by_run_id == run_id
        assert row.artifact_sha256 == ctx.artifacts["threat-model"]
        events = _events(db_engine, run_id, "threat_model_refreshed")
        assert len(events) == 1
        assert events[0]["superseded"] == first.artifacts["threat-model"]
        assert events[0]["artifact"] == ctx.artifacts["threat-model"]


class TestFailureIsOpen:
    def test_a_modeler_that_explodes_leaves_a_note_and_no_cache(
        self, db_engine, tmp_path: Path
    ) -> None:  # type: ignore[no-untyped-def]
        ctx, _, _ = _stage(
            db_engine,
            tmp_path,
            "local/tc-boom",
            {"threat-modeler": RuntimeError("scripted failure")},
        )
        assert ctx.threat_model is None
        assert "threat-model" not in ctx.artifacts
        assert any("threat model unavailable" in n for n in ctx.notes)
        assert _cache_row(db_engine, "local/tc-boom") is None

    def test_the_published_artifact_revalidates_as_a_contract_model(
        self, db_engine, tmp_path: Path
    ) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.models.threat import ThreatModel

        ctx, _, _ = _stage(db_engine, tmp_path, "local/tc-valid", {"threat-modeler": THREAT_OUT})
        deps_cas = ArtifactStore(tmp_path / "wd" / "objects")
        raw = json.loads(deps_cas.get(ctx.artifacts["threat-model"]))
        model = ThreatModel.model_validate(raw)
        assert model.focus_paths and all(
            f.path in {"src/lib.rs", "src/main.rs"} for f in model.focus_paths
        )
        # The control cited a real file: validation verified it.
        assert model.threats[0].existing_controls[0].verified is True
