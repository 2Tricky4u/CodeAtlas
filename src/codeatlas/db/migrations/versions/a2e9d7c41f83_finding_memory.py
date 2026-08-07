"""finding memory

Cross-run memory of agent-produced rejections (ADR-0016). Keyed by
(repository, semantic fingerprint, file blob sha): the blob in the key makes
same-key imply same-decision, so rows are append-only and never overwritten.
A recurring finding at byte-identical code with an overlapping span is
suppressed instead of re-dispatched; any miss fails open into validation.

Revision ID: a2e9d7c41f83
Revises: f7a1c3d95b02
Create Date: 2026-08-07 17:20:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a2e9d7c41f83"
down_revision = "f7a1c3d95b02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "finding_memory",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("repository_id", sa.String(length=200), nullable=False),
        sa.Column("fingerprint", sa.String(length=71), nullable=False),
        sa.Column("file_blob_sha", sa.String(length=40), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=True),
        sa.Column("end_line", sa.Integer(), nullable=True),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column("severity", sa.String(length=10), nullable=False),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("decided_in_run", sa.String(length=26), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repository.id"],
            name=op.f("fk_finding_memory_repository_id_repository"),
        ),
        sa.ForeignKeyConstraint(
            ["decided_in_run"], ["run.id"], name=op.f("fk_finding_memory_decided_in_run_run")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_finding_memory")),
        sa.UniqueConstraint(
            "repository_id",
            "fingerprint",
            "file_blob_sha",
            name=op.f("uq_finding_memory_repository_id"),
        ),
    )
    op.create_index(
        op.f("ix_finding_memory_repository_id"),
        "finding_memory",
        ["repository_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_finding_memory_repository_id"), table_name="finding_memory")
    op.drop_table("finding_memory")
