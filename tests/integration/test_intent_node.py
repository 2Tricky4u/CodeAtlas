"""Intent reconstruction node (M9) via the replay engine. Markers: subproc + pg.

Uses a recorded cassette so the test is deterministic and quota-free. Covers the
happy path, the citation-verification downgrade, and the no-spec case where the
node must record `unavailable` rather than fabricate requirements.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from codeatlas.agents.budget import TokenBudget
from codeatlas.agents.dispatch import build_task
from codeatlas.agents.registry import SkillRegistry
from codeatlas.agents.replay_engine import ReplayEngine
from codeatlas.artifacts.store import ArtifactStore
from codeatlas.models.agent import AgentResult, CommandReceipt, UsageStats
from codeatlas.review.intent import collect_intent_sources
from codeatlas.review.intent_node import reconstruct_intent

pytestmark = [pytest.mark.subproc, pytest.mark.pg]

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_SRC = REPO_ROOT / "fixtures" / "rust-flawed-crate"
SKILLS_DIR = REPO_ROOT / ".agents" / "skills"
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


@pytest.fixture(scope="module")
def checkout(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str]:
    from make_fixture_repos import build_fixture_repo

    dest = tmp_path_factory.mktemp("intent-checkout")
    sha = build_fixture_repo(FIXTURE_SRC, dest)
    return dest, sha


def _seed_run(db_engine, sha: str) -> str:  # type: ignore[no-untyped-def]
    from codeatlas.db import repositories as repo

    with Session(db_engine) as s:
        repository = repo.ensure_repository(s, repository_id="local/kvstore", provider="local")
        revision = repo.ensure_revision(s, repository_id=repository.id, sha=sha)
        run = repo.create_run(
            s, repository_id=repository.id, kind="repository", head_revision_id=revision.id
        )
        s.commit()
        return run.id


class TestIntentNode:
    def test_reconstructs_requirements_with_verified_citations(
        self, db_engine, checkout: tuple[Path, str], tmp_path: Path
    ) -> None:  # type: ignore[no-untyped-def]
        path, sha = checkout
        run_id = _seed_run(db_engine, sha)
        package, problems, artifact_sha = reconstruct_intent(
            engine=ReplayEngine(CASSETTES),
            registry=SkillRegistry.load(SKILLS_DIR),
            run_id=run_id,
            revision_sha=sha,
            checkout=path,
            db_engine=db_engine,
            cas=ArtifactStore(tmp_path / "objects"),
            budget=TokenBudget(max_run_tokens=1_000_000, max_task_tokens=200_000),
        )

        assert package.requirements, "the fixture has a SPEC.md and an ADR"
        assert artifact_sha.startswith("sha256:")
        assert problems == [], f"unverifiable citations: {problems}"

        cited = [r for r in package.requirements if r.source_kind in ("spec", "adr")]
        assert cited, "at least one requirement must come from a document"
        valid = {s.path for s in collect_intent_sources(path)}
        for requirement in cited:
            assert requirement.source_ref is not None
            assert requirement.source_ref.split("#")[0] in valid

    def test_invocation_is_persisted(
        self, db_engine, checkout: tuple[Path, str], tmp_path: Path
    ) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.db.tables import AgentInvocationRow

        path, sha = checkout
        run_id = _seed_run(db_engine, sha)
        reconstruct_intent(
            engine=ReplayEngine(CASSETTES),
            registry=SkillRegistry.load(SKILLS_DIR),
            run_id=run_id,
            revision_sha=sha,
            checkout=path,
            db_engine=db_engine,
            cas=ArtifactStore(tmp_path / "objects"),
        )
        with Session(db_engine) as s:
            row = s.scalar(select(AgentInvocationRow).where(AgentInvocationRow.run_id == run_id))
            assert row is not None
            assert row.skill_id == "intent-reconstructor"
            assert row.engine == "replay"
            assert row.status == "succeeded"
            assert row.result_sha256 is not None


class TestNoSpecRepository:
    def test_missing_spec_yields_unavailable_not_fabrication(
        self, db_engine, tmp_path: Path
    ) -> None:  # type: ignore[no-untyped-def]
        """A repository with no documents must not produce invented requirements."""
        from make_fixture_repos import build_fixture_repo

        bare_src = tmp_path / "bare-src"
        (bare_src / "src").mkdir(parents=True)
        (bare_src / "src" / "main.rs").write_text("fn main() {}\n", encoding="utf-8")
        repo_dir = tmp_path / "bare-repo"
        sha = build_fixture_repo(bare_src, repo_dir)
        run_id = _seed_run(db_engine, sha)

        # No documents => the node short-circuits without dispatching an agent.
        package, problems, _ = reconstruct_intent(
            engine=ReplayEngine(tmp_path / "no-cassettes"),
            registry=SkillRegistry.load(SKILLS_DIR),
            run_id=run_id,
            revision_sha=sha,
            checkout=repo_dir,
            db_engine=db_engine,
            cas=ArtifactStore(tmp_path / "objects2"),
        )
        assert problems == []
        assert len(package.requirements) == 1
        assert package.requirements[0].source_kind == "unavailable"
        assert package.requirements[0].source_ref is None


class TestCitationDowngrade:
    def test_hallucinated_citation_is_downgraded_to_inferred(
        self, db_engine, checkout: tuple[Path, str], tmp_path: Path
    ) -> None:  # type: ignore[no-untyped-def]
        """An agent citing a document that does not exist must not be trusted."""
        path, sha = checkout
        run_id = _seed_run(db_engine, sha)

        cassettes = tmp_path / "bad-cassettes"
        engine = ReplayEngine(cassettes)
        registry = SkillRegistry.load(SKILLS_DIR)
        skill = registry.get("intent-reconstructor")
        sources = collect_intent_sources(path)
        cas = ArtifactStore(tmp_path / "objects3")
        inputs = {"documents": cas.put_json([s.path for s in sources])}
        task = build_task(
            skill=skill, run_id=run_id, revision_sha=sha, checkout=path, inputs=inputs
        )
        engine.record(
            task,
            AgentResult(
                task_id=task.task_id,
                status="succeeded",
                output={
                    "schemaVersion": "1.0.0",
                    "requirements": [
                        {
                            "id": "REQ-001",
                            "sourceKind": "spec",
                            "sourceRef": "docs/DOES-NOT-EXIST.md#L1-L3",
                            "text": "invented obligation",
                            "acceptanceCriteria": [],
                        }
                    ],
                    "nonGoals": [],
                    "compatibilityObligations": [],
                    "unresolvedQuestions": [],
                },
                command_receipts=[CommandReceipt(command="rg --files", exit_code=0, duration_ms=1)],
                usage=UsageStats(
                    prompt_tokens=10,
                    completion_tokens=10,
                    cost_usd=None,
                    wall_ms=1,
                    model_id="replay",
                ),
            ),
        )

        package, problems, _ = reconstruct_intent(
            engine=engine,
            registry=registry,
            run_id=run_id,
            revision_sha=sha,
            checkout=path,
            db_engine=db_engine,
            cas=cas,
        )
        assert problems, "a citation to a non-existent document must be reported"
        assert package.requirements[0].source_kind == "inferred"
        assert package.requirements[0].source_ref is None
