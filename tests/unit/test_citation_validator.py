"""Every claim must cite something that exists (P3). Pure — no agent needed.

An explanation is the one artifact in this pipeline written by a model, and the
thing that makes it trustworthy is not that the model was careful — it is that
each sentence points at a revision, an edge, an API item or an impact entry that
can be checked, and that anything failing the check is *removed* rather than
hedged. A softened false claim is still a false claim, and it keeps the authority
of appearing in the report.

The empirical case for the citations themselves: developers shown explanations
with inline code links rated them 3.99/5 for trust against 3.41 for verdict-only,
and questioned the tool *more* often rather than less (arXiv 2607.24601).
"""

from __future__ import annotations

from codeatlas.models.explanation import (
    ApiCitation,
    ChangeExplanation,
    Claim,
    EdgeCitation,
    ExplanationSection,
    ImpactCitation,
    SourceCitation,
)
from codeatlas.review.citations import CitationIndex, validate_explanation

BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40

INDEX = CitationIndex(
    base_revision=BASE_SHA,
    head_revision=HEAD_SHA,
    paths_by_revision={
        BASE_SHA: {"kvstore/src/cache.rs", "kvstore/src/api.rs"},
        HEAD_SHA: {"kvstore/src/cache.rs", "kvstore/src/api.rs"},
    },
    edge_ids={"edge:abc123"},
    api_items={"pub fn kvstore::cache::Cache::evict_oldest(&mut self, usize)"},
    impact_keys={"sym:scip/rust-analyzer cargo kvstore api/handle_request()."},
    line_counts={(HEAD_SHA, "kvstore/src/cache.rs"): 90, (BASE_SHA, "kvstore/src/cache.rs"): 80},
)


def explanation(*claims: Claim, section: str = "before") -> ChangeExplanation:
    return ChangeExplanation(
        summary="The eviction API was replaced.",
        sections=[ExplanationSection(id=section, title="What it did before", claims=list(claims))],  # type: ignore[arg-type]
    )


def claim(text: str, *citations: object) -> Claim:
    return Claim(text=text, citations=list(citations))  # type: ignore[arg-type]


class TestResolvableCitationsSurvive:
    def test_a_source_citation_at_a_known_path_and_line_is_kept(self) -> None:
        kept, dropped = validate_explanation(
            explanation(
                claim(
                    "evict_oldest removed one entry too many.",
                    SourceCitation(
                        revision="base", path="kvstore/src/cache.rs", start_line=41, end_line=48
                    ),
                )
            ),
            INDEX,
        )
        assert kept.claim_count == 1
        assert dropped == []

    def test_a_graph_edge_citation_is_kept(self) -> None:
        kept, _ = validate_explanation(
            explanation(claim("put no longer calls it.", EdgeCitation(edge_id="edge:abc123"))),
            INDEX,
        )
        assert kept.claim_count == 1

    def test_an_api_item_citation_is_kept(self) -> None:
        kept, _ = validate_explanation(
            explanation(
                claim(
                    "The method left the public API.",
                    ApiCitation(
                        item="pub fn kvstore::cache::Cache::evict_oldest(&mut self, usize)"
                    ),
                )
            ),
            INDEX,
        )
        assert kept.claim_count == 1

    def test_an_impact_citation_is_kept(self) -> None:
        kept, _ = validate_explanation(
            explanation(
                claim(
                    "handle_request could be affected.",
                    ImpactCitation(
                        stable_key="sym:scip/rust-analyzer cargo kvstore api/handle_request()."
                    ),
                )
            ),
            INDEX,
        )
        assert kept.claim_count == 1


