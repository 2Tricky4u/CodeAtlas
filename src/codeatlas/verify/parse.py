"""Parse cargo's machine-readable output into a location-indexed evidence set.

Kept separate from execution so it is testable without a toolchain, and so a
future language adapter can populate the same index from its own tools.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

TestStatus = Literal["passed", "failed", "skipped", "error"]

_DEFAULT_TOLERANCE = 3


@dataclass(frozen=True, slots=True)
class Diagnostic:
    path: str  # repo-relative, forward slashes
    start_line: int
    end_line: int
    level: str  # error | warning | note
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class TestResult:
    name: str
    status: TestStatus
    output: str | None = None


def _normalize(path: str) -> str:
    return path.replace("\\", "/")


def parse_clippy_messages(lines: list[str]) -> list[Diagnostic]:
    """Extract primary-span diagnostics from `cargo clippy --message-format json`."""
    diagnostics: list[Diagnostic] = []
    for line in lines:
        payload = _load(line)
        if payload is None or payload.get("reason") != "compiler-message":
            continue
        message = payload.get("message") or {}
        spans = [s for s in message.get("spans", []) if s.get("is_primary")]
        if not spans:
            continue
        span = spans[0]
        code = (message.get("code") or {}).get("code") or message.get("level", "")
        diagnostics.append(
            Diagnostic(
                path=_normalize(str(span.get("file_name", ""))),
                start_line=int(span.get("line_start", 0)),
                end_line=int(span.get("line_end", span.get("line_start", 0))),
                level=str(message.get("level", "")),
                code=str(code),
                message=str(message.get("message", "")),
            )
        )
    return diagnostics


def parse_test_events(lines: list[str]) -> list[TestResult]:
    """Extract per-test outcomes from `cargo test -- --format json` output."""
    results: list[TestResult] = []
    for line in lines:
        payload = _load(line)
        if payload is None or payload.get("type") != "test":
            continue
        event = payload.get("event")
        if event == "started":
            continue
        status: TestStatus
        if event == "ok":
            status = "passed"
        elif event == "failed":
            status = "failed"
        elif event == "ignored":
            status = "skipped"
        else:
            status = "error"
        results.append(
            TestResult(
                name=str(payload.get("name", "")),
                status=status,
                output=payload.get("stdout"),
            )
        )
    return results


def _load(line: str) -> dict[str, Any] | None:
    line = line.strip()
    if not line or not line.startswith("{"):
        return None
    try:
        parsed = json.loads(line)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


@dataclass(frozen=True, slots=True)
class VerificationIndex:
    """Deterministic evidence, addressable by the locations findings cite."""

    by_path: dict[str, list[Diagnostic]] = field(default_factory=dict)
    tests: list[TestResult] = field(default_factory=list)

    @staticmethod
    def build(diagnostics: list[Diagnostic], tests: list[TestResult]) -> VerificationIndex:
        by_path: dict[str, list[Diagnostic]] = {}
        for diagnostic in diagnostics:
            by_path.setdefault(diagnostic.path, []).append(diagnostic)
        return VerificationIndex(by_path=by_path, tests=tests)

    def diagnostics_near(
        self, path: str, start_line: int, end_line: int, tolerance: int = _DEFAULT_TOLERANCE
    ) -> list[Diagnostic]:
        hits = []
        for diagnostic in self.by_path.get(path, []):
            if (diagnostic.start_line - tolerance) <= end_line and start_line <= (
                diagnostic.end_line + tolerance
            ):
                hits.append(diagnostic)
        return hits

    def failing_tests(self) -> list[TestResult]:
        return [t for t in self.tests if t.status == "failed"]

    def summary(self) -> dict[str, int]:
        return {
            "diagnostics": sum(len(v) for v in self.by_path.values()),
            "tests": len(self.tests),
            "failingTests": len(self.failing_tests()),
        }
