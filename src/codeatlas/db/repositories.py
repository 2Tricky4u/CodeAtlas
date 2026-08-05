"""Typed query layer over the relational spine.

All functions take an active Session; transactions are owned by callers.
Contract payloads go in as `contract_dump()` JSONB verbatim.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from codeatlas.core.canonical import canonical_sha256
from codeatlas.core.ids import new_run_id
from codeatlas.db.tables import (
    RUN_STATUSES,
    ArtifactRow,
    ExtractorReceiptRow,
    GraphEdgeRow,
    GraphNodeRow,
    GraphSnapshotRow,
    RepositoryRow,
    RevisionRow,
    RunEventRow,
    RunRow,
)
from codeatlas.models.graph import ProjectGraph
from codeatlas.models.receipts import ExtractorReceipt


def ensure_repository(
    session: Session, repository_id: str, provider: str, remote_url: str | None = None
) -> RepositoryRow:
    row = session.get(RepositoryRow, repository_id)
    if row is None:
        row = RepositoryRow(id=repository_id, provider=provider, remote_url=remote_url)
        session.add(row)
        session.flush()
    return row


def ensure_revision(
    session: Session, repository_id: str, sha: str, ref_name: str | None = None
) -> RevisionRow:
    row = session.scalar(
        select(RevisionRow).where(
            RevisionRow.repository_id == repository_id, RevisionRow.sha == sha
        )
    )
    if row is None:
        row = RevisionRow(repository_id=repository_id, sha=sha, ref_name=ref_name)
        session.add(row)
        session.flush()
    return row


def create_run(
    session: Session,
    repository_id: str,
    kind: str,
    head_revision_id: int,
    base_revision_id: int | None = None,
    pr_number: int | None = None,
) -> RunRow:
    row = RunRow(
        id=new_run_id(),
        repository_id=repository_id,
        kind=kind,
        head_revision_id=head_revision_id,
        base_revision_id=base_revision_id,
        pr_number=pr_number,
        status="created",
    )
    session.add(row)
    session.flush()
    return row


def get_run(session: Session, run_id: str) -> RunRow | None:
    return session.get(RunRow, run_id)


def set_run_status(session: Session, run_id: str, status: str) -> None:
    if status not in RUN_STATUSES:
        raise ValueError(f"unknown run status: {status!r}")
    run = session.get(RunRow, run_id)
    if run is None:
        raise ValueError(f"unknown run: {run_id}")
    run.status = status
    session.flush()


def add_run_event(
    session: Session,
    run_id: str,
    stage: str,
    event: str,
    level: str = "info",
    data: dict[str, Any] | None = None,
) -> None:
    session.add(RunEventRow(run_id=run_id, stage=stage, event=event, level=level, data=data))
    session.flush()


def record_receipt(session: Session, run_id: str, receipt: ExtractorReceipt) -> None:
    session.add(
        ExtractorReceiptRow(
            run_id=run_id,
            extractor=receipt.extractor,
            extractor_version=receipt.extractor_version,
            revision_sha=receipt.revision,
            exit_code=receipt.exit_code,
            payload=receipt.contract_dump(),
        )
    )
    session.flush()


def index_artifact(
    session: Session,
    sha256: str,
    kind: str,
    media_type: str,
    size_bytes: int,
    producer: str,
    produced_by_run_id: str | None = None,
    schema_id: str | None = None,
) -> ArtifactRow:
    row = session.get(ArtifactRow, sha256)
    if row is None:
        row = ArtifactRow(
            sha256=sha256,
            kind=kind,
            media_type=media_type,
            size_bytes=size_bytes,
            producer=producer,
            produced_by_run_id=produced_by_run_id,
            schema_id=schema_id,
        )
        session.add(row)
        session.flush()
    return row


def store_graph_snapshot(
    session: Session,
    run_id: str,
    revision_id: int,
    graph: ProjectGraph,
    artifact_sha256: str,
) -> GraphSnapshotRow:
    """Project a canonical graph into relational rows (JSON stays the truth)."""
    dump = graph.contract_dump()
    snapshot = GraphSnapshotRow(
        run_id=run_id,
        revision_id=revision_id,
        schema_version=graph.schema_version,
        canonical_sha256=canonical_sha256(dump),
        artifact_sha256=artifact_sha256,
        node_count=len(graph.nodes),
        edge_count=len(graph.edges),
    )
    session.add(snapshot)
    session.flush()

    for node in graph.nodes:
        session.add(
            GraphNodeRow(
                snapshot_id=snapshot.id,
                natural_id=node.id,
                kind=node.kind,
                label=node.label,
                path=node.location.path if node.location else None,
                start_line=node.location.start_line if node.location else None,
                end_line=node.location.end_line if node.location else None,
                attrs=node.contract_dump(),
            )
        )
    for edge in graph.edges:
        session.add(
            GraphEdgeRow(
                snapshot_id=snapshot.id,
                natural_id=edge.id,
                source_natural_id=edge.source,
                target_natural_id=edge.target,
                kind=edge.kind,
                configuration=edge.configuration,
                attrs=edge.contract_dump(),
            )
        )
    session.flush()
    return snapshot


def load_graph_snapshot(session: Session, snapshot_id: int) -> GraphSnapshotRow | None:
    return session.get(GraphSnapshotRow, snapshot_id)
