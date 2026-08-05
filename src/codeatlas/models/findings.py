"""Contract models for candidate findings (finding.v1.json)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from codeatlas.models.base import ContractModel
from codeatlas.models.graph import Evidence, SourceLocation

FindingCategory = Literal["correctness", "security", "architecture", "spec", "standards"]
Severity = Literal["critical", "high", "medium", "low", "info"]

FINDING_ID_PATTERN = r"^F-[0-9]{4}$"


class Finding(ContractModel):
    finding_id: str = Field(pattern=FINDING_ID_PATTERN)
    category: FindingCategory
    discovered_by_skill: str = Field(min_length=1)
    skill_version: str = Field(min_length=1)
    severity: Severity
    confidence: float = Field(ge=0, le=1)
    claim: str = Field(min_length=1)
    location: SourceLocation
    requirement_ids: list[str] | None = None
    evidence: list[Evidence] = Field(min_length=1)
    proposed_reproduction: str | None = None
