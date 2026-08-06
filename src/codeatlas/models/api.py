"""Contract models for the public API surface and its change across revisions.

`api-surface.v1.json` is a fact about one revision; `api-change.v1.json` is a
comparison of two. Keeping them apart matters for the same reason a project graph
describes one revision (ADR-0013): a surface is addressable by the revision that
produced it, and a comparison is not a property of either side.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from codeatlas.models.base import ContractModel
from codeatlas.models.graph import GIT_SHA_PATTERN

RequiredBump = Literal["major", "minor", "none", "unknown"]


class SkippedPackage(ContractModel):
    """A package whose API was not measured, and why."""

    name: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class ApiPackage(ContractModel):
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    manifest_path: str = Field(min_length=1)
    items: list[str]


class ApiSurface(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    revision: str = Field(pattern=GIT_SHA_PATTERN)
    tool: str = Field(min_length=1)
    packages: list[ApiPackage]
    skipped: list[SkippedPackage]

    def package(self, name: str) -> ApiPackage | None:
        return next((p for p in self.packages if p.name == name), None)


class SemverLint(ContractModel):
    """One cargo-semver-checks lint that fired, with where it fired."""

    id: str = Field(min_length=1)
    level: Literal["major", "minor"]
    summary: str = Field(min_length=1)
    locations: list[str] = Field(default_factory=list)


class PackageApiDelta(ContractModel):
    name: str = Field(min_length=1)
    added: list[str]
    removed: list[str]
    unchanged_count: int = Field(ge=0)
    required_bump: RequiredBump
    lints: list[SemverLint] = Field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.added and not self.removed


class ApiChange(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    base_revision: str = Field(pattern=GIT_SHA_PATTERN)
    head_revision: str = Field(pattern=GIT_SHA_PATTERN)
    packages: list[PackageApiDelta]
    skipped: list[SkippedPackage]
    tools: dict[str, str]

    @property
    def has_breaking_change(self) -> bool:
        return any(p.required_bump == "major" for p in self.packages)
