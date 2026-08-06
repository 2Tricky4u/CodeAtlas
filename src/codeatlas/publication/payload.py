"""The exact payload that would be posted, and the checks it must survive.

The payload is built once, stored content-addressed, approved as a specific
artifact, and posted verbatim — so what a human approves is byte-for-byte what
goes out. Nothing is regenerated between approval and publication.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import Field

from codeatlas.models.base import ContractModel
from codeatlas.models.graph import GIT_SHA_PATTERN
from codeatlas.review.synthesis import ReviewReport, render_markdown

# Secret shapes that must never leave the machine inside a review comment. Kept
# in step with .gitleaks.toml; the review path is a second, independent gate
# because review text quotes source code.
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("github-fine-grained-pat", re.compile(r"github_pat_[0-9A-Za-z_]{20,}")),
    ("github-classic-pat", re.compile(r"gh[pousr]_[0-9A-Za-z]{20,}")),
    ("anthropic-api-key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("postgres-url-password", re.compile(r"postgres(?:ql)?://[^:\s]+:[^@\s]{6,}@")),
    ("aws-access-key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private-key-block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
)


class ReviewComment(ContractModel):
    path: str = Field(min_length=1)
    line: int = Field(ge=1)
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
        return {
            "commit_id": self.commit_sha,
            "body": self.body,
            "event": self.event,
            "comments": [
                {"path": c.path, "line": c.line, "side": "RIGHT", "body": c.body}
                for c in self.comments
            ],
        }


def scan_for_secrets(text: str) -> list[str]:
    """Names of secret patterns found in `text` (empty means clean)."""
    return sorted({name for name, pattern in _SECRET_PATTERNS if pattern.search(text)})


def scan_payload(payload: ReviewPayload) -> list[str]:
    findings = set(scan_for_secrets(payload.body))
    for comment in payload.comments:
        findings.update(scan_for_secrets(comment.body))
    return sorted(findings)


def build_payload(
    report: ReviewReport,
    owner: str,
    repo: str,
    pr_number: int,
    commit_sha: str,
    changed_paths: set[str] | None = None,
    explanation_markdown: str | None = None,
) -> ReviewPayload:
    """Render a report into a PR review payload.

    Inline comments are only produced for findings inside changed files — GitHub
    rejects comments outside the diff, and commenting on untouched code in a PR
    is noise regardless. Everything else stays in the summary body.

    The change explanation leads the body when there is one: a reviewer needs to
    know what the change does before being told what might be wrong with it.
    """
    comments: list[ReviewComment] = []
    for entry in report.publishable:
        location = entry.validation.location
        if changed_paths is not None and location.path not in changed_paths:
            continue
        if location.start_line is None:
            continue
        comments.append(
            ReviewComment(
                path=location.path,
                line=location.start_line,
                body=_comment_body(entry),
            )
        )

    body = render_markdown(report)
    if explanation_markdown:
        body = f"## What this change does\n\n{explanation_markdown}\n\n---\n\n{body}"

    return ReviewPayload(
        owner=owner,
        repo=repo,
        pr_number=pr_number,
        commit_sha=commit_sha,
        body=body,
        comments=comments,
    )


def _comment_body(entry: Any) -> str:
    validation = entry.validation
    lines = [
        f"**{validation.severity.upper()} · {entry.finding.category}** (`{entry.finding_id}`)",
        "",
        validation.claim,
        "",
        "Evidence: "
        + "; ".join(
            f"{e.kind}"
            + (f" `{e.command}`" if e.command else "")
            + (f" (exit {e.exit_code})" if e.exit_code is not None else "")
            for e in validation.evidence
        ),
    ]
    return "\n".join(lines)
