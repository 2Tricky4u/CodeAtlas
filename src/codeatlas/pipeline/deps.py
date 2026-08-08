"""Dependency container for the pipeline.

Everything the stages need is injected here rather than read from globals, so a
test can substitute a test database, a temporary artifact store, a replay agent
engine, or a deliberately crashing stage without touching configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import Engine

from codeatlas.agents.budget import TokenBudget
from codeatlas.agents.registry import SkillRegistry
from codeatlas.artifacts.store import ArtifactStore
from codeatlas.vcs.git import GitClient

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SKILLS_DIR = REPO_ROOT / ".agents" / "skills"


@dataclass
class PipelineDeps:
    engine: Engine
    workdir: Path  # mirrors + pinned checkouts live under here
    cas: ArtifactStore
    checkpoint_path: Path  # SqliteSaver database file
    git: GitClient = field(default_factory=GitClient)
    crash_stage: str | None = None  # fault injection for resume tests

    # Agent stages. When `agent_engine` is None the pipeline runs its
    # deterministic half only — extraction, graph, diagrams — which is a valid
    # and useful mode, not a degraded one.
    agent_engine: object | None = None
    skills_dir: Path = DEFAULT_SKILLS_DIR
    budget: TokenBudget | None = None

    # The two agent capabilities are independent and are switched independently:
    # explaining a project needs no pull request, and reviewing one needs nobody
    # to open the map. They were a single flag, which made "narrate this
    # repository" mean "and also run four reviewers and a validator per finding".
    narration_enabled: bool = True
    review_enabled: bool = True
    # The threat model is cached per repository; this forces a rebuild even
    # when a cached one exists. The supersession is logged as a run event.
    refresh_threat_model: bool = False

    # Publication target. Absent means the run stops after the report.
    github_owner: str | None = None
    github_repo: str | None = None
    pr_number: int | None = None
    # Inline comments already on the PR ({path, line, body} each), fetched by
    # review-pr so the payload can fold already-posted findings into a note
    # instead of posting them twice. None = not fetched; dedup is off.
    existing_review_comments: list[dict[str, Any]] | None = None

    @property
    def mirrors(self) -> Path:
        return self.workdir / "mirrors"

    @property
    def checkouts(self) -> Path:
        return self.workdir / "checkouts"

    @property
    def artifacts_dir(self) -> Path:
        return self.workdir / "artifacts"

    def registry(self) -> SkillRegistry:
        return SkillRegistry.load(self.skills_dir)

    @property
    def reviews_enabled(self) -> bool:
        return self.agent_engine is not None and self.review_enabled

    @property
    def narration_available(self) -> bool:
        return self.agent_engine is not None and self.narration_enabled
