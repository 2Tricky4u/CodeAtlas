"""Source resolution: remote detection and the fetch-then-retry fallback.

`resolve_in_mirror`'s fallback is what makes analyzing a pull-request head
possible at all — a mirror clone brings branch tips, and a PR head lives
outside them. Nothing exercised it: every start_run in the suite passes a
local path.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from codeatlas.pipeline.source import is_remote, resolve_in_mirror


@pytest.mark.parametrize(
    "source",
    [
        "https://github.com/o/r",
        "http://example.org/r.git",
        "git://example.org/r.git",
        "ssh://git@example.org/o/r.git",
        "git@github.com:o/r.git",
    ],
)
def test_remote_sources_are_remote(source: str) -> None:
    assert is_remote(source)


@pytest.mark.parametrize("source", ["C:\\repos\\x", "./x", "../elsewhere", "repo", "gitlab/x"])
def test_local_paths_are_not(source: str) -> None:
    assert not is_remote(source)


class RecoveringGit:
    """Fails the first resolve (the ref is not in the mirror), then succeeds."""

    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.resolve_calls = 0

    def resolve_sha(self, mirror: Path, ref: str) -> str:
        self.resolve_calls += 1
        if self.resolve_calls == 1:
            raise RuntimeError(f"unknown ref {ref}")
        return "a" * 40

    def run(self, args: list[str], cwd: Path, check: bool = True) -> None:
        self.commands.append(args)


def test_a_remote_unknown_ref_is_fetched_then_resolved() -> None:
    git = RecoveringGit()
    deps = SimpleNamespace(git=git)
    sha = resolve_in_mirror(deps, Path("mirror"), "abc123", remote=True)  # type: ignore[arg-type]
    assert sha == "a" * 40
    assert ["fetch", "origin", "abc123"] in git.commands
    # The fetch that makes PR-head analysis possible at all.
    assert ["fetch", "origin", "+refs/pull/*/head:refs/pull/*/head"] in git.commands


def test_a_local_unknown_ref_reraises_without_fetching() -> None:
    class FailingGit:
        def __init__(self) -> None:
            self.commands: list[list[str]] = []

        def resolve_sha(self, mirror: Path, ref: str) -> str:
            raise RuntimeError("unknown ref")

        def run(self, args: list[str], cwd: Path, check: bool = True) -> None:
            self.commands.append(args)

    git = FailingGit()
    deps = SimpleNamespace(git=git)
    with pytest.raises(RuntimeError, match="unknown ref"):
        resolve_in_mirror(deps, Path("mirror"), "abc123", remote=False)  # type: ignore[arg-type]
    assert git.commands == [], "there is no origin to fetch from for a local path"
