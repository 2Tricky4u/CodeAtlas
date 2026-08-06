"""The project explainer, replayed against its cassette (P5c). Markers: subproc + pg.

The narrative is the only part of the project map a model writes, so what is
worth testing is not its prose but its discipline: does every surviving claim
point at something the deterministic overview actually measured, and is anything
that does not *gone* rather than hedged.

Replayed, not live (ADR-0012), so the assertions are about wiring, contracts and
the validator — never about model quality.
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
def narrated(db_engine, tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    """Narrate the fixture crate from its real overview, replaying the cassette."""
    from make_fixture_repos import build_fixture_repo
    from sqlalchemy.orm import Session

    from codeatlas.agents.registry import SkillRegistry
    from codeatlas.agents.replay_engine import ReplayEngine
    from codeatlas.db import repositories as repo
    from codeatlas.extractors.rust.cargo_meta import CargoMetadataExtractor
    from codeatlas.extractors.rust.ra_scip import RaScipExtractor
    from codeatlas.graph.merge import merge_fragments
    from codeatlas.project.narrative import build_project_index, explain_project
    from codeatlas.project.overview import build_overview

    root = tmp_path_factory.mktemp("narrative")
    checkout = root / "repo"
    sha = build_fixture_repo(FIXTURE_SRC, checkout)

    cargo_fragment, _ = CargoMetadataExtractor().extract(checkout, sha)
    scip_fragment, _ = RaScipExtractor().extract(checkout, sha)
    graph = merge_fragments(
        repository_id="local/kvstore", head_sha=sha, fragments=[cargo_fragment, scip_fragment]
    )
    overview = build_overview(graph, repository_id="local/kvstore")

    paths = {node.location.path for node in graph.nodes if node.location}
    index = build_project_index(overview, paths=paths)

    def read_lines(path: str) -> int:
        return len((checkout / path).read_text(encoding="utf-8", errors="replace").splitlines())

    cas = ArtifactStore(root / "objects")
    with Session(db_engine) as session:
        repository = repo.ensure_repository(session, repository_id="local/kv-n", provider="github")
        revision = repo.ensure_revision(session, repository_id=repository.id, sha=sha)
        run = repo.create_run(
            session,
            repository_id=repository.id,
            kind="repository",
            head_revision_id=revision.id,
        )
        session.commit()
        run_id = run.id

    explanation, dropped = explain_project(
        engine=ReplayEngine(CASSETTES),
        registry=SkillRegistry.load(REPO_ROOT / ".agents" / "skills"),
        run_id=run_id,
        revision_sha=sha,
        checkout=checkout,
        db_engine=db_engine,
        cas=cas,
        overview=overview,
        index=index,
        read_lines=read_lines,
    )
    assert explanation is not None, "the cassette should have replayed"
    return explanation, dropped, index, overview, run_id


class TestTheNarrativeIsUsable:
    def test_it_says_what_the_project_is(self, narrated) -> None:  # type: ignore[no-untyped-def]
        explanation, _, _, _, _ = narrated
        assert explanation.summary
        assert explanation.claim_count > 0

    def test_it_tells_a_newcomer_where_to_start(self, narrated) -> None:  # type: ignore[no-untyped-def]
        """The question the project half of this phase exists to answer."""
        explanation, _, _, _, _ = narrated
        sections = {section.id for section in explanation.sections}
        assert sections & {"what", "entry"}, sections


class TestEveryClaimIsCheckable:
    def test_every_surviving_claim_carries_a_resolvable_citation(self, narrated) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.project.narrative import project_citation_problem

        explanation, _, index, _, _ = narrated
        for section in explanation.sections:
            for claim in section.claims:
                assert claim.citations, claim.text
                for citation in claim.citations:
                    assert project_citation_problem(citation, index) is None, (
                        claim.text,
                        citation,
                    )

    def test_revalidating_changes_nothing(self, narrated) -> None:  # type: ignore[no-untyped-def]
        """Validation is a filter, so running it twice must be a no-op."""
        from codeatlas.project.narrative import validate_project_explanation

        explanation, _, index, _, _ = narrated
        again, dropped_again = validate_project_explanation(explanation, index)
        assert dropped_again == []
        assert again.claim_count == explanation.claim_count

    def test_a_module_citation_names_a_module_the_overview_measured(self, narrated) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.models.project_explanation import ModuleCitation

        explanation, _, _, overview, _ = narrated
        keys = {module.key for module in overview.modules}
        cited = [
            citation.key
            for section in explanation.sections
            for claim in section.claims
            for citation in claim.citations
            if isinstance(citation, ModuleCitation)
        ]
        assert set(cited) <= keys

    def test_a_cycle_citation_matches_a_cycle_that_was_found(self, narrated) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.models.project_explanation import CycleCitation

        explanation, _, _, overview, _ = narrated
        found = {frozenset(cycle.members) for cycle in overview.cycles}
        cited = [
            frozenset(citation.members)
            for section in explanation.sections
            for claim in section.claims
            for citation in claim.citations
            if isinstance(citation, CycleCitation)
        ]
        assert all(members in found for members in cited)


class TestAnInventedClaimIsDeleted:
    def test_a_module_the_overview_never_saw_does_not_survive(self, narrated) -> None:  # type: ignore[no-untyped-def]
        """The failure mode this whole stage exists to prevent.

        A newcomer reading this page has no independent picture of the project
        to catch an invention with; the validator is the only thing standing
        between them and a confidently-named module that does not exist.
        """
        from codeatlas.models.project_explanation import (
            ModuleCitation,
            ProjectClaim,
            ProjectSection,
        )
        from codeatlas.project.narrative import validate_project_explanation

        explanation, _, index, _, _ = narrated
        poisoned = explanation.model_copy(
            update={
                "sections": [
                    *explanation.sections,
                    ProjectSection(
                        id="hotspots",
                        title="What everything leans on",
                        claims=[
                            ProjectClaim(
                                text="The scheduler coordinates every write.",
                                citations=[ModuleCitation(key="kvstore/src/scheduler.rs")],
                            )
                        ],
                    ),
                ]
            }
        )
        cleaned, dropped = validate_project_explanation(poisoned, index)
        assert [d.text for d in dropped] == ["The scheduler coordinates every write."]
        assert all(
            "scheduler" not in claim.text
            for section in cleaned.sections
            for claim in section.claims
        )


class TestTheInvocationIsRecorded:
    def test_the_agent_call_left_a_row(self, narrated, db_engine) -> None:  # type: ignore[no-untyped-def]
        from sqlalchemy import select
        from sqlalchemy.orm import Session

        from codeatlas.db.tables import AgentInvocationRow

        _, _, _, _, run_id = narrated
        with Session(db_engine) as session:
            rows = session.scalars(
                select(AgentInvocationRow).where(AgentInvocationRow.run_id == run_id)
            ).all()
        assert [r.skill_id for r in rows] == ["project-explainer"]
        assert rows[0].status == "succeeded"
