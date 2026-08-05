"""ADR parsing: status, lifecycle, and the assertions a decision makes.

Status matters more than prose here: only Accepted (and superseded/deprecated,
tracked separately) decisions constrain the code, and the audit must never
mutate a decision's lifecycle on its own.
"""

from __future__ import annotations

from pathlib import Path

from codeatlas.adr.parser import Decision, parse_adr, parse_adr_directory


def _write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8", newline="\n")
    return path


ACCEPTED = """# ADR-0001: Strict downward layering

- Status: Accepted
- Date: 2026-01-15

## Decision

Dependencies flow strictly downward: `api` may use `cache`, `cache` may use
`storage`, and `storage` depends on nothing inside this crate. Upward imports
are prohibited.

## Consequences

The storage layer stays reusable.
"""

SUPERSEDED = """# ADR-0002: Synchronous payment calls

- Status: Superseded by ADR-0007
- Date: 2025-06-01

## Decision

Checkout calls the payment service synchronously.
"""

MADR_STYLE = """---
status: proposed
date: 2026-02-02
---
# Use JSON framing

## Context and problem statement

We need a wire format.

## Decision

Messages are newline-delimited JSON.
"""


class TestSingleDocument:
    def test_parses_number_title_and_status(self, tmp_path: Path) -> None:
        decision = parse_adr(_write(tmp_path, "adr-0001-layering.md", ACCEPTED))
        assert decision.number == 1
        assert "layering" in decision.title.lower()
        assert decision.status == "accepted"

    def test_extracts_the_decision_section(self, tmp_path: Path) -> None:
        decision = parse_adr(_write(tmp_path, "adr-0001-layering.md", ACCEPTED))
        assert "strictly downward" in decision.decision_text
        assert "reusable" not in decision.decision_text, "consequences are not the decision"

    def test_superseded_status_and_reference(self, tmp_path: Path) -> None:
        decision = parse_adr(_write(tmp_path, "adr-0002-sync.md", SUPERSEDED))
        assert decision.status == "superseded"
        assert decision.superseded_by == "ADR-0007"

    def test_frontmatter_status_is_read(self, tmp_path: Path) -> None:
        decision = parse_adr(_write(tmp_path, "0003-json-framing.md", MADR_STYLE))
        assert decision.status == "proposed"
        assert decision.number == 3

    def test_content_hash_is_stable_and_content_sensitive(self, tmp_path: Path) -> None:
        first = parse_adr(_write(tmp_path, "adr-0001-a.md", ACCEPTED))
        second = parse_adr(_write(tmp_path, "adr-0001-b.md", ACCEPTED))
        third = parse_adr(_write(tmp_path, "adr-0001-c.md", ACCEPTED + "\nmore text\n"))
        assert first.content_sha256 == second.content_sha256
        assert third.content_sha256 != first.content_sha256

    def test_unknown_status_defaults_to_proposed_not_accepted(self, tmp_path: Path) -> None:
        """An unparseable status must never be treated as binding."""
        decision = parse_adr(
            _write(tmp_path, "adr-0009-x.md", "# ADR-0009: X\n\nNo status here.\n")
        )
        assert decision.status == "proposed"


class TestDirectory:
    def test_parses_all_and_sorts_by_number(self, tmp_path: Path) -> None:
        _write(tmp_path, "adr-0002-sync.md", SUPERSEDED)
        _write(tmp_path, "adr-0001-layering.md", ACCEPTED)
        _write(tmp_path, "index.md", "# Index\n\nnot a decision\n")
        decisions = parse_adr_directory(tmp_path)
        assert [d.number for d in decisions] == [1, 2]

    def test_missing_directory_yields_nothing(self, tmp_path: Path) -> None:
        assert parse_adr_directory(tmp_path / "nope") == []

    def test_binding_decisions_are_only_accepted_ones(self, tmp_path: Path) -> None:
        _write(tmp_path, "adr-0001-layering.md", ACCEPTED)
        _write(tmp_path, "adr-0002-sync.md", SUPERSEDED)
        _write(tmp_path, "adr-0003-json.md", MADR_STYLE)
        binding = [d for d in parse_adr_directory(tmp_path) if d.is_binding]
        assert [d.number for d in binding] == [1]


class TestFixtureAdr:
    def test_the_kvstore_fixture_adr_parses_as_accepted(self) -> None:
        root = Path(__file__).resolve().parents[2] / "fixtures" / "rust-flawed-crate"
        decisions = parse_adr_directory(root / "docs" / "adr")
        assert decisions
        layering = decisions[0]
        assert isinstance(layering, Decision)
        assert layering.is_binding
        assert "downward" in layering.decision_text.lower()
