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

    if skill_id == "change-explainer":
        # This skill explains a *change*, so its fixture is the two-revision one.
        checkout, sha, inputs = _change_explainer_inputs(tmp, cas)
    else:
        checkout = tmp / "repo"
        sha = build_fixture_repo(REPO_ROOT / "fixtures" / "rust-flawed-crate", checkout)

        if skill_id == "intent-reconstructor":
            sources = collect_intent_sources(checkout)
            inputs = {"documents": cas.put_json([s.path for s in sources])}
        elif skill_id.startswith("reviewer-"):
            inputs = _reviewer_inputs(checkout, cas)
        elif skill_id == "finding-validator":
            inputs = _validator_inputs(cas)
        elif skill_id == "attack-path-analyst":
            inputs = _attack_path_inputs(cas)
        elif skill_id in ("project-explainer", "protocol-modeler", "threat-modeler"):
            # All three are handed the deterministic overview and nothing else.
            inputs = _project_explainer_inputs(checkout, sha, cas)
        elif skill_id == "code-answerer":
            # One question about the fixture's known defect, so the replay test
            # can assert the discipline on a claim that is actually checkable.
            inputs = {
                "question": cas.put_json(
                    {
                        "question": "what does eviction actually remove?",
                        "scope": "kvstore/src/cache.rs",
                    }
                )
            }
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
    """The evidence bundle reviewers receive, built exactly as the pipeline does.

    Since Z3 the bundle carries `threatFocus` whenever the repository's threat
    model found threats — so this must reproduce the pipeline's aim exactly, or
    the recorded reviewer cassettes key on inputs the pipeline never sends. The
    focus is computed from the recorded threat-modeler cassette, validated
    against the same file set the pipeline uses (`git ls-tree`), so a focus path
    that would be dropped in the pipeline is dropped here too.
    """
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
        threat_focus=_recorded_threat_focus(checkout, sha, graph),
    )


def _recorded_threat_focus(checkout: Path, sha: str, graph: object) -> dict[str, object] | None:
    """The threatFocus the pipeline would send, from the recorded threat model.

    Mirrors `stage_threat_model` → `model_threats`: validate the raw cassette
    output against the run's file set, then take the aiming subset. Returns None
    when the threat cassette has not been recorded — the reviewers then record
    unaimed, which is a legitimate (threat-model-off) mode, not an error.
    """
    import json

    from codeatlas.models.graph import ProjectGraph
    from codeatlas.models.threat import ThreatModel
    from codeatlas.project.threat import build_threat_index, validate_threat_model
    from codeatlas.review.reviewers import threat_focus_for_reviewers
    from codeatlas.vcs.git import GitClient

    assert isinstance(graph, ProjectGraph)
    cassette = next((REPO_ROOT / "tests" / "cassettes").glob("threat-modeler-*.json"), None)
    if cassette is None:
        return None
    raw = ThreatModel.model_validate(
        json.loads(cassette.read_text(encoding="utf-8"))["result"]["output"]
    )
    raw = raw.model_copy(update={"modeled_at_revision": sha})
    paths = {entry.path for entry in GitClient().ls_tree(checkout, sha)}
    validated, _ = validate_threat_model(raw, build_threat_index(graph, paths=paths))
    return threat_focus_for_reviewers(validated)


def _project_explainer_inputs(checkout: Path, sha: str, cas: ArtifactStore) -> dict[str, str]:
    """The deterministic overview, built exactly as the `project_overview` stage does.

    Recording against a hand-written overview would freeze the skill's behaviour
    on input it never receives — and this is the one input, so it has to be the
    real one.
    """
    from codeatlas.extractors.rust.cargo_meta import CargoMetadataExtractor
    from codeatlas.extractors.rust.ra_scip import RaScipExtractor
    from codeatlas.graph.merge import merge_fragments
    from codeatlas.project.overview import build_overview
    from codeatlas.vcs.git import GitClient

    cargo_fragment, _ = CargoMetadataExtractor().extract(checkout, sha)
    scip_fragment, _ = RaScipExtractor().extract(checkout, sha)
    graph = merge_fragments(
        repository_id="local/kvstore", head_sha=sha, fragments=[cargo_fragment, scip_fragment]
    )
    # Churn included, exactly as the pipeline measures it — the fixture repo is
    # its own history, so `git log` works on the checkout directly.
    churn = GitClient().file_churn(checkout, sha)
    overview = build_overview(graph, repository_id="local/kvstore", churn=churn)
    return {"overview": cas.put_json(overview.contract_dump())}


def _change_explainer_inputs(tmp: Path, cas: ArtifactStore) -> tuple[Path, str, dict[str, str]]:
    """The full deterministic change analysis, exactly as the pipeline assembles it.

    Everything here is the same computation the `graph_diff`, `api_change` and
    `change_impact` stages perform; recording against anything less would freeze
    the skill's behaviour on inputs it never actually receives.
    """
    from make_fixture_repos import build_api_change_fixture_repo

    from codeatlas.change.analysis import assemble_change_analysis

    repo = tmp / "pr-repo"
    base_sha, head_sha = build_api_change_fixture_repo(
        REPO_ROOT / "fixtures" / "rust-flawed-crate", repo
    )
    analysis = assemble_change_analysis(repo, base_sha, head_sha, workdir=tmp)
    return (
        analysis.head_tree,
        head_sha,
        analysis.agent_inputs(cas.put, cas.put_json),
    )


def _attack_path_candidate() -> dict[str, object]:
    """The {finding, validation} an attack-path analysis receives.

    A validated *security* finding from the security reviewer's cassette, with a
    validated verdict synthesized deterministically — the exact shape
    `analyze_attack_paths` builds. Shared with the replay test so the recorded
    cassette is keyed on the identical candidate.
    """
    import json

    from codeatlas.models.findings import Finding
    from codeatlas.models.validation import ValidationResult

    # Newest by name, so a lingering older-version cassette cannot silently
    # supply the candidate and key this recording on a version we are replacing.
    matches = sorted((REPO_ROOT / "tests" / "cassettes").glob("reviewer-security-*.json"))
    if not matches:
        raise SystemExit("record the reviewer-security cassette first")
    findings = json.loads(matches[-1].read_text(encoding="utf-8"))["result"]["output"]["findings"]
    finding = Finding.model_validate(findings[0])
    verdict = ValidationResult(
        finding_id=finding.finding_id,
        status="validated",
        severity=finding.severity,
        confidence=0.95,
        introduced_by_change=True,
        location=finding.location,
        claim=finding.claim,
        evidence=[],
        counter_evidence_checked=["callers", "existing tests"],
        publication_eligible=True,
        reason="the cited sink is reached with attacker-controlled input and no guard",
    )
    return {"finding": finding.contract_dump(), "validation": verdict.contract_dump()}


def _attack_path_inputs(cas: ArtifactStore) -> dict[str, str]:
    return {"candidate": cas.put_json(_attack_path_candidate())}


def _validator_inputs(cas: ArtifactStore) -> dict[str, str]:
    """One candidate finding as the validation stage would present it.

    Uses a recorded reviewer finding so the cassette exercises a realistic claim.
    """
    import json

    from codeatlas.models.findings import Finding

    # Newest by name, so a lingering older-version reviewer cassette cannot
    # silently supply the candidate this validator recording keys on.
    matches = sorted((REPO_ROOT / "tests" / "cassettes").glob("reviewer-correctness-*.json"))
    if not matches:
        raise SystemExit("record the reviewer cassettes first")
    findings = json.loads(matches[-1].read_text(encoding="utf-8"))["result"]["output"]["findings"]
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
