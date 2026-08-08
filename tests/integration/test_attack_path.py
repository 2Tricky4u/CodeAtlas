"""Attack-path receipts attach to validated security findings, and only those.

The stage is narrow on purpose: a receipt is one agent call, meaningful only
where the actor is an attacker. So a validated *security* finding gets one, a
validated *correctness* finding does not, a *rejected* security finding does
not, and when the analyst fails the finding keeps its verdict untouched — the
receipt enriches, it never gates.

Markers: pg. The engine is scripted; this is wiring, not prose.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from codeatlas.agents.registry import SkillRegistry
from codeatlas.artifacts.store import ArtifactStore
from codeatlas.models.findings import Finding
from codeatlas.models.graph import Evidence, SourceLocation
from codeatlas.models.validation import ValidationResult
from codeatlas.validation.attack_path import analyze_attack_paths, eligible_findings
from codeatlas.validation.validator import ValidationOutcome

pytestmark = [pytest.mark.pg, pytest.mark.timeout(120)]

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / ".agents" / "skills"
sys.path.insert(0, str(REPO_ROOT / "tests"))

from support.engines import ScriptedEngine  # noqa: E402

ATTACK_PATH_OUT: dict[str, Any] = {
    "schemaVersion": "1.0.0",
    "findingId": "WILL-BE-OVERWRITTEN",
    "dataflow": {
        "source": "the key field of a wire request (api.rs:12)",
        "sink": "FileStore::read joins the key onto the root (storage.rs:28)",
        "outcome": "a traversal key reads files outside the store root",
    },
    "reachability": {
        "attacker": "any party whose requests reach handle_request",
        "entrypoint": "handle_request (api.rs:12)",
        "preconditions": ["an embedder wires FileStore to wire keys"],
    },
    "impact": {"level": "high", "why": "arbitrary file read on the host"},
    "likelihood": {"level": "medium", "why": "no auth once reachable"},
    "limitations": ["no shipping listener found in the repo"],
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


def _run_id(db_engine) -> str:  # type: ignore[no-untyped-def]
    from codeatlas.db import repositories as repo

    with Session(db_engine) as s:
        repository = repo.ensure_repository(s, repository_id="local/ap", provider="local")
        revision = repo.ensure_revision(s, repository_id=repository.id, sha="a" * 40)
        run = repo.create_run(
            s, repository_id=repository.id, kind="repository", head_revision_id=revision.id
        )
        s.commit()
        return run.id


def _finding(fid: str, category: str) -> Finding:
    return Finding(
        finding_id=fid,
        category=category,  # type: ignore[arg-type]
        discovered_by_skill=f"reviewer-{category}",
        skill_version="1.0.0",
        severity="high",
        confidence=0.9,
        claim=f"claim {fid}",
        location=SourceLocation(path="kvstore/src/storage.rs", start_line=28, end_line=32),
        evidence=[Evidence(kind="llm-inference", producer="reviewer", confidence=0.9)],
    )


def _verdict(fid: str, status: str) -> ValidationResult:
    return ValidationResult(
        finding_id=fid,
        status=status,  # type: ignore[arg-type]
        severity="high",
        confidence=0.95,
        introduced_by_change=True,
        location=SourceLocation(path="kvstore/src/storage.rs", start_line=28, end_line=32),
        claim=f"claim {fid}",
        evidence=[],
        counter_evidence_checked=["callers"],
        publication_eligible=status == "validated",
        reason="reason",
    )


def _analyze(db_engine, tmp_path: Path, findings, outcome, script):  # type: ignore[no-untyped-def]
    engine = ScriptedEngine(script)
    cas = ArtifactStore(tmp_path / "objects")
    paths, failed = analyze_attack_paths(
        findings=findings,
        outcome=outcome,
        engine=engine,
        registry=SkillRegistry.load(SKILLS_DIR),
        run_id=_run_id(db_engine),
        revision_sha="a" * 40,
        checkout=tmp_path / "checkout",
        db_engine=db_engine,
        cas=cas,
    )
    return paths, failed, engine


class TestEligibility:
    def test_only_validated_security_findings_qualify(self) -> None:
        findings = [
            _finding("F-0001", "security"),
            _finding("F-0002", "correctness"),
            _finding("F-0003", "security"),
            _finding("F-0004", "security"),
        ]
        outcome = ValidationOutcome(
            results={
                "F-0001": _verdict("F-0001", "validated"),
                "F-0002": _verdict("F-0002", "validated"),  # correctness: out
                "F-0003": _verdict("F-0003", "rejected"),  # rejected: out
                "F-0004": _verdict("F-0004", "unresolved"),  # unresolved: out
            }
        )
        assert [f.finding_id for f in eligible_findings(findings, outcome)] == ["F-0001"]


class TestDispatch:
    def test_a_validated_security_finding_gets_a_receipt(self, db_engine, tmp_path) -> None:  # type: ignore[no-untyped-def]
        findings = [_finding("F-0001", "security")]
        outcome = ValidationOutcome(results={"F-0001": _verdict("F-0001", "validated")})
        paths, failed, engine = _analyze(
            db_engine, tmp_path, findings, outcome, {"attack-path-analyst": ATTACK_PATH_OUT}
        )
        assert failed == []
        assert [t.skill_id for t in engine.seen] == ["attack-path-analyst"]
        assert "F-0001" in paths
        # The analyst may only speak about the finding it was handed.
        assert paths["F-0001"]["findingId"] == "F-0001"
        assert paths["F-0001"]["impact"]["level"] == "high"

    def test_a_correctness_finding_is_never_dispatched(self, db_engine, tmp_path) -> None:  # type: ignore[no-untyped-def]
        findings = [_finding("F-0002", "correctness")]
        outcome = ValidationOutcome(results={"F-0002": _verdict("F-0002", "validated")})
        # An empty script would raise on any dispatch — proof none happens.
        paths, failed, engine = _analyze(db_engine, tmp_path, findings, outcome, {})
        assert engine.seen == []
        assert paths == {}
        assert failed == []

    def test_a_rejected_security_finding_is_never_dispatched(self, db_engine, tmp_path) -> None:  # type: ignore[no-untyped-def]
        findings = [_finding("F-0003", "security")]
        outcome = ValidationOutcome(results={"F-0003": _verdict("F-0003", "rejected")})
        paths, _failed, engine = _analyze(db_engine, tmp_path, findings, outcome, {})
        assert engine.seen == []
        assert paths == {}


CASSETTES = REPO_ROOT / "tests" / "cassettes"


def _recorded_candidate() -> tuple[Finding, ValidationResult]:
    """The exact finding+verdict the attack-path cassette was recorded on.

    Reconstructed identically to scripts/record_cassette._attack_path_candidate
    so the replay keys on the same candidate sha.
    """
    import json

    cassette = next(CASSETTES.glob("reviewer-security-*.json"))
    findings = json.loads(cassette.read_text(encoding="utf-8"))["result"]["output"]["findings"]
    finding = Finding.model_validate(findings[0])
    verdict = ValidationResult(
        finding_id=finding.finding_id,
        status="validated",
        severity=finding.severity,
        confidence=0.95,
        introduced_by_change=True,
        location=finding.location,
        claim=finding.claim,
        evidence=[],
        counter_evidence_checked=["callers", "existing tests"],
        publication_eligible=True,
        reason="the cited sink is reached with attacker-controlled input and no guard",
    )
    return finding, verdict


class TestTheRecordedCassetteReplays:
    def test_a_real_analysis_replays_into_a_valid_receipt(self, db_engine, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """Proves the recording is genuine, not a stub — the live skill produced
        a schema-valid attack path once, and it replays here without quota."""
        from codeatlas.agents.replay_engine import ReplayEngine
        from codeatlas.models.attack_path import AttackPath

        finding, verdict = _recorded_candidate()
        outcome = ValidationOutcome(results={finding.finding_id: verdict})
        cas = ArtifactStore(tmp_path / "objects")
        paths, failed = analyze_attack_paths(
            findings=[finding],
            outcome=outcome,
            engine=ReplayEngine(CASSETTES),
            registry=SkillRegistry.load(SKILLS_DIR),
            run_id=_run_id(db_engine),
            revision_sha="cec312dc2ce65dc7b34fc0cf1087dcebbda3b5b2",
            checkout=tmp_path / "checkout",
            db_engine=db_engine,
            cas=cas,
        )
        assert failed == []
        receipt = AttackPath.model_validate(paths[finding.finding_id])
        assert receipt.finding_id == finding.finding_id
        assert receipt.dataflow.source and receipt.dataflow.sink
        assert receipt.impact.why and receipt.likelihood.why


class TestFailureIsNeverFatal:
    def test_an_analyst_that_explodes_is_reported_not_raised(self, db_engine, tmp_path) -> None:  # type: ignore[no-untyped-def]
        findings = [_finding("F-0001", "security")]
        outcome = ValidationOutcome(results={"F-0001": _verdict("F-0001", "validated")})
        paths, failed, _ = _analyze(
            db_engine,
            tmp_path,
            findings,
            outcome,
            {"attack-path-analyst": RuntimeError("scripted analyst failure")},
        )
        assert paths == {}
        assert failed == ["F-0001"]
        # The verdict is untouched: the receipt enriches, it does not gate.
        assert outcome.results["F-0001"].status == "validated"
        assert outcome.results["F-0001"].publication_eligible is True
