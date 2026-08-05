"""Generated protocol diagrams must actually render (M13 gate). Marker: subproc.

Text that looks like Mermaid is not a diagram until mmdc has drawn it. This
closes the loop for the generator: every diagram shape it can produce is proven
renderable, not merely well-intentioned.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codeatlas.artifacts.mermaid.gen import sequence_diagram, state_diagram
from codeatlas.artifacts.mermaid.validate import mmdc_path, render
from codeatlas.models.protocol import (
    Protocol,
    ProtocolEvidence,
    ProtocolMessage,
    ProtocolModel,
    ProtocolTimeout,
)

pytestmark = pytest.mark.subproc


@pytest.fixture(autouse=True)
def _require_mmdc() -> None:
    if mmdc_path() is None:
        pytest.skip("mmdc not installed")


def _model() -> ProtocolModel:
    return ProtocolModel(
        protocol=Protocol(
            id="kvstore-wire",
            version="1",
            transport="tcp",
            framing="line-delimited",
            participants=["client", "kvstore-api", "file-store"],
            states=["Idle", "AwaitingReply", "Stored"],
            messages=[
                ProtocolMessage(name="Get key", producer="client", consumer="kvstore-api"),
                ProtocolMessage(name="Read blob", producer="kvstore-api", consumer="file-store"),
                ProtocolMessage(name="Value", producer="file-store", consumer="kvstore-api"),
                ProtocolMessage(name="Response", producer="kvstore-api", consumer="client"),
            ],
            timeouts=[ProtocolTimeout(state="AwaitingReply", duration="PT5S", transition="Idle")],
            evidence=[ProtocolEvidence(path="kvstore/src/api.rs", symbol="handle_request")],
        )
    )


def test_generated_sequence_diagram_renders(tmp_path: Path) -> None:
    source = tmp_path / "sequence.mmd"
    source.write_text(sequence_diagram(_model()), encoding="utf-8", newline="\n")
    result = render(source, tmp_path / "sequence.svg")
    assert result.size_bytes > 0
    svg = result.svg.read_text(encoding="utf-8")
    assert "kvstore-api" in svg, "participants must appear in the rendered output"


def test_generated_state_diagram_renders(tmp_path: Path) -> None:
    source = tmp_path / "state.mmd"
    source.write_text(state_diagram(_model()), encoding="utf-8", newline="\n")
    result = render(source, tmp_path / "state.svg")
    assert result.size_bytes > 0


def test_hostile_labels_still_render(tmp_path: Path) -> None:
    """Repository-derived names contain quotes, semicolons and arrows."""
    model = ProtocolModel(
        protocol=Protocol(
            id="p",
            version="1",
            transport="tcp",
            framing="json",
            participants=['weird "client"', "a;b", "x-->y"],
            states=["S1"],
            messages=[
                ProtocolMessage(
                    name='msg "with" quotes; and -->', producer='weird "client"', consumer="a;b"
                )
            ],
            timeouts=[],
            evidence=[ProtocolEvidence(path="a.rs")],
        )
    )
    source = tmp_path / "hostile.mmd"
    source.write_text(sequence_diagram(model), encoding="utf-8", newline="\n")
    assert render(source, tmp_path / "hostile.svg").size_bytes > 0
