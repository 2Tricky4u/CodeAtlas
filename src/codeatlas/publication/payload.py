"""The exact payload that would be posted, and the checks it must survive.

The payload is built once, stored content-addressed, approved as a specific
artifact, and posted verbatim — so what a human approves is byte-for-byte what
goes out. Nothing is regenerated between approval and publication.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from codeatlas.models.payload import ReviewComment, ReviewPayload
from codeatlas.review.synthesis import ReviewReport, render_markdown

__all__ = [
    "PROVENANCE",
    "ReviewComment",
    "ReviewPayload",
    "build_payload",
    "scan_for_secrets",
    "scan_payload",
]

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


# Every outward-facing byte names its author. Added here so the human approves
# text that already carries it; verified again in `gate.publish_approved` so no
# control flow can post without it (mutating at post time would post something
# nobody approved — the gate checks, never edits).
PROVENANCE = "_Posted by CodeAtlas — an automated, human-approved review._"


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
    added_lines: Mapping[str, set[int]] | None = None,
    existing: list[dict[str, Any]] | None = None,
) -> ReviewPayload:
    """Render a report into a PR review payload.

    Inline comments are only produced for findings whose span touches lines the
    diff actually added — GitHub rejects comments outside the diff with a 422
    that voids the whole review. A publishable finding on an unchanged line of
    a changed file is not dropped: it folds into the summary body under its own
    heading, with a full-SHA permalink, so the honest fallback is visible text
    rather than a doomed API call. Without diff information (`added_lines`
    None) the file-level filter governs alone, as it always did.

    The change explanation leads the body when there is one: a reviewer needs to
    know what the change does before being told what might be wrong with it.
    """
    # Comments we posted on an earlier run, recognizable by the provenance
    # marker: same path + line → the finding folds into a note, not a repost.
    ours_already = {
        (str(c.get("path", "")), c.get("line"))
        for c in (existing or [])
        if PROVENANCE in str(c.get("body", ""))
    }

    comments: list[ReviewComment] = []
    outside_diff: list[str] = []
    previously_posted: list[str] = []
    for entry in report.publishable:
        location = entry.validation.location
        if changed_paths is not None and location.path not in changed_paths:
            continue
        if location.start_line is None:
            continue
        start = location.start_line
        end = location.end_line or start
        if added_lines is not None:
            added = added_lines.get(location.path, set())
            span = set(range(start, end + 1))
            hit = sorted(span & added)
            if not hit:
                outside_diff.append(
                    f"- `{entry.finding_id}` **{entry.validation.severity.upper()}** · "
                    f"{entry.validation.claim[:160]} — "
                    f"{_permalink(owner, repo, commit_sha, location.path, start, end)}"
                )
                continue
            # Anchor on added lines only. The full span becomes a range when
            # every line of it was added; otherwise the first added line is
            # the anchor and the permalink in the body carries the rest.
            anchor_start = hit[0] if span <= added else None
            anchor_line = hit[-1] if span <= added else hit[0]
            if (location.path, anchor_line) in ours_already:
                previously_posted.append(
                    f"- `{entry.finding_id}` at `{location.path}:{anchor_line}` — "
                    "already posted by an earlier run"
                )
                continue
            comments.append(
                ReviewComment(
                    path=location.path,
                    line=anchor_line,
                    start_line=anchor_start if anchor_start != anchor_line else None,
                    body=_comment_body(entry, owner, repo, commit_sha),
                )
            )
        else:
            if (location.path, start) in ours_already:
                previously_posted.append(
                    f"- `{entry.finding_id}` at `{location.path}:{start}` — "
                    "already posted by an earlier run"
                )
                continue
            comments.append(
                ReviewComment(
                    path=location.path,
                    line=start,
                    body=_comment_body(entry, owner, repo, commit_sha),
                )
            )

    body = render_markdown(report)
    if previously_posted:
        body += (
            "\n### Previously posted\n\n"
            "These findings already carry our comment at the same location on "
            "this pull request; they are not posted twice.\n\n"
            + "\n".join(previously_posted)
            + "\n"
        )
    if outside_diff:
        body += (
            "\n### Findings outside the diff\n\n"
            "Validated on the head revision, but not on lines this change added — "
            "posted here because an inline comment outside the diff is rejected.\n\n"
            + "\n".join(outside_diff)
            + "\n"
        )
    if explanation_markdown:
        body = f"## What this change does\n\n{explanation_markdown}\n\n---\n\n{body}"
    body = f"{body.rstrip()}\n\n{PROVENANCE}"

    return ReviewPayload(
        owner=owner,
        repo=repo,
        pr_number=pr_number,
        commit_sha=commit_sha,
        body=body,
        comments=comments,
    )


def _permalink(owner: str, repo: str, sha: str, path: str, start: int, end: int) -> str:
    """A full-SHA blob URL — stable forever, renders as a code preview on GitHub."""
    suffix = f"#L{start}-L{end}" if end != start else f"#L{start}"
    return f"https://github.com/{owner}/{repo}/blob/{sha}/{path}{suffix}"


def _comment_body(entry: Any, owner: str, repo: str, commit_sha: str) -> str:
    validation = entry.validation
    location = validation.location
    start = location.start_line or 1
    end = location.end_line or start
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
        "",
        _permalink(owner, repo, commit_sha, location.path, start, end),
        "",
        PROVENANCE,
    ]
    return "\n".join(lines)
