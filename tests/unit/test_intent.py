"""Intent reconstruction: source collection and citation discipline (pure units).

The hard rule (research doc ~line 754): unstated inferred intent must be labeled
as inference and can never alone justify a blocking finding. Deterministic
post-processing therefore verifies that every citation points at a file that
exists at the analyzed revision, and downgrades anything that does not.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codeatlas.models.intent import IntentPackage, Requirement
from codeatlas.review.intent import (
    IntentError,
    collect_intent_sources,
    verify_citations,
)


def _req(rid: str, kind: str, ref: str | None, text: str = "x") -> Requirement:
    return Requirement(
        id=rid,
        source_kind=kind,  # type: ignore[arg-type]
        source_ref=ref,
        text=text,
        acceptance_criteria=[],
    )


def _package(requirements: list[Requirement]) -> IntentPackage:
    return IntentPackage(
        requirements=requirements,
        non_goals=[],
        compatibility_obligations=[],
        unresolved_questions=[],
    )


class TestSourceCollection:
    def test_collects_spec_and_adrs(self, tmp_path: Path) -> None:
        (tmp_path / "docs" / "adr").mkdir(parents=True)
        (tmp_path / "docs" / "SPEC.md").write_text("# spec\n", encoding="utf-8")
        (tmp_path / "docs" / "adr" / "adr-0001-x.md").write_text("# adr\n", encoding="utf-8")
        (tmp_path / "README.md").write_text("# readme\n", encoding="utf-8")

        sources = collect_intent_sources(tmp_path)
        paths = {s.path for s in sources}
        assert "docs/SPEC.md" in paths
        assert "docs/adr/adr-0001-x.md" in paths
        assert "README.md" in paths

    def test_ignores_source_code_and_vendored_trees(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "lib.rs").write_text("fn main() {}\n", encoding="utf-8")
        (tmp_path / "target").mkdir()
        (tmp_path / "target" / "NOTES.md").write_text("# build junk\n", encoding="utf-8")

        paths = {s.path for s in collect_intent_sources(tmp_path)}
        assert "src/lib.rs" not in paths
        assert "target/NOTES.md" not in paths

    def test_empty_repository_yields_no_sources(self, tmp_path: Path) -> None:
        assert collect_intent_sources(tmp_path) == []

    def test_source_kind_classification(self, tmp_path: Path) -> None:
        (tmp_path / "docs" / "adr").mkdir(parents=True)
        (tmp_path / "docs" / "SPEC.md").write_text("s\n", encoding="utf-8")
        (tmp_path / "docs" / "adr" / "adr-0002-y.md").write_text("a\n", encoding="utf-8")
        by_path = {s.path: s.kind for s in collect_intent_sources(tmp_path)}
        assert by_path["docs/SPEC.md"] == "spec"
        assert by_path["docs/adr/adr-0002-y.md"] == "adr"


class TestCitationVerification:
    def test_valid_citations_pass_through(self) -> None:
        package = _package([_req("REQ-001", "spec", "docs/SPEC.md")])
        verified, problems = verify_citations(package, valid_paths={"docs/SPEC.md"})
        assert problems == []
        assert verified.requirements[0].source_kind == "spec"

    def test_citation_to_missing_file_is_downgraded_to_inferred(self) -> None:
        package = _package([_req("REQ-001", "spec", "docs/GHOST.md")])
        verified, problems = verify_citations(package, valid_paths={"docs/SPEC.md"})
        assert problems, "a bad citation must be reported"
        assert verified.requirements[0].source_kind == "inferred"
        assert verified.requirements[0].source_ref is None

    def test_inferred_requirement_needs_no_citation(self) -> None:
        package = _package([_req("REQ-001", "inferred", None)])
        verified, problems = verify_citations(package, valid_paths=set())
        assert problems == []
        assert verified.requirements[0].source_kind == "inferred"

    def test_cited_kind_without_reference_is_downgraded(self) -> None:
        package = _package([_req("REQ-001", "adr", None)])
        verified, problems = verify_citations(package, valid_paths={"docs/adr/a.md"})
        assert problems
        assert verified.requirements[0].source_kind == "inferred"

    def test_unavailable_is_preserved_not_fabricated(self) -> None:
        package = _package([_req("REQ-001", "unavailable", None, text="no spec found")])
        verified, problems = verify_citations(package, valid_paths=set())
        assert problems == []
        assert verified.requirements[0].source_kind == "unavailable"

    def test_duplicate_requirement_ids_rejected(self) -> None:
        package = _package([_req("REQ-001", "inferred", None), _req("REQ-001", "inferred", None)])
        with pytest.raises(IntentError, match="duplicate"):
            verify_citations(package, valid_paths=set())

    def test_line_anchored_citation_accepted(self) -> None:
        package = _package([_req("REQ-001", "spec", "docs/SPEC.md#L10-L14")])
        verified, problems = verify_citations(package, valid_paths={"docs/SPEC.md"})
        assert problems == []
        assert verified.requirements[0].source_kind == "spec"
