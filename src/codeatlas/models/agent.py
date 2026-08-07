"""Contract models for the agent adapter boundary (agent-task/agent-result v1)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from codeatlas.models.base import ContractModel
from codeatlas.models.graph import GIT_SHA_PATTERN
from codeatlas.models.receipts import SHA256_PATTERN

ULID_PATTERN = r"^[0-9A-HJKMNP-TV-Z]{26}$"

AgentResultStatus = Literal["succeeded", "failed", "timeout", "schema_invalid", "budget_exceeded"]


class WorkspaceSpec(ContractModel):
    checkout_path: str = Field(min_length=1)
    mount_mode: Literal["ro"] = "ro"


class PermissionSet(ContractModel):
    allowed_commands: list[str]
    network: Literal[False] = False
    write_paths: list[str]


class TaskLimits(ContractModel):
    timeout_s: int = Field(ge=1)
    max_tokens: int = Field(ge=1)
    max_iterations: int = Field(ge=1)


class AgentTask(ContractModel):
    task_id: str = Field(pattern=ULID_PATTERN)
    run_id: str = Field(pattern=ULID_PATTERN)
    skill_id: str = Field(min_length=1)
    skill_version: str = Field(min_length=1)
    skill_content_sha256: str = Field(pattern=SHA256_PATTERN)
    revision_sha: str = Field(pattern=GIT_SHA_PATTERN)
    workspace: WorkspaceSpec
    inputs: dict[str, str]
    permissions: PermissionSet
    output_schema_id: str = Field(min_length=1)
    limits: TaskLimits


class CommandReceipt(ContractModel):
    command: str = Field(min_length=1)
    exit_code: int
    duration_ms: int = Field(ge=0)


class UsageStats(ContractModel):
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    wall_ms: int = Field(ge=0)
    model_id: str = Field(min_length=1)


class AgentResult(ContractModel):
    task_id: str = Field(pattern=ULID_PATTERN)
    status: AgentResultStatus
    output: dict[str, Any] | None = None
    command_receipts: list[CommandReceipt]
    usage: UsageStats
    permission_denials: list[str] = Field(default_factory=list)
    transcript_ref: str | None = Field(default=None, pattern=SHA256_PATTERN)
    error: str | None = None
    # Files the agent actually opened with the Read tool — measured by the
    # engine from the tool stream, never claimed by the model. None when the
    # engine does not report reads (replay of older recordings).
    files_read: list[str] | None = None
