"""The code answerer, replayed against its cassette (H6). Markers: subproc + pg.

Same shape as the other three replay suites: the assertions are about the
discipline — every surviving claim resolves against the revision, an invented
claim spliced in does not survive — never about the prose.
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


@pytest.fixture(scope="module")
def answered(db_engine, tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    from make_fixture_repos import build_fixture_repo
    from sqlalchemy.orm import Session

    from codeatlas.agents.registry import SkillRegistry
    from codeatlas.agents.replay_engine import ReplayEngine
    from codeatlas.db import repositories as repo
    from codeatlas.extractors.rust.cargo_meta import CargoMetadataExtractor
    from codeatlas.extractors.rust.ra_scip import RaScipExtractor
    from codeatlas.graph.merge import merge_fragments
    from codeatlas.project.answers import answer_question, build_answer_index

    root = tmp_path_factory.mktemp("answers")
    checkout = root / "repo"
    sha = build_fixture_repo(FIXTURE_SRC, checkout)

    cargo_fragment, _ = CargoMetadataExtractor().extract(checkout, sha)
    scip_fragment, _ = RaScipExtractor().extract(checkout, sha)
    graph = merge_fragments(
        repository_id="local/kvstore", head_sha=sha, fragments=[cargo_fragment, scip_fragment]
    )
    paths = {node.location.path for node in graph.nodes if node.location}
    index = build_answer_index(graph, "kvstore/src/cache.rs", paths)

    cas = ArtifactStore(root / "objects")
    with Session(db_engine) as session:
        repository = repo.ensure_repository(session, repository_id="local/kv-a", provider="github")
        revision = repo.ensure_revision(session, repository_id=repository.id, sha=sha)
        run = repo.create_run(
            session, repository_id=repository.id, kind="repository", head_revision_id=revision.id
        )
        session.commit()
        run_id = run.id

    answer, dropped = answer_question(
        engine=ReplayEngine(CASSETTES),
        registry=SkillRegistry.load(REPO_ROOT / ".agents" / "skills"),
        run_id=run_id,
        revision_sha=sha,
        checkout=checkout,
        db_engine=db_engine,
        cas=cas,
        scope="kvstore/src/cache.rs",
        question="what does eviction actually remove?",
        index=index,
    )
    assert answer is not None, "the cassette should have replayed"
    return answer, dropped, index


class TestTheAnswerIsCheckable:
    def test_it_answered_rather_than_refused(self, answered) -> None:  # type: ignore[no-untyped-def]
        answer, _, _ = answered
        assert answer.refused is None
        assert answer.claims

    def test_every_surviving_claim_resolves(self, answered) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.project.narrative import project_citation_problem

        answer, _, index = answered
        for claim in answer.claims:
            for citation in claim.citations:
                assert project_citation_problem(citation, index) is None, claim.text

    def test_an_invented_claim_does_not_survive(self, answered) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.models.code_answer import AnswerClaim
        from codeatlas.models.project_explanation import ProjectSourceCitation
        from codeatlas.project.answers import validate_answer

        answer, _, index = answered
        poisoned = answer.model_copy(
            update={
                "claims": [
                    *answer.claims,
                    AnswerClaim(
                        text="The scheduler compensates.",
                        citations=[ProjectSourceCitation(path="kvstore/src/sched.rs")],
                    ),
                ]
            }
        )
        cleaned, dropped = validate_answer(poisoned, index)
        assert [d.text for d in dropped] == ["The scheduler compensates."]
        assert all("scheduler" not in claim.text for claim in cleaned.claims)
