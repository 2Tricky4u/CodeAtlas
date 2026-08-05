"""Deterministic validation rules: deduplication and publication eligibility.

These are code, not prompt text, because they are the rules an agent must not be
able to talk its way past. In particular: **confidence never makes a finding
publishable.** A finding earns publication only by carrying evidence that exists
independently of the model's opinion (research doc ~line 695).
"""

from __future__ import annotations

from dataclasses import dataclass

from codeatlas.models.findings import Finding
from codeatlas.models.graph import SourceLocation
from codeatlas.models.validation import ValidationResult

_SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}

# Two findings are the same defect when their cited spans genuinely OVERLAP —
# same lines, same code. Expanding the window by even a couple of lines merged
# distinct defects in adjacent methods (the unsanitized join in FileStore::read,
# cited 22-28, and the separate one in FileStore::write, cited 30-36), silently
# dropping one of them as a duplicate. Reviewers citing one defect overlap;
# reviewers citing neighbours do not.
_DEDUP_TOLERANCE = 0

# Evidence kinds that exist independently of the reviewing model's judgment.
_DETERMINISTIC_KINDS = frozenset(
    {"test", "command", "static-analysis", "compiler", "schema", "repository-rule", "call-path"}
)
_INDEPENDENT_KINDS = frozenset({"independent-review"})


@dataclass(frozen=True, slots=True)
class FindingGroup:
    canonical: Finding
    duplicates: list[Finding]


def _span(finding: Finding) -> tuple[int, int]:
    start = finding.location.start_line or 0
    end = finding.location.end_line or start
    return start, end


def deduplicate(findings: list[Finding]) -> list[FindingGroup]:
    """Group findings that describe the same defect at the same location.

    Cross-category duplicates are expected and desirable to collapse: the same
    `unwrap()` on untrusted input is legitimately seen by both the correctness
    and the security reviewer, but it is one defect.
    """
    ordered = sorted(
        findings,
        key=lambda f: (f.location.path, _span(f)[0], f.finding_id),
    )
    groups: list[list[Finding]] = []
    for finding in ordered:
        start, end = _span(finding)
        placed = False
        for group in groups:
            head = group[0]
            if head.location.path != finding.location.path:
                continue
            h_start, h_end = _span(head)
            if (h_start - _DEDUP_TOLERANCE) <= end and start <= (h_end + _DEDUP_TOLERANCE):
                group.append(finding)
                placed = True
                break
        if not placed:
            groups.append([finding])

    result: list[FindingGroup] = []
    for group in groups:
        # Highest severity wins, then highest confidence; ties break on the
        # lowest finding id so the choice is stable across runs.
        canonical = sorted(
            group,
            key=lambda f: (-_SEVERITY_RANK.get(f.severity, 0), -f.confidence, f.finding_id),
        )[0]
        duplicates = sorted(
            (f for f in group if f.finding_id != canonical.finding_id),
            key=lambda f: f.finding_id,
        )
        result.append(FindingGroup(canonical=canonical, duplicates=duplicates))
    return result


def location_exists(location: SourceLocation, file_lengths: dict[str, int]) -> bool:
    """True iff the cited path exists at the revision and the lines are inside it."""
    length = file_lengths.get(location.path)
    if length is None:
        return False
    if location.start_line is None:
        return True
    return location.start_line <= length


def is_publication_eligible(result: ValidationResult) -> tuple[bool, str]:
    """Decide publishability from evidence alone; returns (eligible, reason).

    Deliberately ignores `result.confidence` and the validator's own
    `publication_eligible` opinion — both are model output.
    """
    if result.status != "validated":
        return False, f"status is {result.status}, not validated"

    if not result.counter_evidence_checked:
        return False, "no counter-evidence was checked"

    for evidence in result.evidence:
        if evidence.kind in _INDEPENDENT_KINDS:
            return True, "independent confirmation from a fresh context"
        if evidence.kind not in _DETERMINISTIC_KINDS:
            continue
        # A command that succeeded reproduced nothing; only a failure (or a
        # diagnostic hit, which carries no exit code) is evidence of a defect.
        if evidence.exit_code is not None and evidence.exit_code == 0:
            continue
        return True, f"deterministic evidence: {evidence.kind}"

    return False, (
        "no deterministic evidence (a failing test or command, a static-analysis "
        "hit, an exactly violated stated rule, a concrete call path, or independent "
        "confirmation is required; confidence alone is never sufficient)"
    )
