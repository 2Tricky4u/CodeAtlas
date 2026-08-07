"""Contract models for the change explanation (change-explanation.v1.json)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from codeatlas.models.base import ContractModel

SectionId = Literal["before", "after", "structural", "impact", "risks"]


class SourceCitation(ContractModel):
    kind: Literal["source"] = "source"
    revision: Literal["base", "head"]
    path: str = Field(min_length=1)
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)


class EdgeCitation(ContractModel):
    kind: Literal["graph-edge"] = "graph-edge"
    edge_id: str = Field(min_length=1)


class ApiCitation(ContractModel):
    kind: Literal["api-item"] = "api-item"
    item: str = Field(min_length=1)


class ImpactCitation(ContractModel):
    kind: Literal["impact"] = "impact"
    stable_key: str = Field(min_length=1)


Citation = Annotated[
    SourceCitation | EdgeCitation | ApiCitation | ImpactCitation,
    Field(discriminator="kind"),
]


class Claim(ContractModel):
    text: str = Field(min_length=1)
    citations: list[Citation] = Field(min_length=1)


class ExplanationSection(ContractModel):
    id: SectionId
    title: str = Field(min_length=1)
    claims: list[Claim] = Field(default_factory=list)


class DroppedClaim(ContractModel):
    section_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class ChangeExplanation(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    summary: str = Field(min_length=1)
    sections: list[ExplanationSection] = Field(default_factory=list)
    sequence_diagram: str | None = None
    dropped_claims: list[DroppedClaim] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @property
    def claim_count(self) -> int:
        return sum(len(section.claims) for section in self.sections)
