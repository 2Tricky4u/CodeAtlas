"""Record a replay cassette by running a skill against the live engine.

Recording is a deliberate, reviewed act (ADR-0012): it consumes real quota and
freezes an agent's output as the expected behavior for CI. Re-record only when a
skill's instructions change — and bump the skill version so stale cassettes are
invalidated rather than silently reused.

Usage:
  uv run python scripts/record_cassette.py intent-reconstructor
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "fixtures"))


def main(skill_id: str) -> int:
    from make_fixture_repos import build_fixture_repo

    from codeatlas.agents.claude_engine import ClaudeAgentEngine
    from codeatlas.agents.dispatch import build_task
    from codeatlas.agents.registry import SkillRegistry
    from codeatlas.agents.replay_engine import ReplayEngine
    from codeatlas.artifacts.store import ArtifactStore
    from codeatlas.core.ids import new_run_id
    from codeatlas.core.logging import configure_logging
    from codeatlas.review.intent import collect_intent_sources

    configure_logging()
    engine = ClaudeAgentEngine()
    health = engine.health_check()
    if not health.available:
        print(f"engine unavailable: {health.detail}", file=sys.stderr)
        return 1

    registry = SkillRegistry.load(REPO_ROOT / ".agents" / "skills")
    skill = registry.get(skill_id)

    tmp = Path(tempfile.mkdtemp(prefix="codeatlas-record-"))
    checkout = tmp / "repo"
    sha = build_fixture_repo(REPO_ROOT / "fixtures" / "rust-flawed-crate", checkout)
    cas = ArtifactStore(tmp / "objects")

    if skill_id == "intent-reconstructor":
        sources = collect_intent_sources(checkout)
        inputs = {"documents": cas.put_json([s.path for s in sources])}
    else:
        inputs = {}

    task = build_task(
        skill=skill, run_id=new_run_id(), revision_sha=sha, checkout=checkout, inputs=inputs
    )
    result = engine.run(task, skill.instructions())
    print(f"status={result.status} error={result.error}")
    if result.status != "succeeded":
        return 2

    ReplayEngine(REPO_ROOT / "tests" / "cassettes").record(task, result)
    print(f"recorded cassette for {skill_id}@{skill.version}")
    print(f"fixture sha (cassette is keyed on it): {sha}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
