"""Contract models for bounded graph views (graph-view.v1.json)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from codeatlas.models.base import ContractModel
from codeatlas.models.graph import GIT_SHA_PATTERN

ViewKind = Literal["package-dependencies", "levelized-modules", "matrix", "neighborhood"]
LayoutFamily = Literal["elk-layered", "fcose", "none"]
CheckName = Literal["node-budget", "edge-density", "max-degree"]


class ViewNode(ContractModel):
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    parent: str | None = None
    level: int | None = Field(default=None, ge=0)
    path: str | None = None
    fan_in: int | None = Field(default=None, ge=0)
    fan_out: int | None = Field(default=None, ge=0)
    in_cycle: bool = False


class ViewEdge(ContractModel):
    id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    weight: int | None = Field(default=None, ge=1)
    violates_levels: bool = False


class ReadabilityCheck(ContractModel):
    name: CheckName
    passed: bool
    value: float
    limit: float


class Readability(ContractModel):
    passed: bool
    checks: list[ReadabilityCheck] = Field(default_factory=list)

    @property
    def first_failure(self) -> ReadabilityCheck | None:
        return next((c for c in self.checks if not c.passed), None)


class GraphViewRefusal(ContractModel):
    id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    failed_check: CheckName
    reason: str = Field(min_length=1)


class GraphView(ContractModel):
    id: str = Field(min_length=1)
    kind: ViewKind
    title: str = Field(min_length=1)
    scope: str | None = None
    layout: LayoutFamily
    nodes: list[ViewNode] = Field(default_factory=list)
    edges: list[ViewEdge] = Field(default_factory=list)
    suppressed_edges: int = Field(default=0, ge=0)
    readability: Readability
    notes: list[str] = Field(default_factory=list)


class GraphViews(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    repository_id: str = Field(min_length=1)
    revision: str = Field(pattern=GIT_SHA_PATTERN)
    views: list[GraphView] = Field(default_factory=list)
    refused: list[GraphViewRefusal] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
