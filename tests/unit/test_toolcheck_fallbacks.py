"""Tools installed outside PATH must not be reported as missing.

Regression: `psql` (under Program Files) and the pinned Structurizr CLI (under
infra/tools) are both used successfully by the code, but a PATH-only probe
reported them MISSING — an environment report that sends someone chasing a
setup problem that does not exist.
"""

from __future__ import annotations

import sys
from pathlib import Path

from codeatlas.core.toolcheck import REQUIRED_TOOLS, ToolRequirement, probe_tool


def test_a_tool_outside_path_is_found_via_its_known_location() -> None:
    req = ToolRequirement(
        name="fallback-only",
        command="definitely-not-on-path-xyz",
        version_args=("--version",),
        required_for="M0",
        fallback_paths=(sys.executable,),
    )
    status = probe_tool(req)
    assert status.found is True
    assert status.path == sys.executable
    assert status.version is not None


def test_absent_everywhere_is_still_missing() -> None:
    req = ToolRequirement(
        name="absent",
        command="definitely-not-on-path-xyz",
        version_args=("--version",),
        required_for="M0",
        fallback_paths=(r"C:\nope\missing.exe",),
    )
    status = probe_tool(req)
    assert status.found is False
    assert "known install location" in (status.error or "")


def test_tools_installed_off_path_declare_fallbacks() -> None:
    by_name = {r.name: r for r in REQUIRED_TOOLS}
    for name in ("psql", "structurizr", "mmdc"):
        assert by_name[name].fallback_paths, f"{name} is installed off PATH and needs a fallback"


def test_pinned_structurizr_fallback_points_into_the_repo() -> None:
    """The CLI is a pinned zip under infra/tools, not a system install."""
    by_name = {r.name: r for r in REQUIRED_TOOLS}
    (fallback,) = by_name["structurizr"].fallback_paths
    parts = Path(fallback).parts
    assert parts[-4:-2] == ("infra", "tools")
    assert parts[-1].startswith("structurizr")
