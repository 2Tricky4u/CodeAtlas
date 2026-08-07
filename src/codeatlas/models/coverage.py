"""Contract models for review coverage (review-coverage.v1.json).

Coverage is measured, never claimed: the engine watches the Read-tool stream
and the pipeline diffs it against the source paths every reviewer was offered.
A reviewer whose engine reported nothing carries measured=False with empty
lists — unknown is a third state, distinct from both read and unread.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from codeatlas.models.base import ContractModel

GIT_SHA_PATTERN = r"^[0-9a-f]{40}$"


class ReviewerCoverage(ContractModel):
    skill_id: str = Field(min_length=1)
    measured: bool
    files_read: list[str] = Field(default_factory=list)
    not_read: list[str] = Field(default_factory=list)


class ReviewCoverage(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    revision: str = Field(pattern=GIT_SHA_PATTERN)
    source_path_count: int = Field(ge=0)
    reviewers: list[ReviewerCoverage]
