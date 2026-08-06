"""Contract models for the ADR conformance audit (adr-audit.v1.json)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from codeatlas.models.base import ContractModel
from codeatlas.models.graph import GIT_SHA_PATTERN

AuditResult = Literal["conformant", "probable-drift", "unverifiable", "intentionally-superseded"]


class AuditedDecision(ContractModel):
    adr: str = Field(min_length=1)
    label: str = Field(min_length=1)
    number: int | None = Field(default=None, ge=0)
    title: str | None = None
    status: str = Field(min_length=1)
    #: As written in the ADR. Carried so the set reads in the order the
    #: decisions were taken rather than in whatever order the directory listed.
    date: str | None = None
    superseded_by: str | None = None
    assertion: str = Field(min_length=1)
    audit_result: AuditResult
    confidence: float = Field(ge=0, le=1)
    #: The audit proposes; it never supersedes. This is how it says so.
    requires_human_decision: bool
    affected_nodes: list[str] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    detail: str = ""


class AdrAudit(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    revision: str = Field(pattern=GIT_SHA_PATTERN)
    decisions: list[AuditedDecision] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
