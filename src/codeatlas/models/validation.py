"""Contract models for validation results (validation-result.v1.json)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from codeatlas.models.base import ContractModel
from codeatlas.models.findings import FINDING_ID_PATTERN, Severity
from codeatlas.models.graph import SourceLocation

ValidationStatus = Literal["validated", "rejected", "duplicate", "unresolved"]

ValidationEvidenceKind = Literal[
    "test",
    "command",
    "call-path",
    "static-analysis",
    "compiler",
    "schema",
    "repository-rule",
    "independent-review",
]


class ValidationEvidence(ContractModel):
    kind: ValidationEvidenceKind
    command: str | None = None
    exit_code: int | None = None
    artifact: str | None = None


class ValidationResult(ContractModel):
    finding_id: str = Field(pattern=FINDING_ID_PATTERN)
    status: ValidationStatus
    severity: Severity
    confidence: float = Field(ge=0, le=1)
    introduced_by_change: bool
    duplicate_of: str | None = Field(default=None, pattern=FINDING_ID_PATTERN)
    location: SourceLocation
    claim: str = Field(min_length=1)
    evidence: list[ValidationEvidence]
    counter_evidence_checked: list[str] = Field(min_length=1)
    publication_eligible: bool
    reason: str | None = None
