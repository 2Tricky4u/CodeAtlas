"""Relational spine for the evidence store (PostgreSQL, SQLAlchemy 2.x typed).

Contract payloads (receipts, findings, manifests) are stored verbatim as JSONB
alongside indexed columns extracted for querying — the JSON contract remains the
source of truth; columns are projections. Domain tables that belong to later
milestones (symbols, components, architecture, protocols, decisions,
requirements, tests) arrive with their milestones' migrations.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from codeatlas.db.base import Base

RUN_STATUSES = (
    "created",
    "running",
    "paused_for_approval",
    "succeeded",
    "succeeded_with_gaps",
    "failed",
    "cancelled",
)

FINDING_STATUSES = ("candidate", "validated", "rejected", "duplicate", "unresolved", "suppressed")


class RepositoryRow(Base):
    __tablename__ = "repository"

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    provider: Mapped[str] = mapped_column(String(20))
    remote_url: Mapped[str | None] = mapped_column(Text)
    default_branch: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RevisionRow(Base):
    __tablename__ = "revision"
    __table_args__ = (UniqueConstraint("repository_id", "sha"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repository_id: Mapped[str] = mapped_column(ForeignKey("repository.id"))
    sha: Mapped[str] = mapped_column(String(40))
    ref_name: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FileRow(Base):
    __tablename__ = "file"
    __table_args__ = (UniqueConstraint("revision_id", "path"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    revision_id: Mapped[int] = mapped_column(ForeignKey("revision.id"))
    path: Mapped[str] = mapped_column(Text)
    git_blob_sha: Mapped[str] = mapped_column(String(40))
    language: Mapped[str | None] = mapped_column(String(40))
    is_generated: Mapped[bool] = mapped_column(Boolean, default=False)


class RunRow(Base):
    __tablename__ = "run"
    __table_args__ = (
        CheckConstraint("status IN ('" + "','".join(RUN_STATUSES) + "')", name="status_valid"),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    repository_id: Mapped[str] = mapped_column(ForeignKey("repository.id"))
    kind: Mapped[str] = mapped_column(String(20))
    pr_number: Mapped[int | None] = mapped_column(Integer)
    base_revision_id: Mapped[int | None] = mapped_column(ForeignKey("revision.id"))
    head_revision_id: Mapped[int] = mapped_column(ForeignKey("revision.id"))
    status: Mapped[str] = mapped_column(String(30), default="created")
    pipeline_version: Mapped[str | None] = mapped_column(String(60))
    skill_registry_sha256: Mapped[str | None] = mapped_column(String(71))
    config_sha256: Mapped[str | None] = mapped_column(String(71))
    toolchain: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    cost: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    manifest_sha256: Mapped[str | None] = mapped_column(String(71))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    events: Mapped[list[RunEventRow]] = relationship(
        back_populates="run", order_by="RunEventRow.id"
    )
    receipts: Mapped[list[ExtractorReceiptRow]] = relationship(back_populates="run")


class RunEventRow(Base):
    __tablename__ = "run_event"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("run.id"), index=True)
    stage: Mapped[str] = mapped_column(String(60))
    event: Mapped[str] = mapped_column(String(60))
    level: Mapped[str] = mapped_column(String(10), default="info")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    run: Mapped[RunRow] = relationship(back_populates="events")


class ExtractorReceiptRow(Base):
    __tablename__ = "extractor_receipt"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("run.id"), index=True)
    extractor: Mapped[str] = mapped_column(String(60))
    extractor_version: Mapped[str] = mapped_column(String(200))
    revision_sha: Mapped[str] = mapped_column(String(40))
    exit_code: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)

    run: Mapped[RunRow] = relationship(back_populates="receipts")


class ArtifactRow(Base):
    __tablename__ = "artifact"

    sha256: Mapped[str] = mapped_column(String(71), primary_key=True)
    kind: Mapped[str] = mapped_column(String(60))
    media_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    schema_id: Mapped[str | None] = mapped_column(String(60))
    producer: Mapped[str] = mapped_column(String(100))
    # The run that FIRST produced this content. Identical content produced by a
    # later run keeps this value, so it is provenance, not membership — use
    # run_artifact to ask which runs an artifact belongs to.
    produced_by_run_id: Mapped[str | None] = mapped_column(ForeignKey("run.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RunArtifactRow(Base):
    """Which artifacts belong to which run.

    Artifacts are content-addressed, so two runs that produce identical output
    share one row — that is the point of the store. Attributing an artifact to a
    single producing run therefore made every repeat run look as though it had
    produced nothing, and the API returned 404 for a graph that plainly existed.
    Membership is a relation, not a column.
    """

    __tablename__ = "run_artifact"
    __table_args__ = (UniqueConstraint("run_id", "sha256", "role"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("run.id"), index=True)
    sha256: Mapped[str] = mapped_column(ForeignKey("artifact.sha256"), index=True)
    role: Mapped[str] = mapped_column(String(60))  # the artifact's kind for this run
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GraphSnapshotRow(Base):
    """One revision's graph, as produced by one run.

    A pull-request run holds two: the head under review and the base it changed.
    `role` is what tells them apart — every reader must ask for the one it means,
    because "the run's graph" stopped being a well-defined phrase the moment a
    run could analyze two revisions.
    """

    __tablename__ = "graph_snapshot"
    __table_args__ = (UniqueConstraint("run_id", "role"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("run.id"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="head")
    revision_id: Mapped[int] = mapped_column(ForeignKey("revision.id"))
    schema_version: Mapped[str] = mapped_column(String(20))
    canonical_sha256: Mapped[str] = mapped_column(String(71))
    artifact_sha256: Mapped[str] = mapped_column(ForeignKey("artifact.sha256"))
    node_count: Mapped[int] = mapped_column(Integer)
    edge_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    nodes: Mapped[list[GraphNodeRow]] = relationship(back_populates="snapshot")
    edges: Mapped[list[GraphEdgeRow]] = relationship(
        back_populates="snapshot", order_by="GraphEdgeRow.natural_id"
    )


class GraphCacheRow(Base):
    """An already-computed graph, reusable when nothing that produced it changed.

    A project graph is a deterministic function of (revision, extractor
    toolchain, normalization code) — ADR-0007 — so an entry whose key matches is
    the graph re-extraction would produce. `produced_by_run_id` keeps a reused
    graph traceable to the run whose receipts actually witness it.
    """

    __tablename__ = "graph_cache"
    __table_args__ = (UniqueConstraint("revision_id", "toolchain_fingerprint"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision_id: Mapped[int] = mapped_column(ForeignKey("revision.id"), index=True)
    toolchain_fingerprint: Mapped[str] = mapped_column(String(71))
    graph_sha256: Mapped[str] = mapped_column(ForeignKey("artifact.sha256"))
    produced_by_run_id: Mapped[str] = mapped_column(ForeignKey("run.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GraphNodeRow(Base):
    __tablename__ = "graph_node"
    __table_args__ = (UniqueConstraint("snapshot_id", "natural_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("graph_snapshot.id"), index=True)
    natural_id: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(30))
    label: Mapped[str] = mapped_column(Text)
    path: Mapped[str | None] = mapped_column(Text)
    start_line: Mapped[int | None] = mapped_column(Integer)
    end_line: Mapped[int | None] = mapped_column(Integer)
    attrs: Mapped[dict[str, Any]] = mapped_column(JSONB)

    snapshot: Mapped[GraphSnapshotRow] = relationship(back_populates="nodes")


class GraphEdgeRow(Base):
    __tablename__ = "graph_edge"
    __table_args__ = (UniqueConstraint("snapshot_id", "natural_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("graph_snapshot.id"), index=True)
    natural_id: Mapped[str] = mapped_column(Text)
    source_natural_id: Mapped[str] = mapped_column(Text, index=True)
    target_natural_id: Mapped[str] = mapped_column(Text, index=True)
    kind: Mapped[str] = mapped_column(String(30))
    configuration: Mapped[str | None] = mapped_column(Text)
    attrs: Mapped[dict[str, Any]] = mapped_column(JSONB)

    snapshot: Mapped[GraphSnapshotRow] = relationship(back_populates="edges")


class FindingRow(Base):
    __tablename__ = "finding"
    __table_args__ = (
        UniqueConstraint("run_id", "finding_id"),
        CheckConstraint("status IN ('" + "','".join(FINDING_STATUSES) + "')", name="status_valid"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("run.id"), index=True)
    finding_id: Mapped[str] = mapped_column(String(10))
    category: Mapped[str] = mapped_column(String(20))
    severity: Mapped[str] = mapped_column(String(10))
    confidence: Mapped[float] = mapped_column(Float)
    claim: Mapped[str] = mapped_column(Text)
    path: Mapped[str] = mapped_column(Text)
    start_line: Mapped[int | None] = mapped_column(Integer)
    end_line: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="candidate")
    duplicate_of: Mapped[str | None] = mapped_column(String(10))
    discovered_by_skill: Mapped[str] = mapped_column(String(60))
    skill_version: Mapped[str] = mapped_column(String(30))
    introduced_by_change: Mapped[bool | None] = mapped_column(Boolean)
    publication_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    validation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class AgentInvocationRow(Base):
    __tablename__ = "agent_invocation"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("run.id"), index=True)
    task_id: Mapped[str] = mapped_column(String(26), unique=True)
    skill_id: Mapped[str] = mapped_column(String(60))
    skill_version: Mapped[str] = mapped_column(String(30))
    engine: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float | None] = mapped_column(Float)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    transcript_sha256: Mapped[str | None] = mapped_column(String(71))
    result_sha256: Mapped[str | None] = mapped_column(String(71))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ApprovalRow(Base):
    __tablename__ = "approval"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("run.id"), index=True)
    action_kind: Mapped[str] = mapped_column(String(40))
    payload_sha256: Mapped[str] = mapped_column(ForeignKey("artifact.sha256"))
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[str | None] = mapped_column(String(100))
    decision: Mapped[str | None] = mapped_column(String(10))
    decision_note: Mapped[str | None] = mapped_column(Text)


class PublicationRow(Base):
    __tablename__ = "publication"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    approval_id: Mapped[int] = mapped_column(ForeignKey("approval.id"))
    run_id: Mapped[str] = mapped_column(ForeignKey("run.id"), index=True)
    target_kind: Mapped[str] = mapped_column(String(40))
    external_ref: Mapped[str | None] = mapped_column(Text)
    payload_sha256: Mapped[str] = mapped_column(String(71))
    status: Mapped[str] = mapped_column(String(20))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
