"""threat model cache

One threat model per repository. Unlike graph_cache — where a key names all
producers and same-key implies same-content, so rows are append-only — a
threat model is the current understanding of what a system is, and a refresh
legitimately replaces it. The row is therefore replaceable by design, and the
supersession is logged as a run event rather than kept as a second row:
honesty by audit trail instead of honesty by immutability.

Revision ID: d4b8e2f61a97
Revises: a2e9d7c41f83
Create Date: 2026-08-08 09:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d4b8e2f61a97"
down_revision = "a2e9d7c41f83"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "threat_model_cache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("repository_id", sa.String(length=200), nullable=False),
        sa.Column("artifact_sha256", sa.String(length=71), nullable=False),
        sa.Column("modeled_at_revision", sa.String(length=40), nullable=False),
        sa.Column("produced_by_run_id", sa.String(length=26), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repository.id"],
            name=op.f("fk_threat_model_cache_repository_id_repository"),
        ),
        sa.ForeignKeyConstraint(
            ["artifact_sha256"],
            ["artifact.sha256"],
            name=op.f("fk_threat_model_cache_artifact_sha256_artifact"),
        ),
        sa.ForeignKeyConstraint(
            ["produced_by_run_id"],
            ["run.id"],
            name=op.f("fk_threat_model_cache_produced_by_run_id_run"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_threat_model_cache")),
        sa.UniqueConstraint("repository_id", name=op.f("uq_threat_model_cache_repository_id")),
    )


def downgrade() -> None:
    op.drop_table("threat_model_cache")
