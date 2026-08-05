"""Synthesis: turning validated findings into a report a human can act on.

The report must never overstate: unpublishable findings are separated from
publishable ones, degraded coverage is stated, and every published claim carries
its evidence.
"""

from __future__ import annotations

from codeatlas.models.findings import Finding
from codeatlas.models.graph import Evidence, SourceLocation
from codeatlas.models.validation import ValidationEvidence, ValidationResult
from codeatlas.review.synthesis import build_report, render_markdown


def _finding(fid: str, category: str = "correctness", severity: str = "high") -> Finding:
    return Finding(
        finding_id=fid,
        category=category,  # type: ignore[arg-type]
        discovered_by_skill=f"reviewer-{category}",
        skill_version="1.0.0",
        severity=severity,  # type: ignore[arg-type]
        confidence=0.9,
        claim=f"claim for {fid}",
        location=SourceLocation(path="kvstore/src/api.rs", start_line=28, end_line=30),
        evidence=[Evidence(kind="llm-inference", producer="reviewer", confidence=0.9)],
    )


def _validation(
    fid: str, status: str = "validated", eligible: bool = True, severity: str = "high"
) -> ValidationResult:
    return ValidationResult(
        finding_id=fid,
        status=status,  # type: ignore[arg-type]
        severity=severity,  # type: ignore[arg-type]
        confidence=0.95,
        introduced_by_change=True,
        location=SourceLocation(path="kvstore/src/api.rs", start_line=28, end_line=30),
        claim=f"claim for {fid}",
        evidence=[ValidationEvidence(kind="test", command="cargo test x", exit_code=101)],
        counter_evidence_checked=["callers", "existing tests"],
        publication_eligible=eligible,
    )


class TestReportStructure:
    def test_separates_publishable_from_everything_else(self) -> None:
        findings = [_finding("F-0001"), _finding("F-0002"), _finding("F-0003")]
        validations = {
            "F-0001": _validation("F-0001", eligible=True),
            "F-0002": _validation("F-0002", status="unresolved", eligible=False),
            "F-0003": _validation("F-0003", status="rejected", eligible=False),
        }
        report = build_report(
            run_id="01J4QDGJ4W8Z9X7C5V3B2N1M0A",
            revision_sha="a" * 40,
            findings=findings,
            validations=validations,
            failed_skills=[],
        )
        assert [f.finding_id for f in report.publishable] == ["F-0001"]
        assert {f.finding_id for f in report.withheld} == {"F-0002", "F-0003"}
        assert report.counts["validated"] == 1
        assert report.counts["rejected"] == 1
        assert report.counts["unresolved"] == 1

    def test_degraded_coverage_is_stated_not_hidden(self) -> None:
        report = build_report(
            run_id="R",
            revision_sha="a" * 40,
            findings=[_finding("F-0001")],
            validations={"F-0001": _validation("F-0001")},
            failed_skills=["reviewer-security"],
        )
        assert report.degraded is True
        assert "reviewer-security" in report.coverage_note
        assert "reviewer-security" in render_markdown(report)

    def test_complete_coverage_says_so(self) -> None:
        report = build_report(
            run_id="R",
            revision_sha="a" * 40,
            findings=[_finding("F-0001")],
            validations={"F-0001": _validation("F-0001")},
            failed_skills=[],
        )
        assert report.degraded is False

    def test_findings_are_ordered_by_severity(self) -> None:
        findings = [
            _finding("F-0001", severity="low"),
            _finding("F-0002", severity="critical"),
            _finding("F-0003", severity="medium"),
        ]
        validations = {
            f.finding_id: _validation(f.finding_id, severity=f.severity) for f in findings
        }
        report = build_report(
            run_id="R",
            revision_sha="a" * 40,
            findings=findings,
            validations=validations,
            failed_skills=[],
        )
        assert [f.finding_id for f in report.publishable] == ["F-0002", "F-0003", "F-0001"]

    def test_empty_run_produces_a_valid_empty_report(self) -> None:
        report = build_report(
            run_id="R", revision_sha="a" * 40, findings=[], validations={}, failed_skills=[]
        )
        assert report.publishable == []
        assert "no findings" in render_markdown(report).lower()


class TestMarkdown:
    def test_every_published_finding_carries_its_evidence(self) -> None:
        report = build_report(
            run_id="R",
            revision_sha="a" * 40,
            findings=[_finding("F-0001")],
            validations={"F-0001": _validation("F-0001")},
            failed_skills=[],
        )
        markdown = render_markdown(report)
        assert "cargo test x" in markdown
        assert "kvstore/src/api.rs" in markdown
        assert "counter" in markdown.lower()

    def test_revision_is_pinned_in_the_report(self) -> None:
        report = build_report(
            run_id="R",
            revision_sha="b" * 40,
            findings=[_finding("F-0001")],
            validations={"F-0001": _validation("F-0001")},
            failed_skills=[],
        )
        assert ("b" * 40)[:12] in render_markdown(report)

    def test_withheld_findings_are_summarized_without_being_asserted(self) -> None:
        report = build_report(
            run_id="R",
            revision_sha="a" * 40,
            findings=[_finding("F-0001")],
            validations={"F-0001": _validation("F-0001", status="unresolved", eligible=False)},
            failed_skills=[],
        )
        markdown = render_markdown(report)
        assert "unresolved" in markdown.lower()
        assert "not published" in markdown.lower() or "withheld" in markdown.lower()

    def test_rendering_is_deterministic(self) -> None:
        args = {
            "run_id": "R",
            "revision_sha": "a" * 40,
            "findings": [_finding("F-0001"), _finding("F-0002")],
            "validations": {"F-0001": _validation("F-0001"), "F-0002": _validation("F-0002")},
            "failed_skills": [],
        }
        assert render_markdown(build_report(**args)) == render_markdown(build_report(**args))  # type: ignore[arg-type]
