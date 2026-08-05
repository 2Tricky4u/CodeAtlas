"""Token budgets.

The agent engine runs on subscription auth, so dollar cost is usually unknown;
budgets are therefore enforced in tokens. A task whose declared maximum exceeds
the remaining run budget is refused *before* dispatch — never truncated mid-run.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from codeatlas.models.agent import AgentResult, AgentTask


class BudgetExceeded(RuntimeError):
    """A task would exceed, or a result did exceed, the configured budget."""


@dataclass
class TokenBudget:
    max_run_tokens: int
    max_task_tokens: int
    spent: int = field(default=0)

    @property
    def remaining(self) -> int:
        return max(0, self.max_run_tokens - self.spent)

    def check_task(self, task: AgentTask) -> None:
        if task.limits.max_tokens > self.max_task_tokens:
            raise BudgetExceeded(
                f"task {task.task_id} declares {task.limits.max_tokens} tokens "
                f"> per-task cap {self.max_task_tokens}"
            )
        if task.limits.max_tokens > self.remaining:
            raise BudgetExceeded(
                f"task {task.task_id} may use {task.limits.max_tokens} tokens "
                f"> {self.remaining} remaining in the run budget"
            )

    def consume(self, result: AgentResult) -> None:
        self.spent += result.usage.prompt_tokens + result.usage.completion_tokens
        if self.spent > self.max_run_tokens:
            raise BudgetExceeded(
                f"run budget exhausted: {self.spent} > {self.max_run_tokens} tokens"
            )
