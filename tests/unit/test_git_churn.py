"""Churn parsing: commits touching each path, from one `git log` pass.

Pure parser tests — the invocation itself is one `GitClient.run` call and is
exercised by the pipeline suites. Commit lines are marked with a \\x01 prefix
(`--format=%x01%H`) so a path that happens to look like a 40-hex string can
never be mistaken for a commit boundary.
"""

from __future__ import annotations

from codeatlas.vcs.git import parse_churn

RAW = (
    "\x01" + "a" * 40 + "\n"
    "src/walk.rs\n"
    "src/main.rs\n"
    "\n"
    "\x01" + "b" * 40 + "\n"
    "\n"
    "\x01" + "c" * 40 + "\n"
    "src/walk.rs\n"
)


def test_counts_commits_touching_each_path() -> None:
    assert parse_churn(RAW) == {"src/walk.rs": 2, "src/main.rs": 1}


def test_a_commit_with_no_files_counts_nowhere() -> None:
    only_merge = "\x01" + "b" * 40 + "\n\n"
    assert parse_churn(only_merge) == {}


def test_empty_history_is_empty() -> None:
    assert parse_churn("") == {}


def test_a_40_hex_path_is_not_a_commit_boundary() -> None:
    tricky = "\x01" + "a" * 40 + "\n" + ("f" * 40) + "\n"
    assert parse_churn(tricky) == {"f" * 40: 1}
