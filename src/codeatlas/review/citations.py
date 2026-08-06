"""Citation validation for the change explanation.

The explanation is the one artifact here written by a model. What makes it
trustworthy is not care on the model's part; it is that every sentence points at
something checkable — a path and line range at a pinned revision, an edge in the
graph diff, an item in the API delta, an entry in the impact set — and that
anything failing the check is *removed*.

Removed, not softened. A hedged false claim is still a false claim, and it keeps
the authority of having appeared in the report. Softening also destroys the
signal: a reader cannot tell "the model was unsure" from "this did not survive
verification". Every removal is recorded in `droppedClaims`, so a thin
explanation is visibly thin.

One deliberate asymmetry: a claim with several citations survives on the ones
that resolve. Dropping a true statement because one of its three references was
sloppy would lose real information, and the surviving citations still let a
reader check it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from codeatlas.models.explanation import (
    ApiCitation,
    ChangeExplanation,
    Citation,
    Claim,
    DroppedClaim,
    EdgeCitation,
    ExplanationSection,
    ImpactCitation,
    SourceCitation,
)


@dataclass(frozen=True, slots=True)
class CitationIndex:
    """Everything a citation is allowed to point at.

    Built from artifacts the run already produced, so the universe of citable
    things is exactly what was actually measured.
    """

    base_revision: str
    head_revision: str
    paths_by_revision: dict[str, set[str]]
    edge_ids: set[str]
    api_items: set[str]
    impact_keys: set[str]
    line_counts: dict[tuple[str, str], int] = field(default_factory=dict)

    def revision_sha(self, side: str) -> str:
        return self.base_revision if side == "base" else self.head_revision


def validate_explanation(
    explanation: ChangeExplanation, index: CitationIndex
) -> tuple[ChangeExplanation, list[DroppedClaim]]:
    """Return the explanation with only checkable claims, plus what was removed."""
    sections: list[ExplanationSection] = []
    dropped: list[DroppedClaim] = []

    for section in explanation.sections:
        kept_claims: list[Claim] = []
        for claim in section.claims:
            resolved: list[Citation] = []
            reasons: list[str] = []
            for citation in claim.citations:
                problem = citation_problem(citation, index)
                if problem is None:
                    resolved.append(citation)
                else:
                    reasons.append(problem)
            if resolved:
                kept_claims.append(Claim(text=claim.text, citations=resolved))
            else:
                dropped.append(
                    DroppedClaim(
                        section_id=section.id,
                        text=claim.text,
                        reason="; ".join(reasons) or "no citations",
                    )
                )
        # A section with nothing left is removed: an empty heading in a report
        # reads as "we looked and found nothing", which is a different claim.
        if kept_claims:
            sections.append(
                ExplanationSection(id=section.id, title=section.title, claims=kept_claims)
            )

    notes = list(explanation.notes)
    if not sections and not any("no claim" in note.lower() for note in notes):
        notes.append(
            "no claim in this explanation survived citation validation; "
            "nothing here is supported by the run's own evidence"
        )

    validated = ChangeExplanation(
        summary=explanation.summary,
        sections=sections,
        sequence_diagram=explanation.sequence_diagram,
        dropped_claims=[*explanation.dropped_claims, *dropped],
        notes=notes,
    )
    return validated, dropped


def citation_problem(citation: Citation, index: CitationIndex) -> str | None:
    """The reason this citation does not resolve, or None if it does."""
    if isinstance(citation, SourceCitation):
        return _source_problem(citation, index)
    if isinstance(citation, EdgeCitation):
        if citation.edge_id not in index.edge_ids:
            return f"graph edge {citation.edge_id} is not in this change's structural diff"
        return None
    if isinstance(citation, ApiCitation):
        if citation.item not in index.api_items:
            return f"API item {citation.item!r} is not in this change's public API delta"
        return None
    assert isinstance(citation, ImpactCitation)
    # The union is closed and discriminated, so this is the last arm.
    if citation.stable_key not in index.impact_keys:
        return f"{citation.stable_key} is not in this change's impact set"
    return None


def _source_problem(citation: SourceCitation, index: CitationIndex) -> str | None:
    revision = index.revision_sha(citation.revision)
    known = index.paths_by_revision.get(revision)
    if known is None:
        return (
            f"no file list was recorded for the {citation.revision} revision, "
            "so this citation cannot be checked"
        )
    if citation.path not in known:
        return f"{citation.path} does not exist at the {citation.revision} revision"

    start = citation.start_line
    end = citation.end_line
    if start is not None and end is not None and end < start:
        return f"{citation.path}:{start}-{end} ends before it begins"

    total = index.line_counts.get((revision, citation.path))
    if total is None:
        return None  # the path checks out; line bounds were not measured
    for line in (start, end):
        if line is not None and line > total:
            return (
                f"{citation.path}:{line} is past the end of the file at the "
                f"{citation.revision} revision ({total} lines)"
            )
    return None
