"""Dependency container for the pipeline (engine, stores, paths) — enables
test injection (test DB, tmp CAS, crash-stage fault injection) without config
globals."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import Engine

from codeatlas.artifacts.store import ArtifactStore
from codeatlas.vcs.git import GitClient


@dataclass
class PipelineDeps:
    engine: Engine
    workdir: Path  # mirrors + pinned checkouts live under here
    cas: ArtifactStore
    checkpoint_path: Path  # SqliteSaver database file
    git: GitClient = field(default_factory=GitClient)
    crash_stage: str | None = None  # fault injection for resume tests

    @property
    def mirrors(self) -> Path:
        return self.workdir / "mirrors"

    @property
    def checkouts(self) -> Path:
        return self.workdir / "checkouts"
