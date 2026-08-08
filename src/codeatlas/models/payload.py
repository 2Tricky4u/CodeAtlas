"""Contract models for the review payload (review-payload.v1.json).

The payload is built once, stored content-addressed, approved as a specific
artifact, and posted verbatim — so what a human approves is byte-for-byte what
goes out. The builder and the gate live in `codeatlas.publication`; these are
only the shapes.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from codeatlas.models.base import ContractModel
from codeatlas.models.graph import GIT_SHA_PATTERN


class ReviewComment(ContractModel):
    path: str = Field(min_length=1)
    # The anchor line on the head revision — always a line the diff added,
    # or GitHub rejects the whole review with a 422.
    line: int = Field(ge=1)
    # Present only when the finding's whole span consists of added lines: the
    # comment then attaches to the range start_line..line.
    start_line: int | None = Field(default=None, ge=1)
    body: str = Field(min_length=1)


class ReviewPayload(ContractModel):
    owner: str = Field(min_length=1)
    repo: str = Field(min_length=1)
    pr_number: int = Field(ge=1)
    commit_sha: str = Field(pattern=GIT_SHA_PATTERN)
    body: str = Field(min_length=1)
    comments: list[ReviewComment]
    event: str = "COMMENT"  # never REQUEST_CHANGES/APPROVE: a human decides that

    def to_github(self) -> dict[str, Any]:
        """The literal GitHub review API request body."""
        comments: list[dict[str, Any]] = []
        for c in self.comments:
            entry: dict[str, Any] = {
                "path": c.path,
                "line": c.line,
                "side": "RIGHT",
                "body": c.body,
            }
            if c.start_line is not None:
                entry["start_line"] = c.start_line
                entry["start_side"] = "RIGHT"
            comments.append(entry)
        return {
            "commit_id": self.commit_sha,
            "body": self.body,
            "event": self.event,
            "comments": comments,
        }
