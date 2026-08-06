"""Contract models for bounded change impact (change-impact.v1.json)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from codeatlas.models.base import ContractModel
from codeatlas.models.graph import GIT_SHA_PATTERN

SeedReason = Literal["touched", "removed"]
ImpactRank = Literal["public-api", "crate-crossing", "internal", "test-only"]
ClaimStrength = Literal["referred-to-removed-symbol", "could-be-affected"]

# Ranks in the order a reader should meet them.
RANK_ORDER: dict[str, int] = {
    "public-api": 0,
    "crate-crossing": 1,
    "internal": 2,
    "test-only": 3,
}


class ImpactSeed(ContractModel):
    stable_key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    path: str | None = None
    reason: SeedReason


class ImpactedSymbol(ContractModel):
    stable_key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    path: str | None = None
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    hop: int = Field(ge=1)
    rank: ImpactRank
    claim_strength: ClaimStrength
    via_seed: str = Field(min_length=1)
    via_edge_kind: str | None = None


class ChangeImpact(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    base_revision: str = Field(pattern=GIT_SHA_PATTERN)
    head_revision: str = Field(pattern=GIT_SHA_PATTERN)
    hops: int = Field(ge=1)
    max_hops: int = Field(ge=1)
    seeds: list[ImpactSeed] = Field(default_factory=list)
    impacted: list[ImpactedSymbol] = Field(default_factory=list)
    total_impacted: int = Field(default=0, ge=0)
    suppressed: int = Field(default=0, ge=0)
    basis: str = Field(min_length=1)
    caveat: str = Field(min_length=1)
    notes: list[str] = Field(default_factory=list)
