"""Contract models for the intent package (intent.v1.json)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from codeatlas.models.base import ContractModel

RequirementSourceKind = Literal[
    "issue",
    "spec",
    "pr-description",
    "commit",
    "adr",
    "repository-rule",
    "inferred",
    "unavailable",
]


class Requirement(ContractModel):
    id: str = Field(pattern=r"^REQ-[0-9]{3,}$")
    source_kind: RequirementSourceKind
    source_ref: str | None = None
    text: str = Field(min_length=1)
    acceptance_criteria: list[str]


class IntentPackage(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    requirements: list[Requirement]
    non_goals: list[str]
    compatibility_obligations: list[str]
    unresolved_questions: list[str]
