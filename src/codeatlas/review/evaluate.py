"""Score findings against a fixture's answer key (recall, precision, decoys).

The answer key lives in the fixture *source* directory and is deliberately kept
out of built repositories, so reviewers cannot read it. Matching is anchored on
the source line containing a documented marker, with a tolerance, because line
numbers shift as fixtures evolve while the defect stays put.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from codeatlas.models.findings import Finding

DEFAULT_TOLERANCE = 5


@dataclass(frozen=True, slots=True)
class ExpectedFinding:
    id: str
    category: str
    path: str
    anchor: str
    summary: str
    min_severity: str


@dataclass(frozen=True, slots=True)
class Decoy:
    id: str
    path: str
    anchor: str
    reason: str


@dataclass(frozen=True, slots=True)
class FixtureManifest:
    expected: list[ExpectedFinding]
    decoys: list[Decoy]


@dataclass(frozen=True, slots=True)
class Score:
    matched: dict[str, str] = field(default_factory=dict)  # expected id -> finding id
    missed: list[str] = field(default_factory=list)
    decoys_reported: list[str] = field(default_factory=list)
    unmatched_findings: list[str] = field(default_factory=list)
    total_expected: int = 0

    @property
    def recall(self) -> float:
        return len(self.matched) / self.total_expected if self.total_expected else 0.0

    @property
    def precision(self) -> float:
        reported = len(self.matched) + len(self.unmatched_findings)
        return len(self.matched) / reported if reported else 0.0


def load_manifest(fixture_root: Path) -> FixtureManifest:
    data = yaml.safe_load((fixture_root / "MANIFEST.yaml").read_text(encoding="utf-8"))
    return FixtureManifest(
        expected=[ExpectedFinding(**item) for item in data.get("expected_findings", [])],
        decoys=[Decoy(**item) for item in data.get("expected_rejections", [])],
    )


def _anchor_line(source_root: Path, path: str, anchor: str) -> int | None:
    file = source_root / path
    if not file.exists():
        return None
    for index, line in enumerate(file.read_text(encoding="utf-8").splitlines(), start=1):
        if anchor in line:
            return index
    return None


def _hits(finding: Finding, path: str, line: int | None, tolerance: int) -> bool:
    if finding.location.path != path or line is None:
        return False
    start = finding.location.start_line or 0
    end = finding.location.end_line or start
    return (start - tolerance) <= line <= (end + tolerance)


def score_findings(
    findings: list[Finding],
    manifest: FixtureManifest,
    source_root: Path,
    tolerance: int = DEFAULT_TOLERANCE,
) -> Score:
    matched: dict[str, str] = {}
    claimed: set[str] = set()

    for expected in manifest.expected:
        line = _anchor_line(source_root, expected.path, expected.anchor)
        for finding in findings:
            if finding.finding_id in claimed:
                continue
            if _hits(finding, expected.path, line, tolerance):
                matched[expected.id] = finding.finding_id
                claimed.add(finding.finding_id)
                break

    decoys_reported: list[str] = []
    for decoy in manifest.decoys:
        line = _anchor_line(source_root, decoy.path, decoy.anchor)
        for finding in findings:
            if finding.finding_id in claimed:
                continue
            if _hits(finding, decoy.path, line, tolerance):
                decoys_reported.append(decoy.id)
                claimed.add(finding.finding_id)
                break

    return Score(
        matched=matched,
        missed=[e.id for e in manifest.expected if e.id not in matched],
        decoys_reported=decoys_reported,
        unmatched_findings=[f.finding_id for f in findings if f.finding_id not in claimed],
        total_expected=len(manifest.expected),
    )
