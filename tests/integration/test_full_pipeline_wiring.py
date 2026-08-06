"""The whole graph, both halves, wired (G9). Markers: subproc + pg.

Every stage function is tested on its own and every agent skill is replayed
against a cassette, but nothing ran the LangGraph itself with the review half
enabled — so a stage could be moved between nodes, or dropped from a node's body,
and every existing test would still pass. That happened three times in this
phase: the architecture model, the ADR audit and the project narrative were each
sitting in the wrong half, and only reading the code found it.

This is the test that would have caught a stage silently not running. It asserts
what a *run* contains rather than what a function returns, and it deliberately
does not assert prose: a cassette's content is frozen model output and testing it
would be testing the model.
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

# The cassettes are keyed on their inputs, and the overview carries the
# repository id — so replay only works under the id they were recorded with.
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
def reviewed(db_engine, tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    """One full run with both halves on, agents replayed from cassettes."""
    from make_fixture_repos import build_fixture_repo

    from codeatlas.agents.replay_engine import ReplayEngine

    root = tmp_path_factory.mktemp("wiring")
    repo = root / "repo"
    build_fixture_repo(FIXTURE_SRC, repo)

    deps = PipelineDeps(
        engine=db_engine,
        workdir=root / "wd",
        cas=ArtifactStore(root / "wd" / "objects"),
        checkpoint_path=root / "wd" / "checkpoints" / "p.sqlite",
        agent_engine=ReplayEngine(CASSETTES),
    )
    run_id = start_run(deps, repo_path=repo, repository_id=REPOSITORY_ID)
    assert run_status(deps, run_id) in ("succeeded", "succeeded_with_gaps")
    return run_id, deps


def _roles(db_engine, run_id: str) -> set[str]:  # type: ignore[no-untyped-def]
    from codeatlas.db.tables import RunArtifactRow

    with Session(db_engine) as session:
        return set(
            session.scalars(select(RunArtifactRow.role).where(RunArtifactRow.run_id == run_id))
        )


def _stages(db_engine, run_id: str) -> set[str]:  # type: ignore[no-untyped-def]
    from codeatlas.db.tables import RunEventRow

    with Session(db_engine) as session:
        return set(
            session.scalars(
                select(RunEventRow.stage).where(
                    RunEventRow.run_id == run_id, RunEventRow.event == "finished"
                )
            )
        )


class TestEveryNodeRan:
    def test_no_node_was_silently_skipped(self, reviewed, db_engine) -> None:  # type: ignore[no-untyped-def]
        run_id, _ = reviewed
        assert {
            "source_lock",
            "extract",
            "build_graph",
            "project_overview",
            "architecture",
            "narrate",
            "export_cytoscape",
            "review",
            "finalize",
        } <= _stages(db_engine, run_id)


class TestEveryHalfProducedItsArtifacts:
    def test_the_deterministic_half_did(self, reviewed, db_engine) -> None:  # type: ignore[no-untyped-def]
        run_id, _ = reviewed
        assert {
            "project-graph",
            "project-overview",
            "graph-views",
            "cytoscape-elements",
            "architecture",
            "structurizr-dsl",
            "adr-audit",
            "source-lock",
            "run-manifest",
        } <= _roles(db_engine, run_id)

    def test_the_agent_half_did(self, reviewed, db_engine) -> None:  # type: ignore[no-untyped-def]
        run_id, _ = reviewed
        assert {
            "intent",
            "candidate-findings",
            "review-markdown",
            "project-explanation",
            "protocol-model",
        } <= _roles(db_engine, run_id)


class TestTheApiCanServeEverythingTheRunOwns:
    def test_every_role_resolves(self, reviewed, db_engine) -> None:  # type: ignore[no-untyped-def]
        """The G1 guarantee at run level rather than at context level.

        The original bug was five artifacts that were stored, named in the
        manifest and 404 from the API. `test_review_artifact_publication`
        asserts this for a synthetic context; this asserts it for everything a
        real run actually produced, which is the form that would have caught it.
        """
        from fastapi.testclient import TestClient

        from codeatlas.api.main import create_app

        run_id, deps = reviewed
        client = TestClient(create_app(engine=db_engine, cas=deps.cas, mirrors=deps.mirrors))
        for role in sorted(_roles(db_engine, run_id)):
            assert client.get(f"/api/runs/{run_id}/artifact/{role}").status_code == 200, role

    def test_the_manifest_names_only_roles_that_resolve(self, reviewed, db_engine) -> None:  # type: ignore[no-untyped-def]
        """The manifest and the membership table must not disagree — an entry
        naming content nobody can fetch is exactly the bug G1 removed."""
        import json

        from codeatlas.db.tables import RunRow

        run_id, deps = reviewed
        with Session(db_engine) as session:
            row = session.get(RunRow, run_id)
            assert row is not None and row.manifest_sha256 is not None
            manifest = json.loads(deps.cas.get(row.manifest_sha256))

        for name, sha in manifest["outputs"].items():
            assert deps.cas.exists(sha), f"{name} names content the store does not hold"


class TestTheReviewLeftItsEvidence:
    def test_findings_were_persisted_with_a_verdict(self, reviewed, db_engine) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.db.tables import FindingRow

        run_id, _ = reviewed
        with Session(db_engine) as session:
            rows = session.scalars(select(FindingRow).where(FindingRow.run_id == run_id)).all()
        assert rows, "the reviewers replayed but nothing reached the findings table"
        # "candidate" means validation never looked at it.
        assert all(r.status != "candidate" for r in rows)

    def test_every_agent_invocation_was_recorded(self, reviewed, db_engine) -> None:  # type: ignore[no-untyped-def]
        """Each dispatch leaves a row; a skill that ran without one is a hole in
        the audit trail, whatever it returned."""
        from codeatlas.db.tables import AgentInvocationRow

        run_id, _ = reviewed
        with Session(db_engine) as session:
            skills = set(
                session.scalars(
                    select(AgentInvocationRow.skill_id).where(AgentInvocationRow.run_id == run_id)
                )
            )
        assert {"intent-reconstructor", "project-explainer", "protocol-modeler"} <= skills

    def test_extractor_receipts_back_the_graph(self, reviewed, db_engine) -> None:  # type: ignore[no-untyped-def]
        """Every extractor invocation emits a receipt — the rule that makes a
        compiler-derived edge distinguishable from an inferred one."""
        from codeatlas.db.tables import ExtractorReceiptRow

        run_id, _ = reviewed
        with Session(db_engine) as session:
            receipts = session.scalars(
                select(ExtractorReceiptRow).where(ExtractorReceiptRow.run_id == run_id)
            ).all()
        assert {"cargo-metadata", "rust-analyzer-scip"} <= {r.extractor for r in receipts}


class TestNothingWasPublished:
    def test_a_run_with_no_pull_request_prepares_nothing(self, reviewed, db_engine) -> None:  # type: ignore[no-untyped-def]
        """Shadow by default, and with no PR target there is not even a payload.
        A publication row here would mean the gate was bypassed entirely."""
        from codeatlas.db.tables import PublicationRow

        run_id, _ = reviewed
        with Session(db_engine) as session:
            published = session.scalars(
                select(PublicationRow).where(PublicationRow.run_id == run_id)
            ).all()
        assert published == []
