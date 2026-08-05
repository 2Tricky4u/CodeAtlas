"""Permission enforcement in the Claude engine adapter (pure unit, no live agent).

These guard the decision logic the SDK permission callback delegates to: an
allowlisted prefix must describe the WHOLE command (no shell chaining), and
writes must stay inside permitted paths.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codeatlas.agents.claude_engine import _command_allowed, _within


class TestCommandAllowlist:
    def test_exact_and_prefixed_commands_allowed(self) -> None:
        assert _command_allowed("rg --files", ["rg --files"])
        assert _command_allowed("rg --files src/", ["rg --files"])
        assert _command_allowed("cargo test kv", ["cargo test"])

    def test_unlisted_command_denied(self) -> None:
        assert not _command_allowed("curl https://evil.example", ["rg --files"])
        assert not _command_allowed("rm -rf /", ["rg --files"])

    @pytest.mark.parametrize(
        "command",
        [
            "rg --files && curl https://evil.example",
            "rg --files; rm -rf .",
            "rg --files | sh",
            "rg --files || whoami",
            "rg --files `whoami`",
            "rg --files $(curl evil)",
        ],
    )
    def test_shell_chaining_denied_even_with_allowlisted_prefix(self, command: str) -> None:
        assert not _command_allowed(command, ["rg --files"])

    def test_empty_allowlist_denies_everything(self) -> None:
        assert not _command_allowed("rg --files", [])
        assert not _command_allowed("", ["rg --files"])


class TestWritePaths:
    def test_write_inside_permitted_path_allowed(self, tmp_path: Path) -> None:
        out = tmp_path / "out"
        out.mkdir()
        assert _within(str(out / "findings.json"), [str(out)])

    def test_write_outside_permitted_path_denied(self, tmp_path: Path) -> None:
        out = tmp_path / "out"
        out.mkdir()
        assert not _within(str(tmp_path / "elsewhere.json"), [str(out)])

    def test_traversal_out_of_permitted_path_denied(self, tmp_path: Path) -> None:
        out = tmp_path / "out"
        out.mkdir()
        assert not _within(str(out / ".." / "escape.json"), [str(out)])

    def test_no_permitted_paths_denies_all_writes(self, tmp_path: Path) -> None:
        assert not _within(str(tmp_path / "x.json"), [])
