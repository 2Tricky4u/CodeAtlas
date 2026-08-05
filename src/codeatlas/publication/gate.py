"""The approval gate — the only door to the outside world.

Every check is re-evaluated at publish time against the database and the
environment, never inherited from whatever control flow led here. A caller that
reaches `publish_approved` by any path still has to satisfy all of them:

1. the approval exists and its recorded decision is `approved`;
2. publication is enabled in configuration;
3. the kill switch is not set;
4. the approved payload contains no secrets;
5. this approval has not already been published (posting is exactly-once).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from codeatlas.artifacts.store import ArtifactStore
from codeatlas.core.logging import get_logger
from codeatlas.db.tables import ApprovalRow, PublicationRow, RunRow
from codeatlas.publication.payload import ReviewPayload, scan_payload

log = get_logger("codeatlas.publication")

KILL_SWITCH_ENV = "CODEATLAS_KILL_SWITCH"


class PublicationBlocked(RuntimeError):
    """Publication was refused. The reason is always specific and recorded."""


# The gate returns immutable snapshots rather than ORM rows: callers routinely
# outlive the session, and a detached row that raises on attribute access is a
# poor API for something whose whole job is to report what happened.
@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    id: int
    run_id: str
    action_kind: str
    payload_sha256: str
    decision: str | None


@dataclass(frozen=True, slots=True)
class PublicationRecord:
    id: int
    approval_id: int
    run_id: str
    target_kind: str
    status: str
    external_ref: str | None
    payload_sha256: str


def _approval_record(row: ApprovalRow) -> ApprovalRecord:
    return ApprovalRecord(
        id=row.id,
        run_id=row.run_id,
        action_kind=row.action_kind,
        payload_sha256=row.payload_sha256,
        decision=row.decision,
    )


def _publication_record(row: PublicationRow) -> PublicationRecord:
    return PublicationRecord(
        id=row.id,
        approval_id=row.approval_id,
        run_id=row.run_id,
        target_kind=row.target_kind,
        status=row.status,
        external_ref=row.external_ref,
        payload_sha256=row.payload_sha256,
    )


class ReviewPublisher(Protocol):
    def create_review(self, payload: ReviewPayload) -> str: ...


def request_approval(
    session: Session, run_id: str, payload: ReviewPayload, cas: ArtifactStore
) -> ApprovalRecord:
    """Store the exact payload and open an approval for it."""
    payload_sha = cas.put_json(payload.contract_dump())
    from codeatlas.db.repositories import index_artifact

    index_artifact(
        session,
        sha256=payload_sha,
        kind="review-payload",
        media_type="application/json",
        size_bytes=len(json.dumps(payload.contract_dump())),
        producer="pipeline",
        produced_by_run_id=run_id,
        schema_id="review-payload.v1",
    )
    approval = ApprovalRow(
        run_id=run_id,
        action_kind="publish_pr_review",
        payload_sha256=payload_sha,
    )
    session.add(approval)
    run = session.get(RunRow, run_id)
    if run is not None:
        run.status = "paused_for_approval"
    session.flush()
    log.info(
        "approval.requested",
        run_id=run_id,
        approval_id=approval.id,
        payload=payload_sha,
        comments=len(payload.comments),
    )
    return _approval_record(approval)


def decide_approval(
    session: Session,
    approval_id: int,
    decision: str,
    decided_by: str,
    note: str | None = None,
) -> ApprovalRecord:
    if decision not in ("approved", "rejected"):
        raise ValueError(f"decision must be approved or rejected, got {decision!r}")
    approval = session.get(ApprovalRow, approval_id)
    if approval is None:
        raise ValueError(f"unknown approval {approval_id}")
    if approval.decision is not None:
        raise ValueError(f"approval {approval_id} already decided: {approval.decision}")
    approval.decision = decision
    approval.decided_by = decided_by
    approval.decision_note = note
    approval.decided_at = datetime.now(UTC)
    session.flush()
    log.info("approval.decided", approval_id=approval_id, decision=decision, by=decided_by)
    return _approval_record(approval)


def publish_approved(
    session: Session,
    approval_id: int,
    github: ReviewPublisher,
    cas: ArtifactStore,
    enabled: bool,
    env: dict[str, str] | None = None,
) -> PublicationRecord:
    environ = env if env is not None else dict(os.environ)

    approval = session.get(ApprovalRow, approval_id)
    if approval is None:
        raise PublicationBlocked(f"unknown approval {approval_id}")

    # Exactly-once: an approval that already produced a publication never posts again.
    existing = session.scalar(
        select(PublicationRow).where(
            PublicationRow.approval_id == approval_id, PublicationRow.status == "published"
        )
    )
    if existing is not None:
        log.info(
            "publication.already_published", approval_id=approval_id, ref=existing.external_ref
        )
        return _publication_record(existing)

    if approval.decision != "approved":
        raise PublicationBlocked(
            f"approval {approval_id} is not approved (decision={approval.decision or 'pending'})"
        )
    if not enabled:
        raise PublicationBlocked("publication is disabled in configuration")
    if environ.get(KILL_SWITCH_ENV):
        raise PublicationBlocked(f"kill switch is engaged ({KILL_SWITCH_ENV} is set)")

    payload = ReviewPayload.model_validate(json.loads(cas.get(approval.payload_sha256)))
    secrets = scan_payload(payload)
    if secrets:
        log.error("publication.secret_detected", approval_id=approval_id, patterns=secrets)
        raise PublicationBlocked(
            f"approved payload contains what looks like a secret ({', '.join(secrets)})"
        )

    publication = PublicationRow(
        approval_id=approval_id,
        run_id=approval.run_id,
        target_kind="github_pr_review",
        payload_sha256=approval.payload_sha256,
        status="pending",
    )
    session.add(publication)
    session.flush()

    try:
        external_ref = github.create_review(payload)
    except Exception as exc:
        publication.status = "failed"
        # Committed, not just flushed: the caller is about to see an exception, and
        # a rolled-back failure record would erase the evidence that we attempted a
        # publication at all. An outward-facing attempt must always leave a trace.
        session.commit()
        log.error("publication.failed", approval_id=approval_id, error=str(exc))
        raise PublicationBlocked(f"github rejected the review: {exc}") from exc

    publication.external_ref = external_ref
    publication.status = "published"
    publication.published_at = datetime.now(UTC)
    run = session.get(RunRow, approval.run_id)
    if run is not None and run.status == "paused_for_approval":
        run.status = "succeeded"
    session.flush()
    log.info("publication.published", approval_id=approval_id, ref=external_ref)
    return _publication_record(publication)
