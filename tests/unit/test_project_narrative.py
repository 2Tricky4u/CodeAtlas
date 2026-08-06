"""The project explanation is checked against the overview that produced it (P5c).

Same discipline as the change explanation, over a different universe. The
deterministic pass in `project/overview.py` already established what modules,
packages and cycles exist at this revision; the narrative may say what they
*mean*, and nothing else. A claim about a module the overview never measured is
a claim about a project that does not exist, and it is deleted.

The cycle citation is the strongest of the four: naming the exact member set
means the model cannot allude vaguely to "some circular dependencies" — it has
to name a cycle the deterministic pass actually found, and the set is checked.
"""

from __future__ import annotations

from codeatlas.models.overview import (
    Cycle,
    CycleEdge,
    ModuleSummary,
    OverviewCounts,
    PackageSummary,
    ProjectOverview,
)
from codeatlas.models.project_explanation import (
    CycleCitation,
    ModuleCitation,
    PackageCitation,
    ProjectClaim,
    ProjectExplanation,
    ProjectSection,
    ProjectSourceCitation,
)
from codeatlas.project.narrative import build_project_index, validate_project_explanation

REVISION = "c" * 40


def module(key: str, level: int = 0, fan_in: int = 0) -> ModuleSummary:
    return ModuleSummary(
        key=key, path=key, package="kvstore", fan_in=fan_in, fan_out=0, level=level, symbol_count=3
    )


OVERVIEW = ProjectOverview(
    repository_id="local/kvstore",
    revision=REVISION,
    packages=[
        PackageSummary(
            name="kvstore", version="0.1.0", manifest_path=None, file_count=4, symbol_count=20
        )
    ],
    modules=[
        module("kvstore/src/main.rs"),
        module("kvstore/src/api.rs", fan_in=2),
        module("kvstore/src/storage.rs", fan_in=1),
    ],
    cycles=[
        Cycle(
            members=["kvstore/src/api.rs", "kvstore/src/storage.rs"],
            edges=[CycleEdge(**{"from": "kvstore/src/api.rs", "to": "kvstore/src/storage.rs"})],
        )
    ],
    counts=OverviewCounts(packages=1, files=4, symbols=20, edges=9),
)

INDEX = build_project_index(OVERVIEW, paths={"kvstore/src/main.rs", "kvstore/src/api.rs"})


def explanation(*claims: ProjectClaim, section: str = "entry") -> ProjectExplanation:
    return ProjectExplanation(
        summary="kvstore is a small key-value store.",
        sections=[ProjectSection(id=section, title="Where to start", claims=list(claims))],  # type: ignore[arg-type]
    )


def claim(text: str, *citations: object) -> ProjectClaim:
    return ProjectClaim(text=text, citations=list(citations))  # type: ignore[arg-type]


class TestCitationsThatResolveSurvive:
    def test_a_module_the_overview_measured_is_kept(self) -> None:
        kept, dropped = validate_project_explanation(
            explanation(claim("Start in main.rs.", ModuleCitation(key="kvstore/src/main.rs"))),
            INDEX,
        )
        assert dropped == []
        assert kept.claim_count == 1

    def test_a_package_the_overview_measured_is_kept(self) -> None:
        kept, _ = validate_project_explanation(
            explanation(claim("One crate.", PackageCitation(name="kvstore"))), INDEX
        )
        assert kept.claim_count == 1

    def test_a_source_path_at_this_revision_is_kept(self) -> None:
        kept, _ = validate_project_explanation(
            explanation(
                claim("It binds a socket.", ProjectSourceCitation(path="kvstore/src/main.rs"))
            ),
            INDEX,
        )
        assert kept.claim_count == 1

    def test_a_cycle_named_by_its_members_is_kept_regardless_of_order(self) -> None:
        # The overview lists members in its own order; a narrative naming the
        # same two modules the other way round is describing the same cycle.
        kept, _ = validate_project_explanation(
            explanation(
                claim(
                    "api and storage depend on each other.",
                    CycleCitation(members=["kvstore/src/storage.rs", "kvstore/src/api.rs"]),
                )
            ),
            INDEX,
        )
        assert kept.claim_count == 1


class TestCitationsThatDoNotResolveAreDeleted:
    def test_a_module_that_was_never_measured_is_dropped(self) -> None:
        kept, dropped = validate_project_explanation(
            explanation(
                claim(
                    "The scheduler drives everything.", ModuleCitation(key="kvstore/src/sched.rs")
                )
            ),
            INDEX,
        )
        assert kept.claim_count == 0
        assert len(dropped) == 1
        assert "kvstore/src/sched.rs" in dropped[0].reason

    def test_a_package_that_does_not_exist_is_dropped(self) -> None:
        _, dropped = validate_project_explanation(
            explanation(claim("It has a client crate.", PackageCitation(name="kvstore-client"))),
            INDEX,
        )
        assert len(dropped) == 1
        assert "kvstore-client" in dropped[0].reason

    def test_a_path_absent_at_this_revision_is_dropped(self) -> None:
        _, dropped = validate_project_explanation(
            explanation(claim("See the README.", ProjectSourceCitation(path="README.md"))), INDEX
        )
        assert len(dropped) == 1
        assert "README.md" in dropped[0].reason

    def test_a_cycle_the_overview_did_not_find_is_dropped(self) -> None:
        # A superset of a real cycle is a different claim about the project.
        _, dropped = validate_project_explanation(
            explanation(
                claim(
                    "Three modules form a cycle.",
                    CycleCitation(
                        members=[
                            "kvstore/src/api.rs",
                            "kvstore/src/storage.rs",
                            "kvstore/src/main.rs",
                        ]
                    ),
                )
            ),
            INDEX,
        )
        assert len(dropped) == 1
        assert "cycle" in dropped[0].reason

    def test_a_line_past_the_end_of_the_file_is_dropped(self) -> None:
        index = build_project_index(
            OVERVIEW,
            paths={"kvstore/src/main.rs"},
            line_counts={"kvstore/src/main.rs": 40},
        )
        _, dropped = validate_project_explanation(
            explanation(
                claim(
                    "It starts here.",
                    ProjectSourceCitation(path="kvstore/src/main.rs", start_line=99),
                )
            ),
            index,
        )
        assert len(dropped) == 1
        assert "past the end" in dropped[0].reason


class TestPartialSupport:
    def test_a_claim_survives_on_the_citations_that_resolve(self) -> None:
        kept, dropped = validate_project_explanation(
            explanation(
                claim(
                    "main.rs wires the store together.",
                    ModuleCitation(key="kvstore/src/main.rs"),
                    ModuleCitation(key="kvstore/src/nope.rs"),
                )
            ),
            INDEX,
        )
        assert dropped == []
        assert kept.claim_count == 1
        # The unresolvable half is gone, so a reader following the citations is
        # never sent somewhere that does not exist.
        assert len(kept.sections[0].claims[0].citations) == 1


class TestAnEmptyResultSaysSo:
    def test_a_section_with_nothing_left_is_removed(self) -> None:
        kept, _ = validate_project_explanation(
            explanation(claim("Nope.", ModuleCitation(key="kvstore/src/nope.rs"))), INDEX
        )
        assert kept.sections == []

    def test_an_explanation_with_no_surviving_claim_states_that(self) -> None:
        kept, _ = validate_project_explanation(
            explanation(claim("Nope.", ModuleCitation(key="kvstore/src/nope.rs"))), INDEX
        )
        assert any("survived" in note for note in kept.notes)
