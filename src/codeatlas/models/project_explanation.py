"""Contract models for the project explanation (project-explanation.v1.json)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from codeatlas.models.base import ContractModel

# One shape for a removed claim across both explanations: a reader who has
# learned to read `droppedClaims` in a change report reads it the same way here.
from codeatlas.models.explanation import DroppedClaim

ProjectSectionId = Literal["what", "structure", "entry", "hotspots", "caution"]

PROJECT_SECTION_TITLES: dict[str, str] = {
    "what": "What this project is",
    "structure": "How it is organised",
    "entry": "Where to start reading",
    "hotspots": "What everything leans on",
    "caution": "What will surprise you",
}


class ProjectSourceCitation(ContractModel):
    """A file at the revision the overview describes.

    There is no `revision` field, unlike the change explanation's source
    citation: a project graph describes exactly one revision (ADR-0013), so
    there is no other side to point at.
    """

    kind: Literal["source"] = "source"
    path: str = Field(min_length=1)
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)


class ModuleCitation(ContractModel):
    kind: Literal["module"] = "module"
    key: str = Field(min_length=1)


class PackageCitation(ContractModel):
    kind: Literal["package"] = "package"
    name: str = Field(min_length=1)


class CycleCitation(ContractModel):
    """A dependency cycle, named by its exact member set.

    Naming the members rather than an index is what makes this checkable: the
    set has to match one the deterministic pass found, so "there are some
    circular dependencies" cannot be written without saying which.
    """

    kind: Literal["cycle"] = "cycle"
    members: list[str] = Field(min_length=2)


ProjectCitation = Annotated[
    ProjectSourceCitation | ModuleCitation | PackageCitation | CycleCitation,
    Field(discriminator="kind"),
]


class ProjectClaim(ContractModel):
    text: str = Field(min_length=1)
    citations: list[ProjectCitation] = Field(min_length=1)


class ProjectSection(ContractModel):
    id: ProjectSectionId
    title: str = Field(min_length=1)
    claims: list[ProjectClaim] = Field(default_factory=list)


class ProjectExplanation(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    summary: str = Field(min_length=1)
    sections: list[ProjectSection] = Field(default_factory=list)
    dropped_claims: list[DroppedClaim] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @property
    def claim_count(self) -> int:
        return sum(len(section.claims) for section in self.sections)


__all__ = [
    "PROJECT_SECTION_TITLES",
    "CycleCitation",
    "DroppedClaim",
    "ModuleCitation",
    "PackageCitation",
    "ProjectCitation",
    "ProjectClaim",
    "ProjectExplanation",
    "ProjectSection",
    "ProjectSectionId",
    "ProjectSourceCitation",
]
