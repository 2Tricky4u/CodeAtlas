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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from codeatlas.artifacts.store import ArtifactStore

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
    tmp = Path(tempfile.mkdtemp(prefix="codeatlas-record-"))
    cas = ArtifactStore(tmp / "objects")

    # The engine shares the store so it can inline each input's content.
    engine = ClaudeAgentEngine(cas=cas)
    health = engine.health_check()
    if not health.available:
        print(f"engine unavailable: {health.detail}", file=sys.stderr)
        return 1

    registry = SkillRegistry.load(REPO_ROOT / ".agents" / "skills")
    skill = registry.get(skill_id)

    checkout = tmp / "repo"
    sha = build_fixture_repo(REPO_ROOT / "fixtures" / "rust-flawed-crate", checkout)

    if skill_id == "intent-reconstructor":
        sources = collect_intent_sources(checkout)
        inputs = {"documents": cas.put_json([s.path for s in sources])}
    elif skill_id.startswith("reviewer-"):
        inputs = _reviewer_inputs(checkout, cas)
    elif skill_id == "finding-validator":
        inputs = _validator_inputs(cas)
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


def _reviewer_inputs(checkout: Path, cas: ArtifactStore) -> dict[str, str]:
    """The evidence bundle reviewers receive, built exactly as the pipeline does."""
    import json

    from codeatlas.extractors.rust.cargo_meta import CargoMetadataExtractor
    from codeatlas.extractors.rust.ra_scip import RaScipExtractor
    from codeatlas.graph.merge import merge_fragments
    from codeatlas.models.intent import IntentPackage
    from codeatlas.review.reviewers import build_reviewer_inputs, slice_graph_for_review
    from codeatlas.vcs.git import GitClient

    sha = GitClient().resolve_sha(checkout, "HEAD")
    cargo_fragment, _ = CargoMetadataExtractor().extract(checkout, sha)
    scip_fragment, _ = RaScipExtractor().extract(checkout, sha)
    graph = merge_fragments(
        repository_id="local/kvstore", head_sha=sha, fragments=[cargo_fragment, scip_fragment]
    )
    source_paths = sorted(
        p.relative_to(checkout).as_posix()
        for p in checkout.rglob("*.rs")
        if "target" not in p.parts
    )

    cassette = next((REPO_ROOT / "tests" / "cassettes").glob("intent-reconstructor-*.json"), None)
    if cassette is None:
        raise SystemExit("record the intent-reconstructor cassette first")
    intent = IntentPackage.model_validate(
        json.loads(cassette.read_text(encoding="utf-8"))["result"]["output"]
    )

    return build_reviewer_inputs(
        cas=cas,
        intent=intent,
        source_paths=source_paths,
        graph_slice=slice_graph_for_review(graph, source_paths),
    )


def _validator_inputs(cas: ArtifactStore) -> dict[str, str]:
    """One candidate finding as the validation stage would present it.

    Uses a recorded reviewer finding so the cassette exercises a realistic claim.
    """
    import json

    from codeatlas.models.findings import Finding

    cassette = next((REPO_ROOT / "tests" / "cassettes").glob("reviewer-correctness-*.json"), None)
    if cassette is None:
        raise SystemExit("record the reviewer cassettes first")
    findings = json.loads(cassette.read_text(encoding="utf-8"))["result"]["output"]["findings"]
    finding = Finding.model_validate(findings[0])
    payload = {
        "finding": finding.contract_dump(),
        "verification": {
            "diagnosticsAtLocation": [],
            "failingTests": [],
            "summary": {"diagnostics": 0, "tests": 0, "failingTests": 0},
        },
    }
    return {"candidate": cas.put_json(payload)}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
