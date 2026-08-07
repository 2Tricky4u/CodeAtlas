"""Contract models for the run manifest (run-manifest.v1.json)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from codeatlas.models.agent import ULID_PATTERN
from codeatlas.models.base import ContractModel
from codeatlas.models.graph import GIT_SHA_PATTERN
from codeatlas.models.receipts import SHA256_PATTERN

RunKind = Literal["repository", "pr"]


class SourceLock(ContractModel):
    repository_id: str = Field(min_length=1)
    remote_url: str | None = None
    head_sha: str = Field(pattern=GIT_SHA_PATTERN)
    base_sha: str | None = Field(default=None, pattern=GIT_SHA_PATTERN)
    merge_base_sha: str | None = Field(default=None, pattern=GIT_SHA_PATTERN)
    changed_paths: list[str]
    generated_paths: list[str]


class RunCost(ContractModel):
    total_prompt_tokens: int = Field(ge=0)
    total_completion_tokens: int = Field(ge=0)
    total_cost_usd: float | None = Field(default=None, ge=0)


class RunManifest(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    run_id: str = Field(pattern=ULID_PATTERN)
    kind: RunKind
    source_lock: SourceLock
    toolchain: dict[str, str]
    skill_registry_sha256: str = Field(pattern=SHA256_PATTERN)
    config_sha256: str = Field(pattern=SHA256_PATTERN)
    model_ids: list[str]
    cassette_ids: list[str]
    inputs: dict[str, str]
    outputs: dict[str, str]
    cost: RunCost
    # Degradations and skips, in the run's own words. The manifest is the
    # report, and a degraded run says so in its report.
    notes: list[str] = Field(default_factory=list)
