"""Dry-run publication: produce the exact payload, post nothing.

Shadow mode is this and only this. The payload written here is byte-identical to
what publication would send, so what is reviewed in shadow mode is what would
have gone out — the difference is solely that no writer is ever constructed.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from codeatlas.artifacts.store import ArtifactStore
from codeatlas.core.canonical import canonical_json
from codeatlas.core.logging import get_logger
from codeatlas.db.repositories import index_artifact
from codeatlas.publication.payload import ReviewPayload, scan_payload
from codeatlas.review.synthesis import ReviewReport, render_markdown

log = get_logger("codeatlas.publication.dry_run")


@dataclass(frozen=True, slots=True)
class DryRunResult:
    payload: ReviewPayload
    payload_sha256: str
    markdown_sha256: str
    secrets_detected: list[str]
    would_comment_on: list[str]

    @property
    def safe(self) -> bool:
        return not self.secrets_detected


def dry_run(
    session: Session,
    run_id: str,
    report: ReviewReport,
    payload: ReviewPayload,
    cas: ArtifactStore,
) -> DryRunResult:
    payload_bytes = canonical_json(payload.contract_dump())
    payload_sha = cas.put(payload_bytes)
    markdown_bytes = render_markdown(report).encode("utf-8")
    markdown_sha = cas.put(markdown_bytes)

    for sha, kind, media, blob, schema_id in (
        (
            payload_sha,
            "review-payload-dry-run",
            "application/json",
            payload_bytes,
            "review-payload.v1",
        ),
        (markdown_sha, "review-markdown", "text/markdown", markdown_bytes, None),
    ):
        index_artifact(
            session,
            sha256=sha,
            kind=kind,
            media_type=media,
            size_bytes=len(blob),
            producer="pipeline",
            produced_by_run_id=run_id,
            schema_id=schema_id,
        )

    secrets = scan_payload(payload)
    if secrets:
        log.error("dry_run.secret_detected", run_id=run_id, patterns=secrets)

    result = DryRunResult(
        payload=payload,
        payload_sha256=payload_sha,
        markdown_sha256=markdown_sha,
        secrets_detected=secrets,
        would_comment_on=[f"{c.path}:{c.line}" for c in payload.comments],
    )
    log.info(
        "dry_run.completed",
        run_id=run_id,
        payload=payload_sha,
        comments=len(payload.comments),
        safe=result.safe,
    )
    return result
