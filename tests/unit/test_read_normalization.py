"""Measured coverage, the pure part: Read-tool paths normalized honestly.

Inside the checkout → repo-relative forward-slash, so coverage can be diffed
against the offered source paths. Outside the checkout → the absolute path,
verbatim-posix: a read that escaped the repo must stay visible as one, never
prettified into looking like repository content.
"""

from __future__ import annotations

import os
from pathlib import Path

from codeatlas.agents.claude_engine import normalize_read_path

CHECKOUT = "C:\\work\\checkouts\\abc" if os.name == "nt" else "/work/checkouts/abc"


def _inside(rel: str) -> str:
    return str(Path(CHECKOUT).joinpath(*rel.split("/")))


def test_a_checkout_file_becomes_repo_relative() -> None:
    assert normalize_read_path(_inside("src/walk.rs"), CHECKOUT) == "src/walk.rs"


def test_nested_paths_keep_forward_slashes() -> None:
    assert normalize_read_path(_inside("src/exec/job.rs"), CHECKOUT) == "src/exec/job.rs"


def test_an_outside_read_stays_absolute() -> None:
    outside = "C:\\work\\secrets\\key.pem" if os.name == "nt" else "/work/secrets/key.pem"
    result = normalize_read_path(outside, CHECKOUT)
    assert result.endswith("work/secrets/key.pem")
    assert result != "key.pem"


def test_a_relative_path_is_taken_as_checkout_relative() -> None:
    assert normalize_read_path("src\\cache.rs", CHECKOUT) == "src/cache.rs"


class TestGrepTargets:
    """The live fd run showed two of three reviewers reading exclusively
    through Grep — 0 opens reported while citing exact lines. Single-file
    greps count; directory greps attribute to no file (undercounting is the
    honest failure direction)."""

    def test_a_file_target_counts(self) -> None:
        from codeatlas.agents.claude_engine import _looks_like_file

        assert _looks_like_file("src/walk.rs")
        assert _looks_like_file("C:\\work\\checkouts\\abc\\src\\exec\\job.rs")

    def test_a_directory_target_does_not(self) -> None:
        from codeatlas.agents.claude_engine import _looks_like_file

        assert not _looks_like_file("src")
        assert not _looks_like_file("src/exec")

    def test_an_extensionless_file_undercounts_and_that_is_the_chosen_direction(self) -> None:
        from codeatlas.agents.claude_engine import _looks_like_file

        assert not _looks_like_file("Makefile")
