"""Evidence-density floors on the narrative — deterministic notes, not gates.

A narrative that survived citation checking can still be thin: three claims
citing one file reads like understanding but is a glance. The floor cannot
force unsaid words after the fact, so it discloses instead — the same posture
as every other degradation note in the manifest.
"""

from __future__ import annotations

from codeatlas.models.project_explanation import (
    ProjectClaim,
    ProjectExplanation,
    ProjectSection,
    ProjectSourceCitation,
)
from codeatlas.project.narrative import density_notes


def _claim(path: str) -> ProjectClaim:
    return ProjectClaim(
        text=f"something about {path}",
        citations=[ProjectSourceCitation(path=path, start_line=1, end_line=2)],
    )


def _explanation(paths: list[str], section_ids: list[str]) -> ProjectExplanation:
    return ProjectExplanation(
        summary="a tool",
        sections=[
            ProjectSection(
                id=sid,  # type: ignore[arg-type]
                title=sid,
                claims=[_claim(p) for p in paths],
            )
            for sid in section_ids
        ],
        dropped_claims=[],
        notes=[],
    )


def test_a_thin_narrative_is_disclosed() -> None:
    explanation = _explanation(
        ["src/main.rs", "src/walk.rs"], ["what", "structure", "entry", "hotspots", "caution"]
    )
    notes = density_notes(explanation, available_files=40)
    assert any("2 distinct file" in note for note in notes)


def test_a_small_project_is_not_scolded_for_being_small() -> None:
    """Two files cited out of two that exist is full coverage, not thinness."""
    explanation = _explanation(
        ["src/main.rs", "src/lib.rs"], ["what", "structure", "entry", "hotspots", "caution"]
    )
    assert density_notes(explanation, available_files=2) == []


def test_missing_canonical_sections_are_named() -> None:
    explanation = _explanation(["a.rs", "b.rs", "c.rs", "d.rs", "e.rs"], ["what", "entry"])
    notes = density_notes(explanation, available_files=40)
    assert any("structure" in note and "hotspots" in note and "caution" in note for note in notes)


def test_a_dense_complete_narrative_earns_silence() -> None:
    explanation = _explanation(
        ["a.rs", "b.rs", "c.rs", "d.rs", "e.rs"],
        ["what", "structure", "entry", "hotspots", "caution"],
    )
    assert density_notes(explanation, available_files=40) == []
