"""The ADR audit as a contract, not an ad-hoc dict (G4).

The audit has produced a list of hand-built dictionaries since M13. Everything
else the pipeline emits is pinned by a JSON Schema and checked in both
directions by the drift test; this was not, which meant its shape could change
under the dashboard without anything failing.

It also dropped two fields the parser already had: `date` and `supersededBy`. A
reader wants decisions in the order they were taken and wants to know which ones
were replaced — an ADR list without those is a set, not a history.
"""

from __future__ import annotations

from codeatlas.adr.audit import AssertionAudit
from codeatlas.adr.parser import Decision
from codeatlas.models.adr_audit import AdrAudit
from codeatlas.project.decisions import build_adr_audit

REVISION = "e" * 40


def decision(
    number: int, *, status: str = "accepted", superseded_by: str | None = None
) -> Decision:
    return Decision(
        path=f"docs/adr/adr-{number:04d}-layering.md",
        number=number,
        title="Layering",
        status=status,
        date=f"2026-0{number}-01",
        superseded_by=superseded_by,
        decision_text="Dependencies flow downward.",
        content_sha256="sha256:" + "0" * 64,
    )


def audit(number: int, result: str = "conformant", **overrides: object) -> AssertionAudit:
    fields: dict[str, object] = {
        "adr_path": f"docs/adr/adr-{number:04d}-layering.md",
        "adr_label": f"ADR-{number:04d}",
        "status": "accepted",
        "assertion": "Dependencies flow downward.",
        "audit_result": result,
        "confidence": 0.9,
        "requires_human_decision": result == "probable-drift",
        "affected_node_ids": [],
        "evidence": [],
        "detail": "",
    }
    fields.update(overrides)
    return AssertionAudit(**fields)  # type: ignore[arg-type]


class TestTheAuditCarriesEnoughToReadAsAHistory:
    def test_the_date_survives_from_the_parser(self) -> None:
        model = build_adr_audit(REVISION, [(decision(2), audit(2))])
        assert model.decisions[0].date == "2026-02-01"

    def test_supersession_survives(self) -> None:
        superseded = decision(1, status="superseded", superseded_by="ADR-0007")
        model = build_adr_audit(REVISION, [(superseded, audit(1, "intentionally-superseded"))])
        assert model.decisions[0].superseded_by == "ADR-0007"

    def test_decisions_are_ordered_by_number_not_by_directory_listing(self) -> None:
        pairs = [(decision(n), audit(n)) for n in (3, 1, 2)]
        model = build_adr_audit(REVISION, pairs)
        assert [d.number for d in model.decisions] == [1, 2, 3]

    def test_an_adr_with_no_number_sorts_last_rather_than_crashing(self) -> None:
        unnumbered = Decision(
            path="docs/adr/notes.md",
            number=None,
            title="Notes",
            status="proposed",
            date=None,
            superseded_by=None,
            decision_text="",
            content_sha256="sha256:" + "1" * 64,
        )
        model = build_adr_audit(REVISION, [(unnumbered, audit(9)), (decision(1), audit(1))])
        assert [d.number for d in model.decisions] == [1, None]


class TestTheOutcomeIsNotSoftened:
    def test_probable_drift_is_reported_as_such(self) -> None:
        model = build_adr_audit(REVISION, [(decision(1), audit(1, "probable-drift"))])
        assert model.decisions[0].audit_result == "probable-drift"
        assert model.decisions[0].requires_human_decision

    def test_a_drifting_decision_is_counted_in_the_notes(self) -> None:
        pairs = [(decision(1), audit(1, "probable-drift")), (decision(2), audit(2))]
        model = build_adr_audit(REVISION, pairs)
        assert any("1" in note and "drift" in note for note in model.notes)

    def test_no_adrs_at_all_is_stated_rather_than_left_blank(self) -> None:
        """The common case on a real project — ripgrep has no docs/adr."""
        model = build_adr_audit(REVISION, [])
        assert model.decisions == []
        assert any("no" in note.lower() for note in model.notes)


class TestItRoundTrips:
    def test_the_contract_dump_reparses(self) -> None:
        model = build_adr_audit(REVISION, [(decision(1), audit(1))])
        assert AdrAudit.model_validate(model.contract_dump()) == model
