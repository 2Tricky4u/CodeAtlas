"""Validation rules: deduplication and publication eligibility.

The eligibility rule is the load-bearing one (research doc ~line 695):
confidence must never make a finding publishable. Only deterministic evidence,
an exactly-violated stated rule, or independent confirmation can.
"""

from __future__ import annotations

import pytest

from codeatlas.models.findings import Finding
from codeatlas.models.graph import Evidence, SourceLocation
from codeatlas.models.validation import ValidationEvidence, ValidationResult
from codeatlas.validation.rules import (
    deduplicate,
    is_publication_eligible,
    location_exists,
)


def _finding(
    fid: str,
    skill: str = "reviewer-correctness",
    path: str = "kvstore/src/cache.rs",
    start: int = 40,
    end: int = 49,
    category: str = "correctness",
    severity: str = "high",
) -> Finding:
    return Finding(
        finding_id=fid,
        category=category,  # type: ignore[arg-type]
        discovered_by_skill=skill,
        skill_version="1.0.0",
        severity=severity,  # type: ignore[arg-type]
        confidence=0.9,
        claim=f"claim {fid}",
        location=SourceLocation(path=path, start_line=start, end_line=end),
        evidence=[Evidence(kind="llm-inference", producer=skill, confidence=0.9)],
    )


class TestDeduplication:
    def test_overlapping_findings_on_same_location_are_grouped(self) -> None:
        a = _finding("F-0001", "reviewer-correctness", start=40, end=49)
        b = _finding("F-0002", "reviewer-security", start=42, end=45, category="security")
        groups = deduplicate([a, b])
        assert len(groups) == 1
        assert groups[0].canonical.finding_id == "F-0001"
        assert [d.finding_id for d in groups[0].duplicates] == ["F-0002"]

    def test_distant_findings_stay_separate(self) -> None:
        a = _finding("F-0001", start=40, end=49)
        b = _finding("F-0002", start=200, end=210)
        assert len(deduplicate([a, b])) == 2

    def test_neighbouring_methods_are_not_merged(self) -> None:
        """Regression: the same defect class in two adjacent methods is two defects.

        FileStore::read and FileStore::write both join an unsanitized key onto the
        store root. They are separate defects needing separate fixes, and an
        over-wide dedup window silently collapsed one into the other.
        """
        # The exact spans the security reviewer cited for these two defects.
        read_defect = _finding(
            "F-0001", "reviewer-security", path="kvstore/src/storage.rs", start=22, end=28
        )
        write_defect = _finding(
            "F-0002", "reviewer-security", path="kvstore/src/storage.rs", start=30, end=36
        )
        assert len(deduplicate([read_defect, write_defect])) == 2

    def test_minor_line_drift_still_merges(self) -> None:
        """Reviewers citing the same defect rarely pick identical ranges."""
        a = _finding("F-0001", "reviewer-correctness", start=28, end=30)
        b = _finding("F-0002", "reviewer-security", start=29, end=31, category="security")
        assert len(deduplicate([a, b])) == 1

    def test_different_files_stay_separate(self) -> None:
        a = _finding("F-0001", path="kvstore/src/cache.rs")
        b = _finding("F-0002", path="kvstore/src/api.rs")
        assert len(deduplicate([a, b])) == 2

    def test_highest_severity_wins_as_canonical(self) -> None:
        low = _finding("F-0001", severity="low")
        high = _finding("F-0002", severity="critical")
        (group,) = deduplicate([low, high])
        assert group.canonical.finding_id == "F-0002"
        assert [d.finding_id for d in group.duplicates] == ["F-0001"]

    def test_grouping_is_deterministic_regardless_of_input_order(self) -> None:
        a = _finding("F-0001", start=40, end=49)
        b = _finding("F-0002", start=42, end=45)
        forward = [g.canonical.finding_id for g in deduplicate([a, b])]
        backward = [g.canonical.finding_id for g in deduplicate([b, a])]
        assert forward == backward

    def test_empty_input(self) -> None:
        assert deduplicate([]) == []


class TestLocationExistence:
    def test_known_path_within_file_length(self) -> None:
        assert location_exists(SourceLocation(path="a.rs", start_line=5, end_line=7), {"a.rs": 20})

    def test_unknown_path_rejected(self) -> None:
        assert not location_exists(SourceLocation(path="ghost.rs"), {"a.rs": 20})

    def test_line_beyond_end_of_file_rejected(self) -> None:
        assert not location_exists(
            SourceLocation(path="a.rs", start_line=50, end_line=60), {"a.rs": 20}
        )

    def test_path_without_lines_only_needs_the_file(self) -> None:
        assert location_exists(SourceLocation(path="a.rs"), {"a.rs": 20})


def _validation(
    evidence: list[ValidationEvidence],
    status: str = "validated",
    confidence: float = 0.99,
) -> ValidationResult:
    return ValidationResult(
        finding_id="F-0001",
        status=status,  # type: ignore[arg-type]
        severity="high",
        confidence=confidence,
        introduced_by_change=True,
        location=SourceLocation(path="a.rs", start_line=1, end_line=2),
        claim="c",
        evidence=evidence,
        counter_evidence_checked=["checked the caller"],
        publication_eligible=True,  # the validator's own opinion, which we override
    )


class TestPublicationEligibility:
    def test_confidence_alone_never_qualifies(self) -> None:
        """The rule the whole gate exists for."""
        result = _validation(evidence=[], confidence=1.0)
        eligible, reason = is_publication_eligible(result)
        assert eligible is False
        assert "deterministic" in reason.lower()

    def test_failing_test_qualifies(self) -> None:
        result = _validation(
            [ValidationEvidence(kind="test", command="cargo test x", exit_code=101)]
        )
        assert is_publication_eligible(result)[0] is True

    def test_passing_command_does_not_qualify_as_reproduction(self) -> None:
        """A command that succeeded did not reproduce anything."""
        result = _validation([ValidationEvidence(kind="test", command="cargo test x", exit_code=0)])
        assert is_publication_eligible(result)[0] is False

    def test_static_analysis_hit_qualifies(self) -> None:
        result = _validation([ValidationEvidence(kind="static-analysis", command="cargo clippy")])
        assert is_publication_eligible(result)[0] is True

    def test_violated_repository_rule_qualifies(self) -> None:
        result = _validation([ValidationEvidence(kind="repository-rule", command="ADR-0001")])
        assert is_publication_eligible(result)[0] is True

    def test_call_path_qualifies(self) -> None:
        result = _validation([ValidationEvidence(kind="call-path", artifact="sha256:" + "0" * 64)])
        assert is_publication_eligible(result)[0] is True

    def test_independent_review_qualifies(self) -> None:
        result = _validation([ValidationEvidence(kind="independent-review")])
        assert is_publication_eligible(result)[0] is True

    @pytest.mark.parametrize("status", ["rejected", "duplicate", "unresolved"])
    def test_non_validated_status_is_never_eligible(self, status: str) -> None:
        result = _validation(
            [ValidationEvidence(kind="test", command="cargo test x", exit_code=101)],
            status=status,
        )
        eligible, reason = is_publication_eligible(result)
        assert eligible is False
        assert status in reason

    def test_validated_with_evidence_but_no_counter_evidence_is_rejected(self) -> None:
        result = _validation(
            [ValidationEvidence(kind="test", command="cargo test x", exit_code=101)]
        ).model_copy(update={"counter_evidence_checked": []})
        # The contract requires min_length=1, so construct via copy and assert the
        # rule still refuses it defensively.
        eligible, reason = is_publication_eligible(result)
        assert eligible is False
        assert "counter" in reason.lower()