class TestUnresolvableCitationsRemoveTheClaim:
    def test_a_path_that_does_not_exist_drops_the_claim(self) -> None:
        kept, dropped = validate_explanation(
            explanation(
                claim(
                    "The retry loop in scheduler.rs was removed.",
                    SourceCitation(revision="head", path="kvstore/src/scheduler.rs"),
                )
            ),
            INDEX,
        )
        assert kept.claim_count == 0
        assert len(dropped) == 1
        assert "scheduler.rs" in dropped[0].reason

    def test_a_line_beyond_the_end_of_the_file_drops_the_claim(self) -> None:
        """A plausible path with an invented line is the most convincing kind of wrong."""
        kept, dropped = validate_explanation(
            explanation(
                claim(
                    "The guard at line 400 was deleted.",
                    SourceCitation(revision="head", path="kvstore/src/cache.rs", start_line=400),
                )
            ),
            INDEX,
        )
        assert kept.claim_count == 0
        assert "90 lines" in dropped[0].reason

    def test_an_unknown_edge_id_drops_the_claim(self) -> None:
        kept, dropped = validate_explanation(
            explanation(claim("A new dependency appeared.", EdgeCitation(edge_id="edge:nope"))),
            INDEX,
        )
        assert kept.claim_count == 0
        assert dropped[0].reason

    def test_an_api_item_nobody_reported_drops_the_claim(self) -> None:
        kept, dropped = validate_explanation(
            explanation(
                claim("A trait impl was removed.", ApiCitation(item="impl Drop for Cache"))
            ),
            INDEX,
        )
        assert kept.claim_count == 0
        assert dropped[0].reason

    def test_the_dropped_claim_is_recorded_not_merely_discarded(self) -> None:
        kept, dropped = validate_explanation(
            explanation(
                claim("Invented.", SourceCitation(revision="head", path="nope.rs")),
                section="risks",
            ),
            INDEX,
        )
        assert dropped[0].section_id == "risks"
        assert dropped[0].text == "Invented."
        assert kept.dropped_claims == dropped, "the artifact carries its own omissions"


class TestOneBadCitationDoesNotPoisonAGoodClaim:
    def test_a_claim_keeps_only_the_citations_that_resolve(self) -> None:
        kept, dropped = validate_explanation(
            explanation(
                claim(
                    "evict_oldest was removed.",
                    SourceCitation(revision="base", path="kvstore/src/cache.rs", start_line=41),
                    EdgeCitation(edge_id="edge:nope"),
                )
            ),
            INDEX,
        )
        assert kept.claim_count == 1
        assert len(kept.sections[0].claims[0].citations) == 1
        assert dropped == [], "the claim still stands on the citation that resolved"

    def test_a_claim_whose_every_citation_fails_is_dropped(self) -> None:
        kept, dropped = validate_explanation(
            explanation(
                claim(
                    "Something happened.",
                    EdgeCitation(edge_id="edge:nope"),
                    ApiCitation(item="pub fn imaginary()"),
                )
            ),
            INDEX,
        )
        assert kept.claim_count == 0
        assert len(dropped) == 1


class TestSectionsAndShape:
    def test_an_emptied_section_is_removed_rather_than_left_blank(self) -> None:
        kept, _ = validate_explanation(
            explanation(claim("Invented.", SourceCitation(revision="head", path="nope.rs"))), INDEX
        )
        assert kept.sections == []

    def test_the_summary_survives_validation(self) -> None:
        """The summary is not a claim; it is the reader's entry point."""
        kept, _ = validate_explanation(
            explanation(claim("Invented.", SourceCitation(revision="head", path="nope.rs"))), INDEX
        )
        assert kept.summary == "The eviction API was replaced."

    def test_an_explanation_left_with_nothing_says_so(self) -> None:
        kept, _ = validate_explanation(
            explanation(claim("Invented.", SourceCitation(revision="head", path="nope.rs"))), INDEX
        )
        assert any("no claim" in note.lower() for note in kept.notes)

    def test_validation_is_idempotent(self) -> None:
        once, _ = validate_explanation(
            explanation(
                claim(
                    "evict_oldest was removed.",
                    SourceCitation(revision="base", path="kvstore/src/cache.rs", start_line=41),
                )
            ),
            INDEX,
        )
        twice, dropped = validate_explanation(once, INDEX)
        assert twice.contract_dump() == once.contract_dump()
        assert dropped == []


class TestUnknownRevisionsAreNotSilentlyAccepted:
    def test_a_citation_against_a_revision_with_no_file_list_is_dropped(self) -> None:
        index = CitationIndex(
            base_revision=BASE_SHA,
            head_revision=HEAD_SHA,
            paths_by_revision={HEAD_SHA: {"kvstore/src/cache.rs"}},
            edge_ids=set(),
            api_items=set(),
            impact_keys=set(),
        )
        kept, dropped = validate_explanation(
            explanation(
                claim(
                    "It used to do this.",
                    SourceCitation(revision="base", path="kvstore/src/cache.rs"),
                )
            ),
            index,
        )
        assert kept.claim_count == 0
        assert "base" in dropped[0].reason
