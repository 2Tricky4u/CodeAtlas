"""Contract models for protocol models (protocol-model.v1.json)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from codeatlas.models.base import ContractModel


class ProtocolEvidence(ContractModel):
    path: str = Field(min_length=1)
    #: A graph node id, when the element corresponds to one.
    symbol: str | None = None
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)


class ProtocolParticipant(ContractModel):
    name: str = Field(min_length=1)
    description: str = ""
    evidence: ProtocolEvidence


class ProtocolMessage(ContractModel):
    name: str = Field(min_length=1)
    producer: str = Field(min_length=1)
    consumer: str = Field(min_length=1)
    message_schema: str | None = Field(default=None, alias="schema")
    #: Required: a message with no source range is a claim about a protocol
    #: nobody can check, and this pipeline deletes those rather than drawing them.
    evidence: ProtocolEvidence


class ProtocolTimeout(ContractModel):
    state: str = Field(min_length=1)
    duration: str = Field(pattern=r"^P")  # ISO-8601 duration
    transition: str = Field(min_length=1)
    evidence: ProtocolEvidence | None = None


class Protocol(ContractModel):
    id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    transport: str = Field(min_length=1)
    framing: str = Field(min_length=1)
    participants: list[ProtocolParticipant] = Field(min_length=1)
    states: list[str] = Field(default_factory=list)
    messages: list[ProtocolMessage] = Field(default_factory=list)
    timeouts: list[ProtocolTimeout] = Field(default_factory=list)
    evidence: list[ProtocolEvidence] = Field(min_length=1)


class DroppedElement(ContractModel):
    kind: Literal["participant", "message", "timeout"]
    name: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class ProtocolModel(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    #: Null when this project has no protocol worth modelling, which is the
    #: common case. A batch program forced into a sequence diagram produces a
    #: confident-looking picture of something that does not exist.
    protocol: Protocol | None = None
    dropped_elements: list[DroppedElement] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
