"""Reviewer fan-out against the fixture answer key (M10 acceptance).

Replay-backed, so it is deterministic and quota-free. This measures the recorded
reviewers' recall on the planted defects and their restraint on the sound
decoys. It does not measure the live model — cassettes freeze one run; live
quality is checked separately.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from codeatlas.agents.registry import SkillRegistry
from codeatlas.agents.replay_engine import ReplayEngine
from codeatlas.artifacts.store import ArtifactStore
from codeatlas.extractors.rust.cargo_meta import CargoMetadataExtractor
from codeatlas.extractors.rust.ra_scip import RaScipExtractor
from codeatlas.graph.merge import merge_fragments
from codeatlas.models.intent import IntentPackage
from codeatlas.review.evaluate import load_manifest, score_findings
from codeatlas.review.reviewers import (
    REVIEWER_SKILLS,
    build_reviewer_inputs,
    run_reviewers,
    slice_graph_for_review,
)

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
def review(db_engine, tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    """Run the full reviewer fan-out once, from replayed cassettes."""
    from make_fixture_repos import build_fixture_repo

    from codeatlas.db import repositories as repo

    tmp = tmp_path_factory.mktemp("review")
    checkout = tmp / "repo"
    sha = build_fixture_repo(FIXTURE_SRC, checkout)
    cas = ArtifactStore(tmp / "objects")

    with Session(db_engine) as s:
        repository = repo.ensure_repository(s, repository_id="local/kvstore", provider="local")
        revision = repo.ensure_revision(s, repository_id=repository.id, sha=sha)
        run = repo.create_run(
            s, repository_id=repository.id, kind="repository", head_revision_id=revision.id
        )
        s.commit()
        run_id = run.id

    cargo_fragment, _ = CargoMetadataExtractor().extract(checkout, sha)
    scip_fragment, _ = RaScipExtractor().extract(checkout, sha)
    graph = merge_fragments(
        repository_id="local/kvstore", head_sha=sha, fragments=[cargo_fragment, scip_fragment]
    )
    source_paths = sorted(
        p.relative_to(checkout).as_posix()
        for p in checkout.rglob("*.rs")
        if "target" not in p.parts
    )
    cassette = next(CASSETTES.glob("intent-reconstructor-*.json"))
    intent = IntentPackage.model_validate(
        json.loads(cassette.read_text(encoding="utf-8"))["result"]["output"]
    )
    inputs = build_reviewer_inputs(
        cas=cas,
        intent=intent,
        source_paths=source_paths,
        graph_slice=slice_graph_for_review(graph, source_paths),
    )

    outcome = run_reviewers(
        engine=ReplayEngine(CASSETTES),
        registry=SkillRegistry.load(SKILLS_DIR),
        run_id=run_id,
        revision_sha=sha,
        checkout=checkout,
        inputs=inputs,
        db_engine=db_engine,
        cas=cas,
    )
    return outcome, run_id, checkout


class TestFanOut:
    def test_all_reviewers_completed(self, review) -> None:  # type: ignore[no-untyped-def]
        outcome, _, _ = review
        assert outcome.failed_skills == [], f"degraded coverage: {outcome.failed_skills}"
        assert outcome.findings

    def test_finding_ids_are_unique_after_merge(self, review) -> None:  # type: ignore[no-untyped-def]
        outcome, _, _ = review
        ids = [f.finding_id for f in outcome.findings]
        assert len(ids) == len(set(ids))

    def test_every_reviewer_contributed_its_own_category(self, review) -> None:  # type: ignore[no-untyped-def]
        outcome, _, _ = review
        skills = {f.discovered_by_skill for f in outcome.findings}
        assert skills == set(REVIEWER_SKILLS), f"missing reviewers: {set(REVIEWER_SKILLS) - skills}"

    def test_all_findings_are_labeled_as_inference(self, review) -> None:  # type: ignore[no-untyped-def]
        """A reviewer produces inference, never fact — the provenance wall."""
        outcome, _, _ = review
        for finding in outcome.findings:
            assert finding.evidence
            assert all(e.kind == "llm-inference" for e in finding.evidence), finding.finding_id

    def test_every_finding_cites_a_path_in_the_reviewed_tree(self, review) -> None:  # type: ignore[no-untyped-def]
        outcome, _, checkout = review
        for finding in outcome.findings:
            assert (checkout / finding.location.path).exists(), finding.location.path

    def test_invocations_persisted_for_each_reviewer(self, review, db_engine) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.db.tables import AgentInvocationRow

        _, run_id, _ = review
        with Session(db_engine) as s:
            rows = s.scalars(
                select(AgentInvocationRow).where(AgentInvocationRow.run_id == run_id)
            ).all()
            assert {r.skill_id for r in rows} == set(REVIEWER_SKILLS)
            assert all(r.status == "succeeded" for r in rows)


class TestRecallAgainstAnswerKey:
    def test_finds_at_least_four_of_five_planted_defects(self, review) -> None:  # type: ignore[no-untyped-def]
        outcome, _, _ = review
        manifest = load_manifest(FIXTURE_SRC)
        score = score_findings(outcome.findings, manifest, source_root=FIXTURE_SRC)
        assert len(score.matched) >= 4, (
            f"recall {score.recall:.0%}; missed {score.missed}; "
            f"unmatched reports {score.unmatched_findings}"
        )

    def test_security_defect_is_found_by_the_security_reviewer(self, review) -> None:  # type: ignore[no-untyped-def]
        """B2 (path traversal) must be reported, and by the right specialist."""
        outcome, _, _ = review
        manifest = load_manifest(FIXTURE_SRC)
        score = score_findings(outcome.findings, manifest, source_root=FIXTURE_SRC)
        assert "B2" in score.matched
        finding = next(f for f in outcome.findings if f.finding_id == score.matched["B2"])
        assert finding.category == "security"

    def test_architecture_violation_is_found_and_cites_the_decision(self, review) -> None:  # type: ignore[no-untyped-def]
        """B5 violates an accepted ADR; the finding should point at it."""
        outcome, _, _ = review
        manifest = load_manifest(FIXTURE_SRC)
        score = score_findings(outcome.findings, manifest, source_root=FIXTURE_SRC)
        assert "B5" in score.matched
        finding = next(f for f in outcome.findings if f.finding_id == score.matched["B5"])
        assert finding.category == "architecture"

    def test_sound_decoys_are_not_reported(self, review) -> None:  # type: ignore[no-untyped-def]
        """saturating_sub and the bounds-checked unsafe block are correct code."""
        outcome, _, _ = review
        manifest = load_manifest(FIXTURE_SRC)
        score = score_findings(outcome.findings, manifest, source_root=FIXTURE_SRC)
        assert score.decoys_reported == [], (
            f"reported sound code as defective: {score.decoys_reported}"
        )

    def test_noise_is_bounded(self, review) -> None:  # type: ignore[no-untyped-def]
        """Unmatched findings are not automatically wrong, but a flood is."""
        outcome, _, _ = review
        manifest = load_manifest(FIXTURE_SRC)
        score = score_findings(outcome.findings, manifest, source_root=FIXTURE_SRC)
        assert len(score.unmatched_findings) <= 8, (
            f"{len(score.unmatched_findings)} unmatched findings: {score.unmatched_findings}"
        )
