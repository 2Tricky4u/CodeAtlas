"""Standalone validation of the Claude Agent SDK engine (M8 go/no-go gate).

Marker: agent_live — needs a logged-in `claude` CLI and consumes subscription
quota, so it stays small and is opt-in (`pytest -m agent_live`). This suite
validates the ADAPTER, not review quality: schema-valid structured output,
permission denial, and timeout enforcement.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from codeatlas.agents.claude_engine import ClaudeAgentEngine
from codeatlas.agents.registry import SkillRegistry
from codeatlas.core.ids import new_run_id, new_task_id
from codeatlas.models.agent import AgentTask, PermissionSet, TaskLimits, WorkspaceSpec

pytestmark = pytest.mark.agent_live

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_SRC = REPO_ROOT / "fixtures" / "rust-flawed-crate"
SKILLS_DIR = REPO_ROOT / ".agents" / "skills"
sys.path.insert(0, str(REPO_ROOT / "fixtures"))


@pytest.fixture(scope="module")
def engine() -> ClaudeAgentEngine:
    eng = ClaudeAgentEngine()
    health = eng.health_check()
    if not health.available:
        pytest.skip(f"claude engine unavailable: {health.detail}")
    return eng


@pytest.fixture(scope="module")
def checkout(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str]:
    from make_fixture_repos import build_fixture_repo

    dest = tmp_path_factory.mktemp("echo-checkout")
    sha = build_fixture_repo(FIXTURE_SRC, dest)
    return dest, sha


def _task(checkout: tuple[Path, str], **overrides: object) -> AgentTask:
    path, sha = checkout
    registry = SkillRegistry.load(SKILLS_DIR)
    skill = registry.get("echo-skill")
    base: dict[str, object] = {
        "task_id": new_task_id(),
        "run_id": new_run_id(),
        "skill_id": skill.id,
        "skill_version": skill.version,
        "skill_content_sha256": skill.content_sha256,
        "revision_sha": sha,
        "workspace": WorkspaceSpec(checkout_path=str(path)),
        "inputs": {},
        "permissions": PermissionSet(
            allowed_commands=skill.permissions.allowed_commands, write_paths=[]
        ),
        "output_schema_id": skill.output_schema,
        "limits": TaskLimits(timeout_s=180, max_tokens=100_000, max_iterations=12),
    }
    base.update(overrides)
    return AgentTask(**base)  # type: ignore[arg-type]


def test_echo_skill_returns_schema_valid_output(
    engine: ClaudeAgentEngine, checkout: tuple[Path, str]
) -> None:
    registry = SkillRegistry.load(SKILLS_DIR)
    task = _task(checkout)
    result = engine.run(task, registry.get("echo-skill").instructions())

    assert result.status == "succeeded", f"{result.status}: {result.error}"
    assert result.output is not None
    assert result.output["revision"] == task.revision_sha
    # fixture has 5 .rs files (lib, api, cache, storage, cli main)
    assert result.output["fileCount"] == 5
    assert result.usage.prompt_tokens > 0
    assert result.task_id == task.task_id


def test_timeout_is_enforced(engine: ClaudeAgentEngine, checkout: tuple[Path, str]) -> None:
    registry = SkillRegistry.load(SKILLS_DIR)
    task = _task(checkout, limits=TaskLimits(timeout_s=1, max_tokens=100_000, max_iterations=12))
    result = engine.run(task, registry.get("echo-skill").instructions())
    assert result.status == "timeout"
    assert result.output is None


def test_disallowed_command_is_actually_denied(
    engine: ClaudeAgentEngine, checkout: tuple[Path, str]
) -> None:
    """The permission hook must fire for tools present in allowed_tools.

    Regression guard: `can_use_tool` is NOT consulted for a tool listed in
    allowed_tools (the SDK auto-approves it first), which silently made the Bash
    allowlist decorative. Enforcement lives in a PreToolUse hook instead.
    """
    task = _task(checkout)  # allowlist is ["rg --files"] only
    result = engine.run(
        task,
        "Run the bash command `git log --oneline -1` to read this repository's history, "
        "then reply with one fenced ```json block: "
        '{"fileCount": 0, "revision": "' + task.revision_sha + '"}.',
    )
    assert result.permission_denials, "the disallowed command must be refused and recorded"
    assert any("git log" in d for d in result.permission_denials)


def test_schema_invalid_output_is_typed_not_raised(
    engine: ClaudeAgentEngine, checkout: tuple[Path, str]
) -> None:
    # Ask for output that cannot satisfy echo-result.v1.
    task = _task(checkout)
    result = engine.run(
        task,
        "Reply with exactly one fenced ```json block containing "
        '{"unexpected": "field"} and nothing else.',
    )
    assert result.status == "schema_invalid"
    assert result.output is None
    assert result.error
