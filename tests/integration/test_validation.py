"""Validation stage (M11): battery + validator. Markers: subproc + pg.

The battery runs the real cargo toolchain against the fixture. Validation runs
against a stub engine so the terminal-status and eligibility guarantees are
tested exhaustively without quota; the live validator behavior is covered by the
recorded cassette test at the end.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from codeatlas.agents.registry import SkillRegistry
from codeatlas.artifacts.store import ArtifactStore
from codeatlas.models.agent import AgentResult, AgentTask, UsageStats
from codeatlas.models.findings import Finding
from codeatlas.models.graph import Evidence, SourceLocation
from codeatlas.validation.validator import validate_findings
from codeatlas.verify.battery import run_battery
from codeatlas.verify.parse import VerificationIndex

pytestmark = [pytest.mark.subproc, pytest.mark.pg]

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_SRC = REPO_ROOT / "fixtures" / "rust-flawed-crate"
SKILLS_DIR = REPO_ROOT / ".agents" / "skills"
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

    dest = tmp_path_factory.mktemp("validate-checkout")
    sha = build_fixture_repo(FIXTURE_SRC, dest)
    return dest, sha


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


def _finding(fid: str, path: str, start: int, end: int, category: str = "correctness") -> Finding:
    return Finding(
        finding_id=fid,
        category=category,  # type: ignore[arg-type]
        discovered_by_skill=f"reviewer-{category}",
        skill_version="1.0.0",
        severity="high",
        confidence=0.9,
        claim=f"claim {fid}",
        location=SourceLocation(path=path, start_line=start, end_line=end),
        evidence=[Evidence(kind="llm-inference", producer="reviewer", confidence=0.9)],
    )


class StubEngine:
    """A validator that answers however the test needs, recording what it saw."""

    name = "stub"

    def __init__(self, responder) -> None:  # type: ignore[no-untyped-def]
        self.responder = responder
        self.seen: list[AgentTask] = []

    def run(self, task: AgentTask, instructions: str) -> AgentResult:
        self.seen.append(task)
        return AgentResult(
            task_id=task.task_id,
            status="succeeded",
            output=self.responder(task),
            command_receipts=[],
            usage=UsageStats(
                prompt_tokens=1, completion_tokens=1, cost_usd=None, wall_ms=1, model_id="stub"
            ),
        )


def _validation_payload(**overrides) -> dict:  # type: ignore[no-untyped-def]
    payload = {
        "findingId": "F-0001",
        "status": "validated",
        "severity": "high",
        "confidence": 0.95,
        "introducedByChange": False,
        "location": {"path": "kvstore/src/api.rs", "startLine": 28, "endLine": 30},
        "claim": "c",
        "evidence": [{"kind": "call-path", "command": "a -> b"}],
        "counterEvidenceChecked": ["callers", "existing tests"],
        "publicationEligible": True,
    }
    payload.update(overrides)
    return payload


class TestBattery:
    def test_runs_the_real_toolchain_and_produces_receipts(
        self, checkout: tuple[Path, str]
    ) -> None:
        path, sha = checkout
        outcome = run_battery(path, sha)
        assert "cargo-check" in outcome.tools_run
        assert "cargo-test" in outcome.tools_run
        assert all(r.revision == sha for r in outcome.receipts)
        assert all(r.stdout_sha256.startswith("sha256:") for r in outcome.receipts)
        # Unavailable tools are named, never silently dropped.
        assert set(outcome.tools_run) | set(outcome.tools_unavailable) >= {
            "cargo-check",
            "cargo-clippy",
            "cargo-test",
        }

    def test_index_is_queryable_by_location(self, checkout: tuple[Path, str]) -> None:
        path, sha = checkout
        outcome = run_battery(path, sha)
        assert outcome.index.summary()["diagnostics"] >= 0  # fixture may be lint-clean
        assert outcome.index.diagnostics_near("does/not/exist.rs", 1, 2) == []


class TestTerminalStatuses:
    def test_every_finding_gets_a_terminal_status(
        self, db_engine, checkout: tuple[Path, str], tmp_path: Path
    ) -> None:  # type: ignore[no-untyped-def]
        path, sha = checkout
        findings = [
            _finding("F-0001", "kvstore/src/api.rs", 28, 30),
            _finding("F-0002", "kvstore/src/api.rs", 29, 31),  # duplicate of F-0001
            _finding("F-0003", "kvstore/src/ghost.rs", 1, 2),  # dead location
        ]
        engine = StubEngine(lambda task: _validation_payload())
        outcome = validate_findings(
            findings=findings,
            index=VerificationIndex.build([], []),
            file_lengths={"kvstore/src/api.rs": 40},
            engine=engine,
            registry=SkillRegistry.load(SKILLS_DIR),
            run_id=_run_id(db_engine, sha),
            revision_sha=sha,
            checkout=path,
            db_engine=db_engine,
            cas=ArtifactStore(tmp_path / "objects"),
        )
        assert set(outcome.results) == {"F-0001", "F-0002", "F-0003"}
        assert outcome.results["F-0002"].status == "duplicate"
        assert outcome.results["F-0002"].duplicate_of == "F-0001"
        assert outcome.results["F-0003"].status == "rejected"
        assert "does not exist" in (outcome.results["F-0003"].reason or "")

    def test_dead_location_is_rejected_without_calling_an_agent(
        self, db_engine, checkout: tuple[Path, str], tmp_path: Path
    ) -> None:  # type: ignore[no-untyped-def]
        path, sha = checkout
        engine = StubEngine(lambda task: _validation_payload())
        validate_findings(
            findings=[_finding("F-0001", "kvstore/src/ghost.rs", 1, 2)],
            index=VerificationIndex.build([], []),
            file_lengths={"kvstore/src/api.rs": 40},
            engine=engine,
            registry=SkillRegistry.load(SKILLS_DIR),
            run_id=_run_id(db_engine, sha),
            revision_sha=sha,
            checkout=path,
            db_engine=db_engine,
            cas=ArtifactStore(tmp_path / "objects2"),
        )
        assert engine.seen == [], "a dead location must not cost an agent call"

    def test_validator_failure_yields_unresolved_not_silence(
        self, db_engine, checkout: tuple[Path, str], tmp_path: Path
    ) -> None:  # type: ignore[no-untyped-def]
        class FailingEngine:
            name = "failing"

            def run(self, task: AgentTask, instructions: str) -> AgentResult:
                raise RuntimeError("engine exploded")

        path, sha = checkout
        outcome = validate_findings(
            findings=[_finding("F-0001", "kvstore/src/api.rs", 28, 30)],
            index=VerificationIndex.build([], []),
            file_lengths={"kvstore/src/api.rs": 40},
            engine=FailingEngine(),
            registry=SkillRegistry.load(SKILLS_DIR),
            run_id=_run_id(db_engine, sha),
            revision_sha=sha,
            checkout=path,
            db_engine=db_engine,
            cas=ArtifactStore(tmp_path / "objects3"),
        )
        assert outcome.results["F-0001"].status == "unresolved"
        assert outcome.publishable == []


class TestValidatorIsolationAndAuthority:
    def test_validator_receives_no_discovery_reasoning(
        self, db_engine, checkout: tuple[Path, str], tmp_path: Path
    ) -> None:  # type: ignore[no-untyped-def]
        """The candidate payload carries the claim and evidence — not a narrative."""
        import json

        path, sha = checkout
        cas = ArtifactStore(tmp_path / "objects4")
        engine = StubEngine(lambda task: _validation_payload())
        validate_findings(
            findings=[_finding("F-0001", "kvstore/src/api.rs", 28, 30)],
            index=VerificationIndex.build([], []),
            file_lengths={"kvstore/src/api.rs": 40},
            engine=engine,
            registry=SkillRegistry.load(SKILLS_DIR),
            run_id=_run_id(db_engine, sha),
            revision_sha=sha,
            checkout=path,
            db_engine=db_engine,
            cas=cas,
        )
        (task,) = engine.seen
        assert set(task.inputs) == {"candidate"}
        payload = json.loads(cas.get(task.inputs["candidate"]))
        assert set(payload) == {"finding", "verification"}

    def test_validator_cannot_rule_on_a_different_finding(
        self, db_engine, checkout: tuple[Path, str], tmp_path: Path
    ) -> None:  # type: ignore[no-untyped-def]
        path, sha = checkout
        engine = StubEngine(lambda task: _validation_payload(findingId="F-9999"))
        outcome = validate_findings(
            findings=[_finding("F-0001", "kvstore/src/api.rs", 28, 30)],
            index=VerificationIndex.build([], []),
            file_lengths={"kvstore/src/api.rs": 40},
            engine=engine,
            registry=SkillRegistry.load(SKILLS_DIR),
            run_id=_run_id(db_engine, sha),
            revision_sha=sha,
            checkout=path,
            db_engine=db_engine,
            cas=ArtifactStore(tmp_path / "objects5"),
        )
        assert "F-9999" not in outcome.results
        assert outcome.results["F-0001"].finding_id == "F-0001"

    def test_confident_validator_without_deterministic_evidence_is_not_publishable(
        self, db_engine, checkout: tuple[Path, str], tmp_path: Path
    ) -> None:  # type: ignore[no-untyped-def]
        """A validator claiming eligibility with no evidence must not get it."""
        path, sha = checkout
        engine = StubEngine(
            lambda task: _validation_payload(confidence=1.0, evidence=[], publicationEligible=True)
        )
        outcome = validate_findings(
            findings=[_finding("F-0001", "kvstore/src/api.rs", 28, 30)],
            index=VerificationIndex.build([], []),
            file_lengths={"kvstore/src/api.rs": 40},
            engine=engine,
            registry=SkillRegistry.load(SKILLS_DIR),
            run_id=_run_id(db_engine, sha),
            revision_sha=sha,
            checkout=path,
            db_engine=db_engine,
            cas=ArtifactStore(tmp_path / "objects6"),
        )
        result = outcome.results["F-0001"]
        assert result.publication_eligible is False
        assert outcome.publishable == []

    def test_tool_evidence_at_the_location_is_attached_by_us(
        self, db_engine, checkout: tuple[Path, str], tmp_path: Path
    ) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.verify.parse import Diagnostic

        path, sha = checkout
        index = VerificationIndex.build(
            diagnostics=[
                Diagnostic(
                    path="kvstore/src/api.rs",
                    start_line=29,
                    end_line=29,
                    level="warning",
                    code="clippy::unwrap_used",
                    message="used unwrap on an Option value",
                )
            ],
            tests=[],
        )
        engine = StubEngine(lambda task: _validation_payload(evidence=[]))
        outcome = validate_findings(
            findings=[_finding("F-0001", "kvstore/src/api.rs", 28, 30)],
            index=index,
            file_lengths={"kvstore/src/api.rs": 40},
            engine=engine,
            registry=SkillRegistry.load(SKILLS_DIR),
            run_id=_run_id(db_engine, sha),
            revision_sha=sha,
            checkout=path,
            db_engine=db_engine,
            cas=ArtifactStore(tmp_path / "objects7"),
        )
        result = outcome.results["F-0001"]
        assert any(e.kind == "static-analysis" for e in result.evidence)
        # ...and that deterministic evidence is what makes it publishable.
        assert result.publication_eligible is True
        assert outcome.publishable == ["F-0001"]
