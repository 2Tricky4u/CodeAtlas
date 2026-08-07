"""Deterministic stand-in engines for pipeline tests.

A cassette replays a *recorded* model answer and is keyed to exact inputs; a
scripted engine answers with whatever the test declares, which is what wiring
tests need — they assert which stages ran and what artifacts landed, never
prose. Both live here so no test file grows its own private engine.
"""

from __future__ import annotations

from collections.abc import Callable

from codeatlas.models.agent import AgentResult, AgentTask, UsageStats


def _result(task: AgentTask, output: object) -> AgentResult:
    return AgentResult(
        task_id=task.task_id,
        status="succeeded",
        output=output,
        command_receipts=[],
        usage=UsageStats(
            prompt_tokens=1, completion_tokens=1, cost_usd=None, wall_ms=1, model_id="scripted"
        ),
    )


class ScriptedEngine:
    """Answers each task from a script keyed by skill id, recording all tasks.

    A value may be a plain output dict, a callable taking the task, or an
    Exception instance — which is raised, for degraded-run tests. An unknown
    skill raises loudly rather than inventing an answer.
    """

    name = "scripted"

    def __init__(self, script: dict[str, object]) -> None:
        self.script = script
        self.seen: list[AgentTask] = []

    def run(self, task: AgentTask, instructions: str) -> AgentResult:
        self.seen.append(task)
        if task.skill_id not in self.script:
            raise KeyError(f"no scripted output for {task.skill_id}")
        outcome = self.script[task.skill_id]
        if isinstance(outcome, Exception):
            raise outcome
        if callable(outcome):
            outcome = outcome(task)
        return _result(task, outcome)


class StubEngine:
    """A single responder for every task — the shape validator tests want."""

    name = "stub"

    def __init__(self, responder: Callable[[AgentTask], object]) -> None:
        self.responder = responder
        self.seen: list[AgentTask] = []

    def run(self, task: AgentTask, instructions: str) -> AgentResult:
        self.seen.append(task)
        return _result(task, self.responder(task))


class FailingEngine:
    """Every dispatch explodes — the engine-level failure path."""

    name = "failing"

    def run(self, task: AgentTask, instructions: str) -> AgentResult:
        raise RuntimeError("engine exploded")


class FlakyEngine:
    """Typed failures for the first N attempts, then success — retry tests.

    Records every (task, instructions) pair so a test can assert the second
    attempt carried the first failure's error text, and that task ids differ.
    """

    name = "flaky"

    def __init__(
        self,
        first_status: str,
        output: object,
        error: str = "['findings']: 'x' is not of type 'array'",
        failures: int = 1,
    ) -> None:
        self.first_status = first_status
        self.output = output
        self.error = error
        self.failures = failures
        self.calls: list[tuple[AgentTask, str]] = []

    def run(self, task: AgentTask, instructions: str) -> AgentResult:
        self.calls.append((task, instructions))
        if len(self.calls) <= self.failures:
            return AgentResult(
                task_id=task.task_id,
                status=self.first_status,  # type: ignore[arg-type]
                output=None,
                error=self.error,
                command_receipts=[],
                usage=UsageStats(
                    prompt_tokens=1, completion_tokens=0, cost_usd=None, wall_ms=1, model_id="flaky"
                ),
            )
        return _result(task, self.output)
