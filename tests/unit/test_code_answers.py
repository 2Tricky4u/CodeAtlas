"""A code answer is checked against the scope it claims to describe (H6).

The fourth artifact under the narratives' rule and the first produced on
demand: the temptation profile is different — a question invites an answer, and
an agent asked "what does this do" will produce one whether or not the scope
supports it — but the discipline is identical, enforced by the same
`partition_claims` the other three use.
"""

from __future__ import annotations

from codeatlas.models.code_answer import AnswerClaim, CodeAnswer
from codeatlas.models.graph import ProjectGraph, RepositoryRef, RevisionRef
from codeatlas.models.project_explanation import ModuleCitation, ProjectSourceCitation
from codeatlas.project.answers import answer_role, build_answer_index, validate_answer

REVISION = "d" * 40

GRAPH = ProjectGraph(
    repository=RepositoryRef(id="local/kv"),
    revision=RevisionRef(head=REVISION),
    nodes=[],
    edges=[],
)

INDEX = build_answer_index(GRAPH, "src/cache.rs", paths={"src/cache.rs", "src/api.rs"})


def claim(text: str, *citations: object) -> AnswerClaim:
    return AnswerClaim(text=text, citations=list(citations))  # type: ignore[arg-type]


def answer(*claims: AnswerClaim, refused: str | None = None) -> CodeAnswer:
    return CodeAnswer(
        question="what does eviction do?",
        scope="src/cache.rs",
        answer="It evicts." if not refused else None,
        claims=list(claims),
        refused=refused,
    )


class TestClaimsThatResolveSurvive:
    def test_a_source_citation_in_scope_is_kept(self) -> None:
        kept, dropped = validate_answer(
            answer(claim("Eviction pops the front.", ProjectSourceCitation(path="src/cache.rs"))),
            INDEX,
        )
        assert dropped == []
        assert len(kept.claims) == 1
        assert kept.refused is None


class TestClaimsThatDoNotResolveAreDeleted:
    def test_a_path_that_does_not_exist_is_dropped(self) -> None:
        kept, dropped = validate_answer(
            answer(claim("See the scheduler.", ProjectSourceCitation(path="src/sched.rs"))),
            INDEX,
        )
        assert len(dropped) == 1
        assert "src/sched.rs" in dropped[0].reason
        assert kept.claims == []

    def test_an_answer_with_nothing_left_becomes_a_refusal(self) -> None:
        """An answer whose every claim failed is not a thinner answer — the
        prose summary cannot stand on evidence that was deleted."""
        kept, _ = validate_answer(
            answer(claim("Invented.", ProjectSourceCitation(path="src/ghost.rs"))), INDEX
        )
        assert kept.answer is None
        assert kept.refused is not None
        assert any("survived" in note for note in kept.notes)

    def test_a_module_citation_resolves_against_file_nodes(self) -> None:
        _, dropped = validate_answer(
            answer(claim("Defined here.", ModuleCitation(key="file:src/nope.rs"))), INDEX
        )
        assert len(dropped) == 1


class TestRefusalPassesThrough:
    def test_a_refused_answer_is_not_validated_into_something_else(self) -> None:
        refused = answer(refused="this needs code outside src/cache.rs")
        kept, dropped = validate_answer(refused, INDEX)
        assert kept == refused
        assert dropped == []

    def test_revalidating_changes_nothing(self) -> None:
        kept, _ = validate_answer(
            answer(claim("Eviction pops the front.", ProjectSourceCitation(path="src/cache.rs"))),
            INDEX,
        )
        again, dropped_again = validate_answer(kept, INDEX)
        assert dropped_again == []
        assert again.claims == kept.claims


class TestTheCacheKey:
    def test_same_question_same_scope_same_revision_is_one_role(self) -> None:
        assert answer_role(REVISION, "src/cache.rs", "why?") == answer_role(
            REVISION, "src/cache.rs", "why?"
        )

    def test_any_ingredient_changing_changes_the_role(self) -> None:
        base = answer_role(REVISION, "src/cache.rs", "why?")
        assert answer_role(REVISION, "src/cache.rs", "how?") != base
        assert answer_role(REVISION, "src/api.rs", "why?") != base
        assert answer_role("e" * 40, "src/cache.rs", "why?") != base

    def test_the_role_is_servable_by_the_api(self) -> None:
        import re

        assert re.match(r"^[a-z][a-z0-9-]{0,59}$", answer_role(REVISION, "s", "q"))
