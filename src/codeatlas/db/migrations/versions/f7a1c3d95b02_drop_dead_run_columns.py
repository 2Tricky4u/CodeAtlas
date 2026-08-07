"""drop dead run columns; timing columns become real

Revision ID: f7a1c3d95b02
Revises: e4f8b2c60a17
Create Date: 2026-08-07 06:00:00.000000

Six columns the audit found never written and never read: the manifest is the
home of pipeline version, config hash, toolchain and cost; default_branch and
ref_name were parameters nobody passed. started_at/finished_at stay — the
repository layer now writes them.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "f7a1c3d95b02"
down_revision = "e4f8b2c60a17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("run", "pipeline_version")
    op.drop_column("run", "config_sha256")
    op.drop_column("run", "toolchain")
    op.drop_column("run", "cost")
    op.drop_column("repository", "default_branch")
    op.drop_column("revision", "ref_name")


def downgrade() -> None:
    op.add_column("revision", sa.Column("ref_name", sa.String(length=300), nullable=True))
    op.add_column("repository", sa.Column("default_branch", sa.String(length=200), nullable=True))
    op.add_column("run", sa.Column("cost", JSONB(), nullable=True))
    op.add_column("run", sa.Column("toolchain", JSONB(), nullable=True))
    op.add_column("run", sa.Column("config_sha256", sa.String(length=71), nullable=True))
    op.add_column("run", sa.Column("pipeline_version", sa.String(length=60), nullable=True))
