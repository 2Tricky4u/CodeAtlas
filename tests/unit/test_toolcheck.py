"""Tests for codeatlas.core.toolcheck — the environment tool-matrix prober.

Written before the implementation (M0 TDD). The prober must never raise on a
missing or broken tool: absence is data, not an error.
"""

from __future__ import annotations

import sys

import pytest

from codeatlas.core.toolcheck import (
    REQUIRED_TOOLS,
    ToolRequirement,
    ToolStatus,
    build_matrix,
    format_matrix,
    probe_tool,
)


def _req(name: str, command: str, *, required_for: str = "M0") -> ToolRequirement:
    return ToolRequirement(
        name=name,
        command=command,
        version_args=("--version",),
        required_for=required_for,
    )


class TestProbeTool:
    def test_present_tool_is_found_with_version(self) -> None:
        # Python itself is guaranteed present in the test environment.
        req = ToolRequirement(
            name="python",
            command=sys.executable,
            version_args=("--version",),
            required_for="M0",
        )
        status = probe_tool(req)
        assert status.found is True
        assert status.name == "python"
        assert status.path is not None
        assert status.version is not None and status.version.strip() != ""
        assert status.error is None

    def test_missing_tool_is_not_found_and_does_not_raise(self) -> None:
        status = probe_tool(_req("nope", "definitely-not-a-real-tool-xyz"))
        assert status.found is False
        assert status.path is None
        assert status.version is None
        assert status.error is not None

    def test_tool_found_but_version_command_fails(self) -> None:
        # `python -c "exit(3)"` exists but its "version" invocation fails:
        # found must still be True (binary exists) with the failure captured.
        req = ToolRequirement(
            name="broken",
            command=sys.executable,
            version_args=("-c", "import sys; sys.exit(3)"),
            required_for="M0",
        )
        status = probe_tool(req)
        assert status.found is True
        assert status.version is None
        assert status.error is not None
        assert "3" in status.error  # exit code surfaced

    def test_version_captured_from_stderr_when_stdout_empty(self) -> None:
        # Some tools print their version to stderr; the prober must not lose it.
        req = ToolRequirement(
            name="stderr-version",
            command=sys.executable,
            version_args=("-c", "import sys; print('tool 9.9.9', file=sys.stderr)"),
            required_for="M0",
        )
        status = probe_tool(req)
        assert status.found is True
        assert status.version == "tool 9.9.9"

    def test_version_hang_is_bounded_by_timeout(self) -> None:
        req = ToolRequirement(
            name="hang",
            command=sys.executable,
            version_args=("-c", "import time; time.sleep(60)"),
            required_for="M0",
        )
        status = probe_tool(req, timeout_s=1.0)
        assert status.found is True
        assert status.version is None
        assert status.error is not None
        assert "timeout" in status.error.lower()


class TestMatrix:
    def test_registry_covers_all_planned_integrations(self) -> None:
        names = {r.name for r in REQUIRED_TOOLS}
        expected = {
            "python",
            "uv",
            "git",
            "cargo",
            "rustc",
            "rust-analyzer",
            "node",
            "npm",
            "claude",
            "psql",
            "gh",
            "java",
            "structurizr",
            "mmdc",
            "clangd",
        }
        assert expected <= names

    def test_registry_names_are_unique(self) -> None:
        names = [r.name for r in REQUIRED_TOOLS]
        assert len(names) == len(set(names))

    def test_build_matrix_returns_status_for_every_requirement(self) -> None:
        matrix = build_matrix()
        assert {s.name for s in matrix} == {r.name for r in REQUIRED_TOOLS}
        assert all(isinstance(s, ToolStatus) for s in matrix)

    def test_format_matrix_lists_every_tool_and_milestone(self) -> None:
        statuses = [
            ToolStatus(name="git", found=True, path="C:/x/git.exe", version="git 2.50", error=None),
            ToolStatus(name="psql", found=False, path=None, version=None, error="not on PATH"),
        ]
        text = format_matrix(statuses)
        assert "git" in text
        assert "psql" in text
        assert "not on PATH" in text

    def test_format_matrix_marks_missing_tools(self) -> None:
        statuses = [
            ToolStatus(name="mmdc", found=False, path=None, version=None, error="not on PATH"),
        ]
        text = format_matrix(statuses)
        assert "MISSING" in text


class TestExitCode:
    def test_matrix_exit_code_zero_when_current_milestone_tools_present(self) -> None:
        from codeatlas.core.toolcheck import matrix_exit_code

        statuses = [
            ToolStatus(name="git", found=True, path="x", version="v", error=None),
            ToolStatus(name="psql", found=False, path=None, version=None, error="missing"),
        ]
        # psql is only required from M5 on; through M4 it must not fail the check.
        assert matrix_exit_code(statuses, through_milestone="M4") == 0

    def test_matrix_exit_code_nonzero_when_required_tool_missing(self) -> None:
        from codeatlas.core.toolcheck import matrix_exit_code

        statuses = [
            ToolStatus(name="git", found=False, path=None, version=None, error="missing"),
        ]
        assert matrix_exit_code(statuses, through_milestone="M0") != 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
