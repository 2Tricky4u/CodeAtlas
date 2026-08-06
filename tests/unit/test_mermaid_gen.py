"""Protocol model -> Mermaid sequence and state diagrams (pure generation)."""

from __future__ import annotations

from codeatlas.artifacts.mermaid.gen import sequence_diagram, state_diagram
from codeatlas.models.protocol import (
    Protocol,
    ProtocolEvidence,
    ProtocolMessage,
    ProtocolModel,
    ProtocolParticipant,
    ProtocolTimeout,
)

EVIDENCE = ProtocolEvidence(path="kvstore/src/api.rs")


def _message(name: str, producer: str = "client", consumer: str = "server") -> ProtocolMessage:
    return ProtocolMessage(name=name, producer=producer, consumer=consumer, evidence=EVIDENCE)


def _model(**overrides) -> ProtocolModel:  # type: ignore[no-untyped-def]
    protocol = Protocol(
        id="kvstore-wire",
        version="1",
        transport="tcp",
        framing="line",
        participants=overrides.get(
            "participants",
            [
                ProtocolParticipant(name="client", evidence=EVIDENCE),
                ProtocolParticipant(name="server", evidence=EVIDENCE),
            ],
        ),
        states=overrides.get("states", ["Idle", "AwaitingReply"]),
        messages=overrides.get("messages", [_message("Get")]),
        timeouts=overrides.get(
            "timeouts",
            [ProtocolTimeout(state="AwaitingReply", duration="PT5S", transition="Idle")],
        ),
        evidence=[ProtocolEvidence(path="kvstore/src/api.rs", symbol="handle_request")],
    )
    return ProtocolModel(protocol=protocol)


class TestSequence:
    def test_declares_participants_and_messages(self) -> None:
        diagram = sequence_diagram(_model())
        assert diagram.startswith("sequenceDiagram")
        assert "participant client as client" in diagram
        assert "client->>server: Get" in diagram

    def test_timeout_is_annotated(self) -> None:
        assert "times out after PT5S" in sequence_diagram(_model())

    def test_undeclared_participant_is_flagged_not_dropped(self) -> None:
        diagram = sequence_diagram(_model(messages=[_message("Ghost", producer="nobody")]))
        assert "skipped Ghost" in diagram

    def test_labels_are_sanitized(self) -> None:
        diagram = sequence_diagram(_model(messages=[_message('Get "key"; drop')]))
        assert '"' not in diagram.split("participant")[-1] or "'key'" in diagram
        assert ";" not in diagram

    def test_generation_is_deterministic(self) -> None:
        assert sequence_diagram(_model()) == sequence_diagram(_model())

    def test_no_protocol_produces_no_diagram(self) -> None:
        """A project without a protocol must not get a picture of one."""
        assert sequence_diagram(ProtocolModel(protocol=None)) == ""


class TestState:
    def test_states_and_transitions(self) -> None:
        diagram = state_diagram(_model())
        assert diagram.startswith("stateDiagram-v2")
        assert "[*] --> Idle" in diagram
        assert "timeout PT5S" in diagram

    def test_a_stateless_protocol_gets_no_state_chart(self) -> None:
        """Most request/response protocols are stateless, and an empty state
        chart is a heading over blank space rather than information."""
        assert state_diagram(_model(states=[], timeouts=[])) == ""

    def test_no_protocol_produces_no_diagram(self) -> None:
        assert state_diagram(ProtocolModel(protocol=None)) == ""
