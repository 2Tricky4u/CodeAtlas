"""The change explainer, replayed against its cassette (P3). Markers: subproc + pg.

The explanation is the only artifact here a model writes, so the thing worth
testing is not its prose but its discipline: does every surviving claim point at
something this run actually measured, and is anything that does not point at
such a thing *gone* rather than hedged.

Replayed, not live (ADR-0012), so the assertions are about wiring, contracts and
the validator — never about model quality.
"""

from __future__ import annotations

import shutil
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
    for tool in ("cargo-public-api", "cargo-semver-checks", "rustup"):
        if shutil.which(tool) is None:
            pytest.skip(f"{tool} not on PATH")
    mig = migrator_engine(test=True)
    downgrade_base(mig)
    upgrade_head(mig)
    mig.dispose()
    engine = app_engine(test=True)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def explained(db_engine, tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    """Run the explainer over the API-change fixture, replaying the cassette."""
    from make_fixture_repos import build_api_change_fixture_repo
    from sqlalchemy.orm import Session

    from codeatlas.agents.registry import SkillRegistry
    from codeatlas.agents.replay_engine import ReplayEngine
    from codeatlas.change.analysis import assemble_change_analysis
    from codeatlas.db import repositories as repo
    from codeatlas.review.citations import CitationIndex
    from codeatlas.review.explainer import explain_change

    root = tmp_path_factory.mktemp("explainer")
    source = root / "repo"
    base_sha, head_sha = build_api_change_fixture_repo(FIXTURE_SRC, source)
    analysis = assemble_change_analysis(source, base_sha, head_sha, workdir=root)

    cas = ArtifactStore(root / "objects")
    with Session(db_engine) as session:
        repository = repo.ensure_repository(session, repository_id="local/kv-x", provider="github")
        head = repo.ensure_revision(session, repository_id=repository.id, sha=head_sha)
        base = repo.ensure_revision(session, repository_id=repository.id, sha=base_sha)
        run = repo.create_run(
            session,
            repository_id=repository.id,
            kind="pr",
            head_revision_id=head.id,
            base_revision_id=base.id,
        )
        session.commit()
        run_id, head_id, base_id = run.id, head.id, base.id

    # Paths come straight from the analysis rather than the file table: this
    # test exercises the explainer, not the pipeline's bookkeeping.
    paths = {
        sha: {n.location.path for n in graph.nodes if n.location}
        for sha, graph in ((base_sha, analysis.base_graph), (head_sha, analysis.head_graph))
    }
    index = CitationIndex(
        base_revision=base_sha,
        head_revision=head_sha,
        paths_by_revision=paths,
        edge_ids={e.id for e in [*analysis.diff.edges.added, *analysis.diff.edges.removed]},
        api_items={
            item
            for package in analysis.api_change.packages
            for item in [*package.added, *package.removed]
        },
        impact_keys={i.stable_key for i in analysis.impact.impacted},
    )

    def read_lines(revision: str, path: str) -> int:
        tree = analysis.base_tree if revision == base_sha else analysis.head_tree
        return len((tree / path).read_text(encoding="utf-8", errors="replace").splitlines())

    explanation, dropped = explain_change(
        engine=ReplayEngine(CASSETTES),
        registry=SkillRegistry.load(REPO_ROOT / ".agents" / "skills"),
        run_id=run_id,
        head_sha=head_sha,
        checkout=analysis.head_tree,
        db_engine=db_engine,
        cas=cas,
        diff_text=analysis.diff_text,
        diff=analysis.diff,
        api_change=analysis.api_change,
        impact=analysis.impact,
        index=index,
        read_lines=read_lines,
    )
    assert explanation is not None, "the cassette should have replayed"
    return explanation, dropped, index, run_id, (base_id, head_id)


class TestTheExplanationIsUsable:
    def test_it_says_what_the_change_did(self, explained) -> None:  # type: ignore[no-untyped-def]
        explanation, _, _, _, _ = explained
        assert explanation.summary
        assert explanation.claim_count > 0

    def test_it_covers_before_and_after(self, explained) -> None:  # type: ignore[no-untyped-def]
        """The question the whole phase exists to answer."""
        explanation, _, _, _, _ = explained
        sections = {section.id for section in explanation.sections}
        assert {"before", "after"} <= sections

    def test_no_diagram_is_offered_for_a_change_that_moved_no_interaction(self, explained) -> None:  # type: ignore[no-untyped-def]
        explanation, _, _, _, _ = explained
        assert explanation.sequence_diagram is None


class TestEveryClaimIsCheckable:
    def test_every_surviving_claim_carries_a_resolvable_citation(self, explained) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.review.citations import citation_problem

        explanation, _, index, _, _ = explained
        for section in explanation.sections:
            for claim in section.claims:
                assert claim.citations, claim.text
                for citation in claim.citations:
                    assert citation_problem(citation, index) is None, (claim.text, citation)

    def test_revalidating_changes_nothing(self, explained) -> None:  # type: ignore[no-untyped-def]
        """Validation is a filter, so running it twice must be a no-op."""
        from codeatlas.review.citations import validate_explanation

        explanation, _, index, _, _ = explained
        again, dropped_again = validate_explanation(explanation, index)
        assert dropped_again == []
        assert again.claim_count == explanation.claim_count

    def test_the_structural_section_cites_real_edges(self, explained) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.models.explanation import EdgeCitation

        explanation, _, index, _, _ = explained
        structural = next((s for s in explanation.sections if s.id == "structural"), None)
        if structural is None:
            pytest.skip("the explainer chose not to write a structural section")
        cited = [
            c.edge_id
            for claim in structural.claims
            for c in claim.citations
            if isinstance(c, EdgeCitation)
        ]
        assert cited, "a structural section without an edge citation explains nothing"
        assert set(cited) <= index.edge_ids


class TestTheInvocationIsRecorded:
    def test_the_agent_call_left_a_row(self, explained, db_engine) -> None:  # type: ignore[no-untyped-def]
        from sqlalchemy import select
        from sqlalchemy.orm import Session

        from codeatlas.db.tables import AgentInvocationRow

        _, _, _, run_id, _ = explained
        with Session(db_engine) as session:
            rows = session.scalars(
                select(AgentInvocationRow).where(AgentInvocationRow.run_id == run_id)
            ).all()
        assert [r.skill_id for r in rows] == ["change-explainer"]
        assert rows[0].status == "succeeded"


class TestTheCondensedFormForAPullRequestComment:
    def test_it_leads_with_the_summary_and_bounds_its_length(self, explained) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.review.explainer import condensed_markdown

        explanation, _, _, _, _ = explained
        markdown = condensed_markdown(explanation, limit=4)
        assert markdown.startswith(explanation.summary)
        assert markdown.count("\n- ") <= 4

    def test_it_states_what_it_left_out(self, explained) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.review.explainer import condensed_markdown

        explanation, _, _, _, _ = explained
        markdown = condensed_markdown(explanation, limit=2)
        assert "further point" in markdown
