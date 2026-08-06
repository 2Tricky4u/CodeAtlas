"""Contract models for scoped code answers (code-answer.v1.json)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from codeatlas.models.base import ContractModel
from codeatlas.models.explanation import DroppedClaim
from codeatlas.models.project_explanation import ModuleCitation, ProjectSourceCitation

#: The same citation shapes the project narrative uses, minus package and cycle:
#: a scoped answer talks about code, not about the project's topology.
AnswerCitation = Annotated[ProjectSourceCitation | ModuleCitation, Field(discriminator="kind")]


class AnswerClaim(ContractModel):
    text: str = Field(min_length=1)
    citations: list[AnswerCitation] = Field(min_length=1)


class CodeAnswer(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    question: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    #: Absent when refused. The prose summary; the claims are the checkable form.
    answer: str | None = None
    claims: list[AnswerClaim] = Field(default_factory=list)
    #: Why no answer was given: needs code outside this scope, or asks for an
    #: opinion rather than a fact. A first-class outcome, not a failure.
    refused: str | None = None
    dropped_claims: list[DroppedClaim] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
