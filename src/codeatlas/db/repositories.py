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
    RunArtifactRow,
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
    role: str | None = None,
) -> ArtifactRow:
    """Index an artifact and, when a run is given, record that run's membership.

    The artifact row is shared across runs that produce identical content; the
    membership row is per run. Asking "which artifacts does this run have?" must
    go through `run_artifact`, never through `produced_by_run_id`.

    `role` defaults to `kind` and exists for the case where one run holds two
    artifacts of the same kind — a pull-request run has a project graph for the
    head and another for the base, and "the run's project graph" has to mean one
    of them, chosen deliberately.
    """
    membership_role = role or kind
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

    if produced_by_run_id is not None:
        existing = session.scalar(
            select(RunArtifactRow).where(
                RunArtifactRow.run_id == produced_by_run_id,
                RunArtifactRow.sha256 == sha256,
                RunArtifactRow.role == membership_role,
            )
        )
        if existing is None:
            session.add(
                RunArtifactRow(run_id=produced_by_run_id, sha256=sha256, role=membership_role)
            )
            session.flush()
    return row


def artifact_for_run(session: Session, run_id: str, role: str) -> str | None:
    """The sha256 of this run's artifact with the given role, if any."""
    return session.scalar(
        select(RunArtifactRow.sha256)
        .where(RunArtifactRow.run_id == run_id, RunArtifactRow.role == role)
        .order_by(RunArtifactRow.id.desc())
    )


def store_graph_snapshot(
    session: Session,
    run_id: str,
    revision_id: int,
    graph: ProjectGraph,
    artifact_sha256: str,
    role: str = "head",
) -> GraphSnapshotRow:
    """Project a canonical graph into relational rows (JSON stays the truth).

    Re-entrant: a resumed run may reach this stage a second time, and a snapshot
    that already records the identical graph needs nothing done to it. A snapshot
    recording a *different* graph for the same (run, role) is a contradiction —
    the same run cannot have analyzed one revision two ways — so it is raised
    rather than overwritten.
    """
    dump = graph.contract_dump()
    canonical = canonical_sha256(dump)
    existing = session.scalar(
        select(GraphSnapshotRow).where(
            GraphSnapshotRow.run_id == run_id, GraphSnapshotRow.role == role
        )
    )
    if existing is not None:
        if existing.canonical_sha256 != canonical:
            raise ValueError(
                f"run {run_id} already has a different {role} graph "
                f"({existing.canonical_sha256} != {canonical})"
            )
        return existing

    snapshot = GraphSnapshotRow(
        run_id=run_id,
        role=role,
        revision_id=revision_id,
        schema_version=graph.schema_version,
        canonical_sha256=canonical,
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


def graph_snapshot_for_run(
    session: Session, run_id: str, role: str = "head"
) -> GraphSnapshotRow | None:
    """This run's snapshot for one revision role.

    Always name the role. A pull-request run has two snapshots, and picking one
    by insertion order silently answers a different question than the caller
    asked — `codeatlas compare` would compare the base graph of one run against
    the head graph of another and call a changed run reproducible.
    """
    return session.scalar(
        select(GraphSnapshotRow).where(
            GraphSnapshotRow.run_id == run_id, GraphSnapshotRow.role == role
        )
    )
