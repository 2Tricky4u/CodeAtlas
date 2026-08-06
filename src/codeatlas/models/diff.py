"""Contract models for the structural graph diff (graph-diff.v1.json)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from codeatlas.models.base import ContractModel
from codeatlas.models.graph import GIT_SHA_PATTERN


class DiffNode(ContractModel):
    stable_key: str = Field(min_length=1)
    id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    label: str = Field(min_length=1)
    path: str | None = None
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)


class MovedNode(ContractModel):
    stable_key: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    label: str = Field(min_length=1)
    before_path: str = Field(min_length=1)
    after_path: str = Field(min_length=1)


class DiffEdge(ContractModel):
    id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    source_key: str = Field(min_length=1)
    target_key: str = Field(min_length=1)
    source_label: str = Field(min_length=1)
    target_label: str = Field(min_length=1)
    source_path: str | None = None
    target_path: str | None = None


class VersionChange(ContractModel):
    name: str = Field(min_length=1)
    before: str = Field(min_length=1)
    after: str = Field(min_length=1)


class RenameGuess(ContractModel):
    """An inference. Never presented as a fact, never rewrites one."""

    before_key: str = Field(min_length=1)
    after_key: str = Field(min_length=1)
    before_label: str = Field(min_length=1)
    after_label: str = Field(min_length=1)
    path: str | None = None
    confidence: float = Field(gt=0, le=1)
    basis: str = Field(min_length=1)


class NodeDelta(ContractModel):
    added: list[DiffNode] = Field(default_factory=list)
    removed: list[DiffNode] = Field(default_factory=list)
    moved: list[MovedNode] = Field(default_factory=list)
    touched: list[DiffNode] = Field(default_factory=list)


class EdgeDelta(ContractModel):
    added: list[DiffEdge] = Field(default_factory=list)
    removed: list[DiffEdge] = Field(default_factory=list)


class DiffSummary(ContractModel):
    nodes_added: int = Field(ge=0)
    nodes_removed: int = Field(ge=0)
    nodes_moved: int = Field(ge=0)
    nodes_touched: int = Field(ge=0)
    edges_added: int = Field(ge=0)
    edges_removed: int = Field(ge=0)


class GraphDiff(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    base_revision: str = Field(pattern=GIT_SHA_PATTERN)
    head_revision: str = Field(pattern=GIT_SHA_PATTERN)
    nodes: NodeDelta
    edges: EdgeDelta
    package_version_changes: list[VersionChange] = Field(default_factory=list)
    likely_renamed: list[RenameGuess] = Field(default_factory=list)
    unnormalized_identities: int = Field(default=0, ge=0)
    summary: DiffSummary

    @property
    def is_empty(self) -> bool:
        """True when the change altered no structure at all."""
        return (
            not self.nodes.added
            and not self.nodes.removed
            and not self.nodes.moved
            and not self.edges.added
            and not self.edges.removed
        )
