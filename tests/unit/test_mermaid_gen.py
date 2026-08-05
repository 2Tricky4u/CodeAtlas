"""Protocol model -> Mermaid sequence and state diagrams (pure generation)."""

from __future__ import annotations

from codeatlas.artifacts.mermaid.gen import sequence_diagram, state_diagram
from codeatlas.models.protocol import (
    Protocol,
    ProtocolEvidence,
    ProtocolMessage,
    ProtocolModel,
    ProtocolTimeout,
)


def _model(**overrides) -> ProtocolModel:  # type: ignore[no-untyped-def]
    protocol = Protocol(
        id="kvstore-wire",
        version="1",
        transport="tcp",
        framing="line",
        participants=overrides.get("participants", ["client", "server"]),
        states=overrides.get("states", ["Idle", "AwaitingReply"]),
        messages=overrides.get(
            "messages",
            [ProtocolMessage(name="Get", producer="client", consumer="server")],
        ),
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
        diagram = sequence_diagram(
            _model(messages=[ProtocolMessage(name="Ghost", producer="nobody", consumer="server")])
        )
        assert "skipped Ghost" in diagram

    def test_labels_are_sanitized(self) -> None:
        diagram = sequence_diagram(
            _model(
                messages=[
                    ProtocolMessage(name='Get "key"; drop', producer="client", consumer="server")
                ]
            )
        )
        assert '"' not in diagram.split("participant")[-1] or "'key'" in diagram
        assert ";" not in diagram

    def test_generation_is_deterministic(self) -> None:
        assert sequence_diagram(_model()) == sequence_diagram(_model())


class TestState:
    def test_states_and_transitions(self) -> None:
        diagram = state_diagram(_model())
        assert diagram.startswith("stateDiagram-v2")
        assert "[*] --> Idle" in diagram
        assert "timeout PT5S" in diagram

    def test_empty_states_do_not_crash(self) -> None:
        diagram = state_diagram(_model(states=[], timeouts=[]))
        assert diagram.strip() == "stateDiagram-v2"
