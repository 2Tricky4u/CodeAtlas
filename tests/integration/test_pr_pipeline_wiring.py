"""PR mode with the review half ON — the wiring no test had ever executed.

`test_full_pipeline_wiring` drives the whole graph in repository mode with
cassettes; the two-revision suites drive PR mode with *no* agent engine. The
intersection — the PR-only conditionals inside the review node, and
`stage_payload`'s dry run — had therefore never run under test, which is
exactly the stage-in-the-wrong-half bug class that wiring test's own
docstring says happened three times.

The engine here is scripted, not a cassette: these assertions are about which
stages ran and what artifacts landed, never about prose, and a scripted
answer proves wiring as well as a recorded one without re-recording every
cassette against the PR fixture's revisions.

Markers: subproc + pg.
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
sys.path.insert(0, str(REPO_ROOT / "fixtures"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from support.engines import ScriptedEngine  # noqa: E402

# Minimal schema-valid outputs. Zero findings on purpose: the funnel's content
# is the cassette suites' business; this file asserts wiring.
INTENT_OUT = {
    "schemaVersion": "1.0.0",
    "requirements": [],
    "nonGoals": [],
    "compatibilityObligations": [],
    "unresolvedQuestions": [],
}
EMPTY_FINDINGS = {"findings": []}
CHANGE_EXPLANATION_OUT = {
    "schemaVersion": "1.0.0",
    "summary": "The defensive parsing was replaced by the original unwrap chain.",
    "sections": [],
}
PROJECT_EXPLANATION_OUT = {
    "schemaVersion": "1.0.0",
    "summary": "A small key-value store.",
    "sections": [
        {
            "id": "what",
            "title": "What this is",
            "claims": [
                {
                    "text": "The cache lives in cache.rs.",
                    "citations": [{"kind": "module", "key": "kvstore/src/cache.rs"}],
                }
            ],
        }
    ],
}
PROTOCOL_REFUSAL = {"schemaVersion": "1.0.0", "protocol": None, "droppedElements": [], "notes": []}


def _script() -> dict[str, object]:
    return {
        "intent-reconstructor": INTENT_OUT,
        "reviewer-correctness": EMPTY_FINDINGS,
        "reviewer-security": EMPTY_FINDINGS,
        "reviewer-architecture": EMPTY_FINDINGS,
        "change-explainer": CHANGE_EXPLANATION_OUT,
        "project-explainer": PROJECT_EXPLANATION_OUT,
        "protocol-modeler": PROTOCOL_REFUSAL,
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


def _pr_run(db_engine, root: Path, repository_id: str, script: dict[str, object]):  # type: ignore[no-untyped-def]
    from make_fixture_repos import build_pr_fixture_repo

    repo_dir = root / "repo"
    base_sha, head_sha = build_pr_fixture_repo(FIXTURE_SRC, repo_dir)
    engine = ScriptedEngine(script)
    deps = PipelineDeps(
        engine=db_engine,
        workdir=root / "wd",
        cas=ArtifactStore(root / "wd" / "objects"),
        checkpoint_path=root / "wd" / "checkpoints" / "p.sqlite",
        agent_engine=engine,
    )
    # What `review-pr` sets: the dry-run payload needs a PR to address.
    deps.github_owner = "o"
    deps.github_repo = "r"
    deps.pr_number = 3
    run_id = start_run(
        deps,
        repo_path=repo_dir,
        repository_id=repository_id,
        ref=head_sha,
        base_ref=base_sha,
        pr_number=3,
    )
    return run_id, deps, engine


@pytest.fixture(scope="module")
def pr_reviewed(db_engine, tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    root = tmp_path_factory.mktemp("pr-wiring")
    return _pr_run(db_engine, root, "local/kvstore-prw", _script())


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


class TestEveryStageRanInPrMode:
    def test_all_thirteen_nodes_finished(self, pr_reviewed, db_engine) -> None:  # type: ignore[no-untyped-def]
        run_id, _, _ = pr_reviewed
        assert {
            "source_lock",
            "extract",
            "build_graph",
            "base_revision",
            "api_change",
            "graph_diff",
            "change_impact",
            "project_overview",
            "architecture",
            "narrate",
            "export_cytoscape",
            "review",
            "finalize",
        } <= _stages(db_engine, run_id)

    def test_the_run_succeeded_cleanly(self, pr_reviewed) -> None:  # type: ignore[no-untyped-def]
        run_id, deps, _ = pr_reviewed
        assert run_status(deps, run_id) == "succeeded"


class TestTheChangeWasExplainedThroughTheGraph:
    def test_change_explainer_was_dispatched_by_the_review_node(self, pr_reviewed) -> None:  # type: ignore[no-untyped-def]
        _, _, engine = pr_reviewed
        assert "change-explainer" in {t.skill_id for t in engine.seen}

    def test_the_explanation_is_a_run_artifact(self, pr_reviewed, db_engine) -> None:  # type: ignore[no-untyped-def]
        run_id, _, _ = pr_reviewed
        assert "change-explanation" in _roles(db_engine, run_id)


class TestTheDryRunPayloadWasPrepared:
    def test_stage_payload_produced_the_dry_run_artifact(self, pr_reviewed, db_engine) -> None:  # type: ignore[no-untyped-def]
        run_id, _, _ = pr_reviewed
        assert "review-payload-dry-run" in _roles(db_engine, run_id)

    def test_nothing_was_published_or_even_requested(self, pr_reviewed, db_engine) -> None:  # type: ignore[no-untyped-def]
        """Shadow means shadow: a payload to inspect, no approval opened, no
        publication row. Approval is a human act via the CLI."""
        from codeatlas.db.tables import ApprovalRow, PublicationRow

        run_id, _, _ = pr_reviewed
        with Session(db_engine) as session:
            assert (
                session.scalars(select(PublicationRow).where(PublicationRow.run_id == run_id)).all()
                == []
            )
            assert (
                session.scalars(select(ApprovalRow).where(ApprovalRow.run_id == run_id)).all() == []
            )


@pytest.fixture(scope="module")
def gapped(db_engine, tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    script = _script()
    script["reviewer-security"] = RuntimeError("scripted reviewer failure")
    root = tmp_path_factory.mktemp("pr-gapped")
    return _pr_run(db_engine, root, "local/kvstore-gaps", script)


class TestAFailedReviewerDegradesTheStatus:
    def test_status_is_exactly_succeeded_with_gaps(self, gapped) -> None:  # type: ignore[no-untyped-def]
        """The one assertion no test made: `succeeded_with_gaps` specifically.
        Every prior test accepted ("succeeded", "succeeded_with_gaps"), so a
        degraded run reporting a clean bill of health would have passed."""
        run_id, deps, _ = gapped
        assert run_status(deps, run_id) == "succeeded_with_gaps"

    def test_the_surviving_reviewers_left_their_audit_rows(self, gapped, db_engine) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.db.tables import AgentInvocationRow

        run_id, _, _ = gapped
        with Session(db_engine) as session:
            recorded = set(
                session.scalars(
                    select(AgentInvocationRow.skill_id).where(AgentInvocationRow.run_id == run_id)
                )
            )
        assert "reviewer-correctness" in recorded
        assert "reviewer-security" not in recorded, (
            "a dispatch that exploded before returning has no result to record"
        )
