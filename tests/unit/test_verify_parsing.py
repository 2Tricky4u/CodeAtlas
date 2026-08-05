"""Parsing of cargo's machine-readable output into a verification index.

Pure functions over canned tool output: the battery itself needs a toolchain,
but turning its JSON into evidence must be testable without one.
"""

from __future__ import annotations

import json

from codeatlas.verify.parse import (
    VerificationIndex,
    parse_clippy_messages,
    parse_test_events,
)

CLIPPY_LINES = [
    json.dumps(
        {
            "reason": "compiler-message",
            "message": {
                "level": "warning",
                "code": {"code": "clippy::needless_range_loop"},
                "message": "the loop variable is only used to index",
                "spans": [
                    {
                        "file_name": "kvstore/src/cache.rs",
                        "line_start": 42,
                        "line_end": 44,
                        "is_primary": True,
                    }
                ],
            },
        }
    ),
    json.dumps(
        {
            "reason": "compiler-message",
            "message": {
                "level": "error",
                "code": {"code": "E0382"},
                "message": "borrow of moved value",
                "spans": [
                    {
                        "file_name": "kvstore/src/api.rs",
                        "line_start": 10,
                        "line_end": 10,
                        "is_primary": True,
                    }
                ],
            },
        }
    ),
    json.dumps({"reason": "build-finished", "success": True}),
    "not json at all",
]

TEST_LINES = [
    json.dumps({"type": "suite", "event": "started", "test_count": 3}),
    json.dumps({"type": "test", "event": "started", "name": "cache::evicts_only_overflow"}),
    json.dumps(
        {
            "type": "test",
            "event": "failed",
            "name": "cache::evicts_only_overflow",
            "stdout": "assertion failed: cache.len() == 2",
        }
    ),
    json.dumps({"type": "test", "event": "ok", "name": "api::parses_get"}),
    json.dumps({"type": "test", "event": "ignored", "name": "api::slow_path"}),
    json.dumps({"type": "suite", "event": "failed", "passed": 1, "failed": 1, "ignored": 1}),
]


class TestClippyParsing:
    def test_extracts_diagnostics_with_locations(self) -> None:
        diagnostics = parse_clippy_messages(CLIPPY_LINES)
        assert len(diagnostics) == 2
        first = diagnostics[0]
        assert first.path == "kvstore/src/cache.rs"
        assert first.start_line == 42
        assert first.end_line == 44
        assert first.code == "clippy::needless_range_loop"
        assert first.level == "warning"

    def test_ignores_non_message_and_malformed_lines(self) -> None:
        assert len(parse_clippy_messages(["", "junk", json.dumps({"reason": "other"})])) == 0

    def test_windows_paths_are_normalized(self) -> None:
        line = json.dumps(
            {
                "reason": "compiler-message",
                "message": {
                    "level": "warning",
                    "code": {"code": "clippy::x"},
                    "message": "m",
                    "spans": [
                        {
                            "file_name": "kvstore\\src\\cache.rs",
                            "line_start": 1,
                            "line_end": 1,
                            "is_primary": True,
                        }
                    ],
                },
            }
        )
        assert parse_clippy_messages([line])[0].path == "kvstore/src/cache.rs"


class TestTestParsing:
    def test_extracts_outcomes(self) -> None:
        results = parse_test_events(TEST_LINES)
        by_name = {r.name: r for r in results}
        assert by_name["cache::evicts_only_overflow"].status == "failed"
        assert by_name["api::parses_get"].status == "passed"
        assert by_name["api::slow_path"].status == "skipped"

    def test_failure_output_is_kept_as_evidence(self) -> None:
        failed = next(r for r in parse_test_events(TEST_LINES) if r.status == "failed")
        assert "assertion failed" in (failed.output or "")

    def test_empty_stream_is_not_an_error(self) -> None:
        assert parse_test_events([]) == []


class TestVerificationIndex:
    def test_lookup_by_location_with_overlap(self) -> None:
        index = VerificationIndex.build(
            diagnostics=parse_clippy_messages(CLIPPY_LINES),
            tests=parse_test_events(TEST_LINES),
        )
        hits = index.diagnostics_near("kvstore/src/cache.rs", 43, 43)
        assert len(hits) == 1
        assert hits[0].code == "clippy::needless_range_loop"

    def test_lookup_respects_tolerance_window(self) -> None:
        index = VerificationIndex.build(diagnostics=parse_clippy_messages(CLIPPY_LINES), tests=[])
        assert index.diagnostics_near("kvstore/src/cache.rs", 46, 46, tolerance=3)
        assert not index.diagnostics_near("kvstore/src/cache.rs", 200, 200, tolerance=3)

    def test_lookup_on_unknown_path_is_empty(self) -> None:
        index = VerificationIndex.build(diagnostics=parse_clippy_messages(CLIPPY_LINES), tests=[])
        assert index.diagnostics_near("other/file.rs", 42, 42) == []

    def test_failing_tests_are_exposed(self) -> None:
        index = VerificationIndex.build(diagnostics=[], tests=parse_test_events(TEST_LINES))
        assert [t.name for t in index.failing_tests()] == ["cache::evicts_only_overflow"]
