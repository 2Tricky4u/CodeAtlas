"""echo-skill, replayed offline — the adapter-validation skill's first
offline coverage.

Every other skill has a cassette; echo-skill was exercised only by the
agent_live suite, so the one skill that proves the adapter works had zero
coverage in any normal run. Markers: subproc (git builds the fixture repo).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from codeatlas.agents.dispatch import build_task
from codeatlas.agents.engine import validate_output
from codeatlas.agents.registry import SkillRegistry
from codeatlas.agents.replay_engine import ReplayEngine
from codeatlas.core.ids import new_run_id

pytestmark = pytest.mark.subproc

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_SRC = REPO_ROOT / "fixtures" / "rust-flawed-crate"
CASSETTES = REPO_ROOT / "tests" / "cassettes"
sys.path.insert(0, str(REPO_ROOT / "fixtures"))


def test_echo_skill_replays_and_its_output_validates(tmp_path: Path) -> None:
    from make_fixture_repos import build_fixture_repo

    checkout = tmp_path / "repo"
    sha = build_fixture_repo(FIXTURE_SRC, checkout)

    registry = SkillRegistry.load(REPO_ROOT / ".agents" / "skills")
    skill = registry.get("echo-skill")
    task = build_task(
        skill=skill, run_id=new_run_id(), revision_sha=sha, checkout=checkout, inputs={}
    )
    result = ReplayEngine(CASSETTES).run(task, skill.instructions())

    assert result.status == "succeeded"
    assert validate_output(result.output, "echo-result.v1") == []
    # The skill's whole job: echo the revision it was run at. A cassette that
    # answered for a different revision would not have replayed at all — the
    # key includes the sha — but the content should agree with the key.
    assert isinstance(result.output, dict)
    assert result.output["revision"] == sha
    assert result.output["fileCount"] > 0
