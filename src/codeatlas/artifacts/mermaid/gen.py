"""Sequence and state diagrams derived from a protocol model.

Both views come from the same `protocol-model.v1` record, so they cannot drift
apart: a diagram is a rendering of the model, never an independent drawing. The
model carries its own evidence, so every participant and transition on a diagram
traces back to code.
"""

from __future__ import annotations

from codeatlas.models.protocol import ProtocolModel


def _label(value: str) -> str:
    """Mermaid-safe label: no quotes, no newlines, no semicolons."""
    return value.replace('"', "'").replace("\n", " ").replace(";", ",").strip()


def _alias(value: str, index: int) -> str:
    cleaned = "".join(ch for ch in value if ch.isalnum())
    return cleaned or f"P{index}"


def sequence_diagram(model: ProtocolModel) -> str:
    """Message exchange between participants, in declaration order."""
    protocol = model.protocol
    aliases = {name: _alias(name, i) for i, name in enumerate(protocol.participants)}

    lines = ["sequenceDiagram", "    autonumber"]
    for name in protocol.participants:
        lines.append(f"    participant {aliases[name]} as {_label(name)}")

    for message in protocol.messages:
        source = aliases.get(message.producer)
        target = aliases.get(message.consumer)
        if source is None or target is None:
            # A message naming a participant the model never declared is a model
            # defect; surface it in the diagram rather than dropping it silently.
            lines.append(f"    %% skipped {_label(message.name)}: undeclared participant")
            continue
        lines.append(f"    {source}->>{target}: {_label(message.name)}")

    for timeout in protocol.timeouts:
        lines.append(
            f"    Note over {aliases.get(protocol.participants[0], 'P0')}: "
            f"{_label(timeout.state)} times out after {_label(timeout.duration)} "
            f"-> {_label(timeout.transition)}"
        )
    return "\n".join(lines) + "\n"


def state_diagram(model: ProtocolModel) -> str:
    """Legal states and the timeout transitions between them."""
    protocol = model.protocol
    lines = ["stateDiagram-v2"]
    if protocol.states:
        lines.append(f"    [*] --> {_alias(protocol.states[0], 0)}")
    for index, state in enumerate(protocol.states):
        lines.append(f"    {_alias(state, index)} : {_label(state)}")
    for timeout in protocol.timeouts:
        source = _alias(timeout.state, 0)
        target = _alias(timeout.transition, 1)
        lines.append(f"    {source} --> {target} : timeout {_label(timeout.duration)}")
    return "\n".join(lines) + "\n"
