"""Shadow mode: analyze a real pull request, publish nothing.

The point of shadow mode is to measure what the system *would have said* on real
changes before anyone trusts it to say anything. It therefore runs the identical
report and payload path and stops one step short: no writer is constructed, so
there is no code path from here to GitHub even if configuration were wrong.

What it produces is the same content-addressed payload publication would send,
plus the scope breakdown a reviewer needs to judge whether the blocking rules
behaved sensibly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from codeatlas.artifacts.store import ArtifactStore
from codeatlas.core.logging import get_logger
from codeatlas.models.findings import Finding
from codeatlas.publication.dry_run import DryRunResult, dry_run
from codeatlas.publication.payload import build_payload
from codeatlas.review.scope import ChangedScope, classify_scope, is_blocking
from codeatlas.review.synthesis import ReviewReport

log = get_logger("codeatlas.publication.shadow")


@dataclass(frozen=True, slots=True)
class ShadowResult:
    dry_run: DryRunResult
    blocking_ids: list[str]
    non_blocking_ids: list[str]
    scope_counts: dict[str, int] = field(default_factory=dict)

    @property
    def would_block(self) -> bool:
        return bool(self.blocking_ids)


def run_shadow(
    session: Session,
    run_id: str,
    report: ReviewReport,
    findings: list[Finding],
    scope: ChangedScope | None,
    cas: ArtifactStore,
    owner: str,
    repo: str,
    pr_number: int,
    commit_sha: str,
    explanation_markdown: str | None = None,
) -> ShadowResult:
    by_id = {f.finding_id: f for f in findings}
    blocking: list[str] = []
    non_blocking: list[str] = []
    scope_counts: dict[str, int] = {}

    for entry in report.publishable:
        finding = by_id.get(entry.finding_id)
        if finding is None:
            continue
        scope_class = classify_scope(finding, scope)
        scope_counts[scope_class] = scope_counts.get(scope_class, 0) + 1
        if is_blocking(finding, scope):
            blocking.append(entry.finding_id)
        else:
            non_blocking.append(entry.finding_id)

    payload = build_payload(
        report,
        owner=owner,
        repo=repo,
        pr_number=pr_number,
        commit_sha=commit_sha,
        changed_paths=scope.changed_paths if scope else None,
        explanation_markdown=explanation_markdown,
    )
    result = dry_run(session, run_id=run_id, report=report, payload=payload, cas=cas)

    log.info(
        "shadow.completed",
        run_id=run_id,
        pr=f"{owner}/{repo}#{pr_number}",
        blocking=len(blocking),
        non_blocking=len(non_blocking),
        scope=scope_counts,
        payload=result.payload_sha256,
        published=False,
    )
    return ShadowResult(
        dry_run=result,
        blocking_ids=sorted(blocking),
        non_blocking_ids=sorted(non_blocking),
        scope_counts=scope_counts,
    )
