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

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol, TypeVar

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

# Covariant: these protocols only ever read citations out of a claim, and both
# explanation models must satisfy them with their own citation union.
CitationT_co = TypeVar("CitationT_co", covariant=True)


class ClaimLike(Protocol[CitationT_co]):
    """The part of a claim this module reads. Both explanations satisfy it."""

    @property
    def text(self) -> str: ...

    @property
    def citations(self) -> Sequence[CitationT_co]: ...


class SectionLike(Protocol[CitationT_co]):
    @property
    def id(self) -> str: ...

    @property
    def title(self) -> str: ...

    @property
    def claims(self) -> Sequence[ClaimLike[CitationT_co]]: ...


@dataclass(frozen=True, slots=True)
class KeptSection[CitationT]:
    """One surviving section: the original, plus each claim's surviving cites."""

    id: str
    title: str
    claims: list[tuple[str, list[CitationT]]]


def partition_claims[CitationT](
    sections: Sequence[SectionLike[CitationT]],
    problem_for: Callable[[CitationT], str | None],
) -> tuple[list[KeptSection[CitationT]], list[DroppedClaim]]:
    """Split claims into those with a resolvable citation and those without.

    The rule lives here, once, because it is the product: a claim that cannot be
    checked is deleted rather than hedged, a claim keeps the citations that do
    resolve, and a section left with nothing is removed — an empty heading reads
    as "we looked and found nothing", which is a different claim.

    The two explanations differ only in what a citation may point at, which is
    the callable.
    """
    kept: list[KeptSection[CitationT]] = []
    dropped: list[DroppedClaim] = []

    for section in sections:
        surviving: list[tuple[str, list[CitationT]]] = []
        for claim in section.claims:
            resolved: list[CitationT] = []
            reasons: list[str] = []
            for citation in claim.citations:
                problem = problem_for(citation)
                if problem is None:
                    resolved.append(citation)
                else:
                    reasons.append(problem)
            if resolved:
                surviving.append((claim.text, resolved))
            else:
                dropped.append(
                    DroppedClaim(
                        section_id=section.id,
                        text=claim.text,
                        reason="; ".join(reasons) or "no citations",
                    )
                )
        if surviving:
            kept.append(KeptSection(id=section.id, title=section.title, claims=surviving))
    return kept, dropped


NOTHING_SURVIVED = (
    "no claim in this explanation survived citation validation; "
    "nothing here is supported by the run's own evidence"
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
    kept, dropped = partition_claims(
        explanation.sections, lambda citation: citation_problem(citation, index)
    )
    sections = [
        ExplanationSection(
            id=section.id,  # type: ignore[arg-type]
            title=section.title,
            claims=[Claim(text=text, citations=citations) for text, citations in section.claims],
        )
        for section in kept
    ]

    notes = list(explanation.notes)
    if not sections and not any("no claim" in note.lower() for note in notes):
        notes.append(NOTHING_SURVIVED)

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
