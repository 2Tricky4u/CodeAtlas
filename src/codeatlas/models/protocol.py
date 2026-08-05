"""Contract models for protocol models (protocol-model.v1.json)."""

from __future__ import annotations

from pydantic import Field

from codeatlas.models.base import ContractModel


class ProtocolMessage(ContractModel):
    name: str = Field(min_length=1)
    producer: str = Field(min_length=1)
    consumer: str = Field(min_length=1)
    message_schema: str | None = Field(default=None, alias="schema")


class ProtocolTimeout(ContractModel):
    state: str = Field(min_length=1)
    duration: str = Field(pattern=r"^P")  # ISO-8601 duration
    transition: str = Field(min_length=1)


class ProtocolEvidence(ContractModel):
    path: str = Field(min_length=1)
    symbol: str | None = None
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)


class Protocol(ContractModel):
    id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    transport: str = Field(min_length=1)
    framing: str = Field(min_length=1)
    participants: list[str] = Field(min_length=1)
    states: list[str]
    messages: list[ProtocolMessage]
    timeouts: list[ProtocolTimeout]
    evidence: list[ProtocolEvidence] = Field(min_length=1)


class ProtocolModel(ContractModel):
    protocol: Protocol
