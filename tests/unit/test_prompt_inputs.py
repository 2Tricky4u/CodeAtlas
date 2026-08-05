"""Agents must receive their inputs as CONTENT, never as bare hashes.

Regression found by a live PR review: task inputs were passed to the model as
content-addressed references (`{"candidate": "sha256:..."}`). An agent cannot
dereference a hash, so every stage was starved of its evidence — the
finding-validator echoed the hash back as a finding id, having never seen the
finding it was asked to rule on. It looked like a schema quirk; it was the
review pipeline silently reasoning about nothing.
"""

from __future__ import annotations

from pathlib import Path

from codeatlas.agents.claude_engine import MAX_INLINE_INPUT_CHARS, ClaudeAgentEngine, _build_prompt
from codeatlas.artifacts.store import ArtifactStore
from codeatlas.models.agent import AgentTask, PermissionSet, TaskLimits, WorkspaceSpec

TASK_ID = "01J4QDGJ4W8Z9X7C5V3B2N1M0K"
RUN_ID = "01J4QDGJ4W8Z9X7C5V3B2N1M0A"


def _task(inputs: dict[str, str]) -> AgentTask:
    return AgentTask(
        task_id=TASK_ID,
        run_id=RUN_ID,
        skill_id="finding-validator",
        skill_version="1.0.0",
        skill_content_sha256="sha256:" + "2" * 64,
        revision_sha="a" * 40,
        workspace=WorkspaceSpec(checkout_path="var/checkouts/x"),
        inputs=inputs,
        permissions=PermissionSet(allowed_commands=["rg"], write_paths=[]),
        output_schema_id="validation-result.v1",
        limits=TaskLimits(timeout_s=60, max_tokens=1000, max_iterations=5),
    )


def test_resolved_inputs_are_inlined_as_json(tmp_path: Path) -> None:
    cas = ArtifactStore(tmp_path / "objects")
    ref = cas.put_json({"finding": {"findingId": "F-0007", "claim": "off-by-one"}})
    engine = ClaudeAgentEngine(cas=cas)

    prompt = _build_prompt(
        _task({"candidate": ref}), "INSTRUCTIONS", engine._resolve_inputs(_task({"candidate": ref}))
    )

    assert "F-0007" in prompt, "the agent must see the finding, not its hash"
    assert "off-by-one" in prompt
    assert "### candidate" in prompt


def test_the_hash_alone_is_never_the_only_thing_provided(tmp_path: Path) -> None:
    cas = ArtifactStore(tmp_path / "objects")
    ref = cas.put_json({"findingId": "F-0001"})
    engine = ClaudeAgentEngine(cas=cas)
    resolved = engine._resolve_inputs(_task({"candidate": ref}))
    assert resolved == {"candidate": {"findingId": "F-0001"}}


def test_without_a_store_the_prompt_says_references_not_content() -> None:
    """Explicit degradation: no store means the agent is told these are refs."""
    engine = ClaudeAgentEngine(cas=None)
    task = _task({"candidate": "sha256:" + "0" * 64})
    assert engine._resolve_inputs(task) is None
    prompt = _build_prompt(task, "INSTRUCTIONS", None)
    assert "input references" in prompt


def test_unresolvable_reference_degrades_rather_than_crashing(tmp_path: Path) -> None:
    engine = ClaudeAgentEngine(cas=ArtifactStore(tmp_path / "objects"))
    assert engine._resolve_inputs(_task({"candidate": "sha256:" + "0" * 64})) is None


def test_oversized_input_is_truncated_with_an_explicit_warning(tmp_path: Path) -> None:
    cas = ArtifactStore(tmp_path / "objects")
    huge = {"items": ["x" * 100 for _ in range(2000)]}
    ref = cas.put_json(huge)
    engine = ClaudeAgentEngine(cas=cas)
    task = _task({"graphSlice": ref})

    prompt = _build_prompt(task, "INSTRUCTIONS", engine._resolve_inputs(task))

    assert "TRUNCATED" in prompt
    assert "do not assume anything about it" in prompt
    assert len(prompt) < MAX_INLINE_INPUT_CHARS + 5_000


def test_empty_inputs_produce_no_inputs_section() -> None:
    prompt = _build_prompt(_task({}), "INSTRUCTIONS", None)
    assert "## Inputs" not in prompt
    assert "## Output contract" in prompt
