"""graph snapshot role and graph cache

Revision ID: 1713be53b2bc
Revises: bf0c6e3f1cc1
Create Date: 2026-08-06 01:42:08.636672
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "1713be53b2bc"
down_revision = "bf0c6e3f1cc1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "graph_cache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("revision_id", sa.Integer(), nullable=False),
        sa.Column("toolchain_fingerprint", sa.String(length=71), nullable=False),
        sa.Column("graph_sha256", sa.String(length=71), nullable=False),
        sa.Column("produced_by_run_id", sa.String(length=26), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["graph_sha256"], ["artifact.sha256"], name=op.f("fk_graph_cache_graph_sha256_artifact")
        ),
        sa.ForeignKeyConstraint(
            ["produced_by_run_id"], ["run.id"], name=op.f("fk_graph_cache_produced_by_run_id_run")
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"], ["revision.id"], name=op.f("fk_graph_cache_revision_id_revision")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_graph_cache")),
        sa.UniqueConstraint(
            "revision_id", "toolchain_fingerprint", name=op.f("uq_graph_cache_revision_id")
        ),
    )
    op.create_index(
        op.f("ix_graph_cache_revision_id"), "graph_cache", ["revision_id"], unique=False
    )

    # Every snapshot that exists today is of a head revision — the base was
    # pinned and never analyzed. The server default backfills them, then goes
    # away so new code has to state the role it means.
    op.add_column(
        "graph_snapshot",
        sa.Column("role", sa.String(length=20), nullable=False, server_default="head"),
    )
    op.alter_column("graph_snapshot", "role", server_default=None)

    # Before this migration nothing stopped a resumed run from writing a second
    # snapshot, so (run_id, role) may already collide. Those extras are repeat
    # computations of the *same* revision, not a second revision, and deleting
    # them would destroy evidence to satisfy a constraint. They are renamed
    # instead: readers ask for 'head' and get the row `load_snapshot` used to
    # return (the highest id), and the duplicates stay inspectable.
    op.execute(
        sa.text(
            """
            UPDATE graph_snapshot AS gs
               SET role = 'stale-' || gs.id
              FROM (
                    SELECT run_id, MAX(id) AS keep_id
                      FROM graph_snapshot
                     GROUP BY run_id
                    HAVING COUNT(*) > 1
                   ) AS dup
             WHERE gs.run_id = dup.run_id
               AND gs.id <> dup.keep_id
            """
        )
    )
    op.create_unique_constraint(
        op.f("uq_graph_snapshot_run_id"), "graph_snapshot", ["run_id", "role"]
    )


def downgrade() -> None:
    op.drop_constraint(op.f("uq_graph_snapshot_run_id"), "graph_snapshot", type_="unique")
    op.drop_column("graph_snapshot", "role")
    op.drop_index(op.f("ix_graph_cache_revision_id"), table_name="graph_cache")
    op.drop_table("graph_cache")
