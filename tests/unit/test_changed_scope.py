"""Changed-scope rules for PR mode.

The rule from the research doc (~line 680): a PR review must not block on
defects the PR did not introduce. Pre-existing problems are still reported —
silence would be dishonest — but they are informational, not blocking, unless
the change removed a safeguard that was protecting them.
"""

from __future__ import annotations

from codeatlas.models.findings import Finding
from codeatlas.models.graph import Evidence, SourceLocation
from codeatlas.review.scope import (
    ChangedScope,
    classify_scope,
    is_blocking,
)


def _finding(path: str, start: int = 10, end: int = 12) -> Finding:
    return Finding(
        finding_id="F-0001",
        category="correctness",
        discovered_by_skill="reviewer-correctness",
        skill_version="1.0.0",
        severity="high",
        confidence=0.9,
        claim="c",
        location=SourceLocation(path=path, start_line=start, end_line=end),
        evidence=[Evidence(kind="llm-inference", producer="reviewer", confidence=0.9)],
    )


def _scope(**overrides) -> ChangedScope:  # type: ignore[no-untyped-def]
    base = {
        "changed_paths": {"kvstore/src/api.rs"},
        "added_lines": {"kvstore/src/api.rs": set(range(10, 20))},
        "removed_safeguard_paths": set(),
    }
    base.update(overrides)
    return ChangedScope(**base)  # type: ignore[arg-type]


class TestClassification:
    def test_finding_on_added_lines_is_introduced(self) -> None:
        assert classify_scope(_finding("kvstore/src/api.rs", 10, 12), _scope()) == "introduced"

    def test_finding_in_changed_file_but_untouched_lines_is_adjacent(self) -> None:
        assert classify_scope(_finding("kvstore/src/api.rs", 90, 92), _scope()) == "adjacent"

    def test_finding_in_untouched_file_is_pre_existing(self) -> None:
        assert classify_scope(_finding("kvstore/src/cache.rs", 5, 7), _scope()) == "pre-existing"

    def test_partial_overlap_counts_as_introduced(self) -> None:
        """A finding spanning old and new lines touches the change."""
        assert classify_scope(_finding("kvstore/src/api.rs", 5, 11), _scope()) == "introduced"

    def test_finding_without_line_numbers_falls_back_to_file_scope(self) -> None:
        finding = _finding("kvstore/src/api.rs")
        finding = finding.model_copy(update={"location": SourceLocation(path="kvstore/src/api.rs")})
        assert classify_scope(finding, _scope()) == "adjacent"


class TestBlocking:
    def test_introduced_findings_block(self) -> None:
        assert is_blocking(_finding("kvstore/src/api.rs", 10, 12), _scope()) is True

    def test_pre_existing_findings_do_not_block(self) -> None:
        assert is_blocking(_finding("kvstore/src/cache.rs", 5, 7), _scope()) is False

    def test_adjacent_findings_do_not_block(self) -> None:
        assert is_blocking(_finding("kvstore/src/api.rs", 90, 92), _scope()) is False

    def test_pre_existing_blocks_when_the_change_removed_a_safeguard(self) -> None:
        """The documented exception: the PR made an old problem reachable."""
        scope = _scope(removed_safeguard_paths={"kvstore/src/cache.rs"})
        assert is_blocking(_finding("kvstore/src/cache.rs", 5, 7), scope) is True

    def test_repository_mode_blocks_on_everything(self) -> None:
        """With no PR scope, there is no 'pre-existing' — the whole tree is in scope."""
        assert is_blocking(_finding("anything.rs", 1, 2), None) is True


class TestDiffParsing:
    def test_added_lines_are_extracted_from_a_unified_diff(self) -> None:
        from codeatlas.review.scope import parse_added_lines

        diff = (
            "diff --git a/kvstore/src/api.rs b/kvstore/src/api.rs\n"
            "index 111..222 100644\n"
            "--- a/kvstore/src/api.rs\n"
            "+++ b/kvstore/src/api.rs\n"
            "@@ -8,6 +8,8 @@ fn handle_request() {\n"
            " context line\n"
            "+let key = parts.next().unwrap();\n"
            "+let ttl: u64 = parts.next().unwrap().parse().unwrap();\n"
            " more context\n"
            "-removed line\n"
        )
        added = parse_added_lines(diff)
        assert added["kvstore/src/api.rs"] == {9, 10}

    def test_multiple_files_and_hunks(self) -> None:
        from codeatlas.review.scope import parse_added_lines

        diff = (
            "diff --git a/a.rs b/a.rs\n--- a/a.rs\n+++ b/a.rs\n"
            "@@ -1,2 +1,3 @@\n+one\n context\n"
            "@@ -10,2 +11,3 @@\n context\n+two\n"
            "diff --git a/b.rs b/b.rs\n--- a/b.rs\n+++ b/b.rs\n"
            "@@ -5,1 +5,2 @@\n+three\n"
        )
        added = parse_added_lines(diff)
        assert added["a.rs"] == {1, 12}
        assert added["b.rs"] == {5}

    def test_new_file_diff(self) -> None:
        from codeatlas.review.scope import parse_added_lines

        diff = (
            "diff --git a/new.rs b/new.rs\nnew file mode 100644\n"
            "--- /dev/null\n+++ b/new.rs\n@@ -0,0 +1,3 @@\n+a\n+b\n+c\n"
        )
        assert parse_added_lines(diff)["new.rs"] == {1, 2, 3}

    def test_empty_diff_is_not_an_error(self) -> None:
        from codeatlas.review.scope import parse_added_lines

        assert parse_added_lines("") == {}
