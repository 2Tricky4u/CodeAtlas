"""Cross-run finding memory, end to end at the stage level (ADR-0016). Marker: pg.

The whole point is only observable across two validations: run 1's agent
rejection is recorded, run 2 suppresses the recurring candidate without
spending a dispatch, and an edited file re-opens the question. The pipeline
wiring above this (FileRow blobs, repository threading) is exercised by the
live runs; what must be airtight is the mechanics — record, match, suppress,
persist, fail open.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from codeatlas.agents.registry import SkillRegistry
from codeatlas.artifacts.store import ArtifactStore
from codeatlas.db.tables import FindingMemoryRow, FindingRow
from codeatlas.models.findings import Finding
from codeatlas.models.graph import (
    Evidence,
    GraphNode,
    ProjectGraph,
    RepositoryRef,
    RevisionRef,
    SourceLocation,
)
from codeatlas.pipeline.deps import PipelineDeps
from codeatlas.pipeline.review_stages import ReviewContext, _persist_findings
from codeatlas.validation.memory import FindingMemory
from codeatlas.validation.validator import validate_findings
from codeatlas.verify.parse import VerificationIndex

pytestmark = pytest.mark.pg

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / ".agents" / "skills"
sys.path.insert(0, str(REPO_ROOT / "tests"))

from support.engines import StubEngine  # noqa: E402

LSP = Evidence(kind="language-server", producer="rust-analyzer", confidence=1.0)
BLOB = "b" * 40
PATH = "kvstore/src/api.rs"


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


def _graph(sha: str) -> ProjectGraph:
    return ProjectGraph(
        repository=RepositoryRef(id="local/kvstore"),
        revision=RevisionRef(head=sha),
        nodes=[
            GraphNode(
                id="sym:scip/handle_request().",
                kind="function",
                label="handle_request",
                location=SourceLocation(path=PATH, start_line=20, end_line=45),
                evidence=[LSP],
            )
        ],
        edges=[],
    )


def _run_id(db_engine, sha: str) -> str:  # type: ignore[no-untyped-def]
    from codeatlas.db import repositories as repo

    with Session(db_engine) as s:
        repository = repo.ensure_repository(s, repository_id="local/kvstore", provider="local")
        revision = repo.ensure_revision(s, repository_id=repository.id, sha=sha)
        run = repo.create_run(
            s, repository_id=repository.id, kind="repository", head_revision_id=revision.id
        )
        s.commit()
        return run.id


def _finding(fid: str, claim: str, start: int = 28, end: int = 30) -> Finding:
    return Finding(
        finding_id=fid,
        category="correctness",
        discovered_by_skill="reviewer-correctness",
        skill_version="1.1.0",
        severity="high",
        confidence=0.9,
        claim=claim,
        location=SourceLocation(path=PATH, start_line=start, end_line=end),
        evidence=[Evidence(kind="llm-inference", producer="reviewer-correctness", confidence=0.9)],
    )


def _rejection_payload(fid: str) -> dict:  # type: ignore[type-arg]
    return {
        "findingId": fid,
        "status": "rejected",
        "severity": "high",
        "confidence": 0.9,
        "introducedByChange": False,
        "location": {"path": PATH, "startLine": 28, "endLine": 30},
        "claim": "c",
        "evidence": [],
        "counterEvidenceChecked": ["the caller's bounds check"],
        "publicationEligible": False,
        "reason": "the caller validates the request before this parse, so the panic is unreachable",
    }


def _validate(  # type: ignore[no-untyped-def]
    db_engine,
    run_id: str,
    sha: str,
    finding: Finding,
    memory: FindingMemory,
    engine,
    tmp_path: Path,
):
    return validate_findings(
        findings=[finding],
        index=VerificationIndex.build([], []),
        file_lengths={PATH: 60},
        engine=engine,
        registry=SkillRegistry.load(SKILLS_DIR),
        run_id=run_id,
        revision_sha=sha,
        checkout=tmp_path,
        db_engine=db_engine,
        cas=ArtifactStore(tmp_path / "objects"),
        memory=memory,
    )


def _persist(db_engine, run_id: str, sha: str, finding: Finding, outcome, memory, tmp_path):  # type: ignore[no-untyped-def]
    deps = PipelineDeps(
        engine=db_engine,
        workdir=tmp_path / "wd",
        cas=ArtifactStore(tmp_path / "objects"),
        checkpoint_path=tmp_path / "wd" / "checkpoints" / "pipeline.sqlite",
    )
    ctx = ReviewContext(run_id=run_id, revision_sha=sha, checkout=tmp_path, graph=_graph(sha))
    ctx.findings = [finding]
    ctx.validation = outcome
    _persist_findings(deps, ctx, memory=memory)


class TestTheMemoryLoop:
    def test_a_rejection_is_remembered_then_replayed_then_reopened(
        self, db_engine, tmp_path: Path
    ) -> None:  # type: ignore[no-untyped-def]
        sha = "a" * 40
        graph = _graph(sha)

        # Run 1: the agent rejects; persistence records the memory row.
        run1 = _run_id(db_engine, sha)
        with Session(db_engine) as s:
            memory1 = FindingMemory.load(s, "local/kvstore", blob_shas={PATH: BLOB}, graph=graph)
        first = _finding("F-0001", "handle_request panics on malformed put")
        engine1 = StubEngine(lambda task: _rejection_payload("F-0001"))
        outcome1 = _validate(db_engine, run1, sha, first, memory1, engine1, tmp_path)
        assert outcome1.results["F-0001"].status == "rejected"
        assert "F-0001" in outcome1.dispatched
        _persist(db_engine, run1, sha, first, outcome1, memory1, tmp_path)

        with Session(db_engine) as s:
            rows = s.scalars(select(FindingMemoryRow)).all()
        assert len(rows) == 1
        assert rows[0].file_blob_sha == BLOB
        assert rows[0].decided_in_run == run1

        # Run 2, byte-identical file: reworded claim, shifted-but-overlapping
        # span. Suppressed — the engine is never consulted.
        run2 = _run_id(db_engine, sha)
        with Session(db_engine) as s:
            memory2 = FindingMemory.load(s, "local/kvstore", blob_shas={PATH: BLOB}, graph=graph)
        calls = {"n": 0}

        def _count(task):  # type: ignore[no-untyped-def]
            calls["n"] += 1
            return _rejection_payload("F-0001")

        second = _finding("F-0001", "a panic is reachable in handle_request", start=29, end=31)
        outcome2 = _validate(db_engine, run2, sha, second, memory2, StubEngine(_count), tmp_path)
        assert calls["n"] == 0, "a remembered rejection must not spend a dispatch"
        assert "F-0001" not in outcome2.results
        remembered = outcome2.suppressed["F-0001"]
        assert remembered.decided_in_run == run1
        assert "unreachable" in remembered.reason

        # The suppressed row persists with its provenance, and no new memory
        # row appears (append-only, same key).
        _persist(db_engine, run2, sha, second, outcome2, memory2, tmp_path)
        with Session(db_engine) as s:
            row = s.scalar(
                select(FindingRow).where(
                    FindingRow.run_id == run2, FindingRow.finding_id == "F-0001"
                )
            )
            memory_rows = s.scalars(select(FindingMemoryRow)).all()
        assert row is not None
        assert row.status == "suppressed"
        assert row.publication_eligible is False
        assert row.validation is not None
        assert row.validation["decidedInRun"] == run1
        assert len(memory_rows) == 1

        # Run 3, the file was edited: a different blob fails open and the
        # engine is consulted again.
        run3 = _run_id(db_engine, sha)
        with Session(db_engine) as s:
            memory3 = FindingMemory.load(
                s, "local/kvstore", blob_shas={PATH: "c" * 40}, graph=graph
            )
        outcome3 = _validate(
            db_engine,
            run3,
            sha,
            _finding("F-0001", "same claim"),
            memory3,
            StubEngine(_count),
            tmp_path,
        )
        assert calls["n"] == 1, "an edited file must re-open the question"
        assert outcome3.results["F-0001"].status == "rejected"

    def test_a_different_defect_in_the_same_function_is_validated(
        self, db_engine, tmp_path: Path
    ) -> None:  # type: ignore[no-untyped-def]
        """Same fingerprint bucket, non-overlapping span: no suppression."""
        sha = "d" * 40
        graph = _graph(sha)
        run1 = _run_id(db_engine, sha)
        with Session(db_engine) as s:
            memory = FindingMemory.load(s, "local/kvstore", blob_shas={PATH: BLOB}, graph=graph)
        first = _finding("F-0001", "first defect", start=28, end=30)
        outcome = _validate(
            db_engine,
            run1,
            sha,
            first,
            memory,
            StubEngine(lambda task: _rejection_payload("F-0001")),
            tmp_path,
        )
        _persist(db_engine, run1, sha, first, outcome, memory, tmp_path)

        run2 = _run_id(db_engine, sha)
        with Session(db_engine) as s:
            memory2 = FindingMemory.load(s, "local/kvstore", blob_shas={PATH: BLOB}, graph=graph)
        calls = {"n": 0}

        def _count(task):  # type: ignore[no-untyped-def]
            calls["n"] += 1
            return _rejection_payload("F-0001")

        other = _finding("F-0001", "different defect, same function", start=40, end=42)
        outcome2 = _validate(db_engine, run2, sha, other, memory2, StubEngine(_count), tmp_path)
        assert calls["n"] == 1
        assert outcome2.suppressed == {}
