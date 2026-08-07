"""publication exactly-once index

Revision ID: c9d2f4a71e08
Revises: 1713be53b2bc
Create Date: 2026-08-07 02:00:00.000000

The exactly-once guard in publish_approved is an application-level SELECT.
Under concurrency that is a check-then-act; the approval-row lock serialises
publishers, and this partial unique index is the database-level backstop — a
second `published` row for one approval is impossible even if a future caller
forgets the lock.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c9d2f4a71e08"
down_revision = "1713be53b2bc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_publication_approval_published",
        "publication",
        ["approval_id"],
        unique=True,
        postgresql_where=sa.text("status = 'published'"),
    )


def downgrade() -> None:
    op.drop_index("uq_publication_approval_published", table_name="publication")
