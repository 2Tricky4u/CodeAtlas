"""Contract models for the project overview (project-overview.v1.json)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from codeatlas.models.base import ContractModel
from codeatlas.models.graph import GIT_SHA_PATTERN


class PackageSummary(ContractModel):
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    manifest_path: str | None = None
    file_count: int = Field(ge=0)
    symbol_count: int = Field(ge=0)


class ModuleSummary(ContractModel):
    key: str = Field(min_length=1)
    path: str = Field(min_length=1)
    package: str | None = None
    fan_in: int = Field(ge=0)
    fan_out: int = Field(ge=0)
    level: int = Field(ge=0)
    symbol_count: int = Field(ge=0)
    # None on artifacts produced before the depth metric existed; the UI
    # omits the interface badge rather than claiming zero public items.
    public_count: int | None = Field(default=None, ge=0)


class LevelSummary(ContractModel):
    level: int = Field(ge=0)
    modules: list[str] = Field(default_factory=list)


class CycleEdge(ContractModel):
    from_: str = Field(min_length=1, alias="from")
    to: str = Field(min_length=1)


class Cycle(ContractModel):
    members: list[str] = Field(min_length=2)
    edges: list[CycleEdge] = Field(default_factory=list)


class Hubs(ContractModel):
    depended_on: list[ModuleSummary] = Field(default_factory=list)
    depends_on: list[ModuleSummary] = Field(default_factory=list)


class Suggestion(ContractModel):
    key: str | None = None
    path: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class OverviewCounts(ContractModel):
    packages: int = Field(ge=0)
    files: int = Field(ge=0)
    symbols: int = Field(ge=0)
    edges: int = Field(ge=0)


class ProjectOverview(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    repository_id: str = Field(min_length=1)
    revision: str = Field(pattern=GIT_SHA_PATTERN)
    packages: list[PackageSummary] = Field(default_factory=list)
    modules: list[ModuleSummary] = Field(default_factory=list)
    levels: list[LevelSummary] = Field(default_factory=list)
    cycles: list[Cycle] = Field(default_factory=list)
    hubs: Hubs = Field(default_factory=Hubs)
    orphans: list[ModuleSummary] = Field(default_factory=list)
    entry_points: list[Suggestion] = Field(default_factory=list)
    start_here: list[Suggestion] = Field(default_factory=list)
    counts: OverviewCounts
    notes: list[str] = Field(default_factory=list)
