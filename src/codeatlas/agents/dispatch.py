"""Task dispatch: build an AgentTask from a registry skill, run it, record it.

This is the single place where a skill's declared permissions become a task's
permissions, where budgets are checked before dispatch, and where invocations
are persisted — so every agent inference in the system has a row explaining who
produced it, under which instructions, at what cost.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from codeatlas.agents.budget import TokenBudget
from codeatlas.agents.registry import Skill, SkillRegistry
from codeatlas.artifacts.store import ArtifactStore
from codeatlas.core.ids import new_task_id
from codeatlas.core.logging import get_logger
from codeatlas.db.tables import AgentInvocationRow
from codeatlas.models.agent import AgentResult, AgentTask, PermissionSet, TaskLimits, WorkspaceSpec

log = get_logger("codeatlas.agents.dispatch")

DEFAULT_LIMITS = TaskLimits(timeout_s=600, max_tokens=200_000, max_iterations=30)


class RunnableEngine(Protocol):
    name: str

    def run(self, task: AgentTask, instructions: str) -> AgentResult: ...


def build_task(
    skill: Skill,
    run_id: str,
    revision_sha: str,
    checkout: Path,
    inputs: dict[str, str],
    limits: TaskLimits = DEFAULT_LIMITS,
) -> AgentTask:
    return AgentTask(
        task_id=new_task_id(),
        run_id=run_id,
        skill_id=skill.id,
        skill_version=skill.version,
        skill_content_sha256=skill.content_sha256,
        revision_sha=revision_sha,
        workspace=WorkspaceSpec(checkout_path=str(checkout)),
        inputs=inputs,
        permissions=PermissionSet(
            allowed_commands=skill.permissions.allowed_commands,
            write_paths=skill.permissions.write_paths,
        ),
        output_schema_id=skill.output_schema,
        limits=limits,
    )


def dispatch(
    engine: RunnableEngine,
    registry: SkillRegistry,
    skill_id: str,
    task: AgentTask,
    db_engine: Engine,
    cas: ArtifactStore,
    budget: TokenBudget | None = None,
) -> AgentResult:
    """Run one agent task and persist the invocation record."""
    skill = registry.get(skill_id)
    if budget is not None:
        budget.check_task(task)

    result = engine.run(task, skill.instructions())

    if budget is not None:
        budget.consume(result)

    result_sha = cas.put_json(result.contract_dump())
    # The cassette key is a pure function of the task; recording it under
    # replay is what lets the manifest name the cassettes a run answered from.
    from codeatlas.agents.replay_engine import cassette_key

    with Session(db_engine) as session:
        session.add(
            AgentInvocationRow(
                run_id=task.run_id,
                task_id=task.task_id,
                skill_id=task.skill_id,
                skill_version=task.skill_version,
                engine=engine.name,
                status=result.status,
                prompt_tokens=result.usage.prompt_tokens,
                completion_tokens=result.usage.completion_tokens,
                cost_usd=result.usage.cost_usd,
                duration_ms=result.usage.wall_ms,
                transcript_sha256=result.transcript_ref,
                result_sha256=result_sha,
                model_id=result.usage.model_id,
                cassette_key=cassette_key(task) if engine.name == "replay" else None,
            )
        )
        session.commit()

    log.info(
        "agent.invocation",
        run_id=task.run_id,
        task_id=task.task_id,
        skill=f"{task.skill_id}@{task.skill_version}",
        status=result.status,
        denials=len(result.permission_denials),
    )
    return result
