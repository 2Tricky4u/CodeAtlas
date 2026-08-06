"""Contract models for the normalized project graph (project-graph.v1.json)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from codeatlas.models.base import ContractModel

EvidenceKind = Literal[
    "compiler",
    "language-server",
    "build-system",
    "schema",
    "static-analysis",
    "runtime-trace",
    "test",
    "manual",
    "llm-inference",
]

NodeKind = Literal[
    "repository",
    "package",
    "module",
    "file",
    "type",
    "function",
    "constant",
    "service",
    "endpoint",
    "database",
    "queue",
    "external-system",
    "deployment-unit",
]

EdgeKind = Literal[
    "contains",
    "imports",
    "depends-on",
    "calls",
    "implements",
    "extends",
    "reads",
    "writes",
    "publishes",
    "subscribes",
    "exposes",
    "deploys",
    "authenticates-with",
    "transfers-data-to",
]

DETERMINISTIC_EVIDENCE_KINDS: frozenset[str] = frozenset(
    {"compiler", "language-server", "build-system", "schema", "static-analysis", "test"}
)

GIT_SHA_PATTERN = r"^[0-9a-f]{40}$"


class SourceLocation(ContractModel):
    path: str = Field(min_length=1)
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    symbol: str | None = None


class Evidence(ContractModel):
    kind: EvidenceKind
    producer: str = Field(min_length=1)
    producer_version: str | None = None
    artifact: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class RepositoryRef(ContractModel):
    id: str = Field(min_length=1)
    url: str | None = None


class RevisionRef(ContractModel):
    head: str = Field(pattern=GIT_SHA_PATTERN)
    base: str | None = Field(default=None, pattern=GIT_SHA_PATTERN)


class GraphNode(ContractModel):
    id: str = Field(min_length=1)
    kind: NodeKind
    label: str = Field(min_length=1)
    language: str | None = None
    location: SourceLocation | None = None
    tags: list[str] | None = None
    metrics: dict[str, float | int | str | bool] | None = None
    evidence: list[Evidence] = Field(min_length=1)


class GraphEdge(ContractModel):
    id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    kind: EdgeKind
    configuration: str | None = None
    evidence: list[Evidence] = Field(min_length=1)


class ProjectGraph(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    repository: RepositoryRef
    revision: RevisionRef
    nodes: list[GraphNode]
    edges: list[GraphEdge]
