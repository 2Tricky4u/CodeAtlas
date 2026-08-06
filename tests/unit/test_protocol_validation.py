"""A protocol model is checked against the code it claims to describe (G5).

Third artifact under the same rule as the two narratives, and the one where the
temptation to invent is strongest. A sequence diagram is the most confident
picture this tool can draw — arrows between named participants, in order, with
timeouts — and almost none of that is visible in a dependency graph. It has to
be read out of the source, which means it has to be checkable against the
source, which means an element whose evidence does not resolve is deleted.

The refusal matters as much as the validation. Most projects have no protocol:
ripgrep is a batch program that reads files and writes lines. Forcing a sequence
diagram onto it would produce exactly the artifact this project exists to avoid
— something that looks authoritative and describes nothing.
"""

from __future__ import annotations

from codeatlas.models.protocol import (
    Protocol,
    ProtocolEvidence,
    ProtocolMessage,
    ProtocolModel,
    ProtocolParticipant,
    ProtocolTimeout,
)
from codeatlas.project.protocol import ProtocolIndex, validate_protocol_model

INDEX = ProtocolIndex(
    revision="f" * 40,
    paths={"kvstore/src/api.rs", "kvstore/src/main.rs"},
    symbols={"sym:handle_request", "sym:Response"},
    line_counts={"kvstore/src/api.rs": 60},
)


def evidence(path: str = "kvstore/src/api.rs", **kwargs: object) -> ProtocolEvidence:
    return ProtocolEvidence(path=path, **kwargs)  # type: ignore[arg-type]


def participant(name: str, path: str = "kvstore/src/api.rs") -> ProtocolParticipant:
    return ProtocolParticipant(name=name, evidence=evidence(path))


def message(
    name: str, producer: str, consumer: str, path: str = "kvstore/src/api.rs"
) -> ProtocolMessage:
    return ProtocolMessage(name=name, producer=producer, consumer=consumer, evidence=evidence(path))


def model(
    participants: list[ProtocolParticipant] | None = None,
    messages: list[ProtocolMessage] | None = None,
    timeouts: list[ProtocolTimeout] | None = None,
) -> ProtocolModel:
    # `is None`, not `or`: an explicitly empty list is a case these tests need
    # to express, and `or` would silently substitute the default for it.
    return ProtocolModel(
        protocol=Protocol(
            id="kv-wire",
            version="1",
            transport="tcp",
            framing="line",
            participants=(
                [participant("client"), participant("server")]
                if participants is None
                else participants
            ),
            states=["idle", "serving"],
            messages=[message("get", "client", "server")] if messages is None else messages,
            timeouts=[] if timeouts is None else timeouts,
            evidence=[evidence()],
        )
    )


class TestElementsThatResolveSurvive:
    def test_a_message_read_from_a_real_file_is_kept(self) -> None:
        kept, dropped = validate_protocol_model(model(), INDEX)
        assert dropped == []
        assert kept.protocol is not None
        assert [m.name for m in kept.protocol.messages] == ["get"]

    def test_evidence_naming_a_known_symbol_is_kept(self) -> None:
        msg = ProtocolMessage(
            name="put",
            producer="client",
            consumer="server",
            evidence=evidence(symbol="sym:handle_request"),
        )
        kept, dropped = validate_protocol_model(model(messages=[msg]), INDEX)
        assert dropped == []
        assert kept.protocol is not None


class TestElementsThatDoNotResolveAreDeleted:
    def test_a_message_from_a_file_that_does_not_exist_is_dropped(self) -> None:
        msg = message("ghost", "client", "server", path="kvstore/src/rpc.rs")
        kept, dropped = validate_protocol_model(model(messages=[msg]), INDEX)
        assert [d.name for d in dropped] == ["ghost"]
        assert kept.protocol is not None
        assert kept.protocol.messages == []

    def test_a_symbol_the_graph_does_not_have_is_dropped(self) -> None:
        msg = ProtocolMessage(
            name="invented",
            producer="client",
            consumer="server",
            evidence=evidence(symbol="sym:nope"),
        )
        _, dropped = validate_protocol_model(model(messages=[msg]), INDEX)
        assert len(dropped) == 1
        assert "sym:nope" in dropped[0].reason

    def test_a_line_past_the_end_of_the_file_is_dropped(self) -> None:
        msg = ProtocolMessage(
            name="offpage",
            producer="client",
            consumer="server",
            evidence=evidence(start_line=900),
        )
        _, dropped = validate_protocol_model(model(messages=[msg]), INDEX)
        assert len(dropped) == 1
        assert "past the end" in dropped[0].reason

    def test_a_participant_that_does_not_resolve_is_dropped(self) -> None:
        kept, dropped = validate_protocol_model(
            model(
                participants=[participant("client"), participant("ghost", "nowhere.rs")],
                messages=[],
            ),
            INDEX,
        )
        assert [d.name for d in dropped] == ["ghost"]
        assert kept.protocol is not None
        assert [p.name for p in kept.protocol.participants] == ["client"]


class TestAMessageCannotOutliveItsParticipants:
    def test_a_message_whose_producer_was_dropped_goes_with_it(self) -> None:
        """An arrow from a box that is not drawn is worse than no arrow."""
        kept, dropped = validate_protocol_model(
            model(
                participants=[participant("client"), participant("ghost", "nowhere.rs")],
                messages=[message("get", "client", "ghost")],
            ),
            INDEX,
        )
        assert {d.name for d in dropped} == {"ghost", "get"}
        assert kept.protocol is not None
        assert kept.protocol.messages == []

    def test_the_reason_names_the_missing_participant(self) -> None:
        _, dropped = validate_protocol_model(
            model(
                participants=[participant("client"), participant("ghost", "nowhere.rs")],
                messages=[message("get", "client", "ghost")],
            ),
            INDEX,
        )
        message_drop = next(d for d in dropped if d.name == "get")
        assert "ghost" in message_drop.reason


class TestRefusal:
    def test_a_null_protocol_survives_untouched(self) -> None:
        """ "This project has no protocol" is an answer, not a failure."""
        empty = ProtocolModel(protocol=None, notes=["no protocol interactions found"])
        kept, dropped = validate_protocol_model(empty, INDEX)
        assert kept.protocol is None
        assert dropped == []
        assert kept.notes == ["no protocol interactions found"]

    def test_a_protocol_left_with_no_participants_becomes_a_refusal(self) -> None:
        """A diagram of nothing is not a smaller diagram."""
        kept, dropped = validate_protocol_model(
            model(participants=[participant("ghost", "nowhere.rs")], messages=[]), INDEX
        )
        assert kept.protocol is None
        assert len(dropped) == 1
        assert any("nothing" in note or "no participant" in note for note in kept.notes)

    def test_revalidating_changes_nothing(self) -> None:
        kept, _ = validate_protocol_model(model(), INDEX)
        again, dropped_again = validate_protocol_model(kept, INDEX)
        assert dropped_again == []
        assert again.protocol == kept.protocol
