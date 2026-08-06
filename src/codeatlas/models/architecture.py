"""Contract models for the derived architecture (architecture.v1.json)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from codeatlas.models.base import ContractModel
from codeatlas.models.graph import GIT_SHA_PATTERN
from codeatlas.models.views import Readability


class ArchitectureContainer(ContractModel):
    key: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""
    technology: str = ""
    level: int | None = Field(default=None, ge=0)
    fan_in: int | None = Field(default=None, ge=0)
    fan_out: int | None = Field(default=None, ge=0)
    #: The project-graph node this box was derived from. Nothing is drawn that
    #: the graph does not contain, and this is how a reader checks that.
    evidence_node_id: str = Field(min_length=1)
    path: str | None = None


class ArchitectureRelationship(ContractModel):
    source_key: str = Field(min_length=1)
    target_key: str = Field(min_length=1)
    description: str = Field(min_length=1)
    evidence_edge_id: str = Field(min_length=1)
    weight: int | None = Field(default=None, ge=1)


class Architecture(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    repository_id: str = Field(min_length=1)
    revision: str = Field(pattern=GIT_SHA_PATTERN)
    system_name: str = Field(min_length=1)
    containers: list[ArchitectureContainer] = Field(default_factory=list)
    relationships: list[ArchitectureRelationship] = Field(default_factory=list)
    readability: Readability | None = None
    notes: list[str] = Field(default_factory=list)
