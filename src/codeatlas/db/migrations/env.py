"""Alembic environment: engine injected by db.migrate, or keyring-backed URL."""

from __future__ import annotations

from alembic import context
from sqlalchemy import Engine

from codeatlas.db import tables  # noqa: F401 - register all mapped tables
from codeatlas.db.base import Base

target_metadata = Base.metadata


def run_migrations_online() -> None:
    engine: Engine | None = context.config.attributes.get("connection_engine")
    if engine is None:
        from codeatlas.db.session import migrator_engine

        engine = migrator_engine()

    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
