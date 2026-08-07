"""invocation model and cassette provenance

Revision ID: e4f8b2c60a17
Revises: c9d2f4a71e08
Create Date: 2026-08-07 05:00:00.000000

The manifest's modelIds/cassetteIds were hard-coded empty because the ledger
never recorded either. The model id is in every AgentResult's usage; the
cassette key is a pure function of the task when the engine is the replayer.
Both become columns so finalize can report what actually answered.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e4f8b2c60a17"
down_revision = "c9d2f4a71e08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_invocation", sa.Column("model_id", sa.String(length=100), nullable=True))
    op.add_column(
        "agent_invocation", sa.Column("cassette_key", sa.String(length=120), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("agent_invocation", "cassette_key")
    op.drop_column("agent_invocation", "model_id")
