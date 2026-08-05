"""Programmatic Alembic entry points (used by tests, CLI, and runbooks)."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _config(engine: Engine) -> Config:
    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option(
        "script_location", str(_REPO_ROOT / "src" / "codeatlas" / "db" / "migrations")
    )
    cfg.attributes["connection_engine"] = engine
    return cfg


def upgrade_head(engine: Engine) -> None:
    command.upgrade(_config(engine), "head")


def downgrade_base(engine: Engine) -> None:
    command.downgrade(_config(engine), "base")
