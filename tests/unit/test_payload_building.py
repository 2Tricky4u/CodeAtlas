"""Payload construction: what would actually be posted."""

from __future__ import annotations

from codeatlas.models.findings import Finding
from codeatlas.models.graph import Evidence, SourceLocation
from codeatlas.models.validation import ValidationEvidence, ValidationResult
from codeatlas.publication.payload import build_payload
from codeatlas.review.synthesis import build_report

SHA = "f" * 40


def _pair(fid: str, path: str, line: int, eligible: bool = True):  # type: ignore[no-untyped-def]
    finding = Finding(
        finding_id=fid,
        category="correctness",
        discovered_by_skill="reviewer-correctness",
        skill_version="1.0.0",
        severity="high",
        confidence=0.9,
        claim=f"claim {fid}",
        location=SourceLocation(path=path, start_line=line, end_line=line + 2),
        evidence=[Evidence(kind="llm-inference", producer="reviewer", confidence=0.9)],
    )
    validation = ValidationResult(
        finding_id=fid,
        status="validated",
        severity="high",
        confidence=0.95,
        introduced_by_change=True,
        location=finding.location,
        claim=finding.claim,
        evidence=[ValidationEvidence(kind="test", command=f"cargo test {fid}", exit_code=101)],
        counter_evidence_checked=["callers"],
        publication_eligible=eligible,
        reason=f"verdict reason for {fid}",
    )
    return finding, validation


def _report(pairs):  # type: ignore[no-untyped-def]
    return build_report(
        run_id="R",
        revision_sha=SHA,
        findings=[f for f, _ in pairs],
        validations={f.finding_id: v for f, v in pairs},
        failed_skills=[],
    )


def test_comments_only_for_changed_files() -> None:
    pairs = [
        _pair("F-0001", "kvstore/src/api.rs", 28),
        _pair("F-0002", "kvstore/src/untouched.rs", 5),
    ]
    payload = build_payload(
        _report(pairs),
        owner="o",
        repo="r",
        pr_number=3,
        commit_sha=SHA,
        changed_paths={"kvstore/src/api.rs"},
    )
    assert [c.path for c in payload.comments] == ["kvstore/src/api.rs"]
    # The withheld one is still visible in the summary body.
    assert "F-0002" in payload.body


def test_withheld_findings_never_become_inline_comments() -> None:
    pairs = [_pair("F-0001", "kvstore/src/api.rs", 28, eligible=False)]
    payload = build_payload(
        _report(pairs), owner="o", repo="r", pr_number=3, commit_sha=SHA, changed_paths=None
    )
    assert payload.comments == []


def test_comment_carries_severity_category_and_evidence() -> None:
    pairs = [_pair("F-0001", "kvstore/src/api.rs", 28)]
    payload = build_payload(
        _report(pairs), owner="o", repo="r", pr_number=3, commit_sha=SHA, changed_paths=None
    )
    body = payload.comments[0].body
    assert "HIGH" in body and "correctness" in body
    assert "cargo test F-0001" in body
    assert "exit 101" in body


def test_event_is_always_comment() -> None:
    payload = build_payload(
        _report([_pair("F-0001", "a.rs", 1)]),
        owner="o",
        repo="r",
        pr_number=3,
        commit_sha=SHA,
        changed_paths=None,
    )
    assert payload.event == "COMMENT"
    assert payload.to_github()["event"] == "COMMENT"


def test_payload_is_deterministic() -> None:
    pairs = [_pair("F-0001", "a.rs", 1), _pair("F-0002", "b.rs", 2)]
    first = build_payload(
        _report(pairs), owner="o", repo="r", pr_number=3, commit_sha=SHA, changed_paths=None
    )
    second = build_payload(
        _report(pairs), owner="o", repo="r", pr_number=3, commit_sha=SHA, changed_paths=None
    )
    assert first.contract_dump() == second.contract_dump()
