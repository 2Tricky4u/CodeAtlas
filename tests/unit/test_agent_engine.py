"""Agent adapter boundary: replay engine, budgets, schema validation, dispatch."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from codeatlas.agents.budget import BudgetExceeded, TokenBudget
from codeatlas.agents.replay_engine import CassetteMissing, ReplayEngine
from codeatlas.models.agent import (
    AgentResult,
    AgentTask,
    CommandReceipt,
    PermissionSet,
    TaskLimits,
    UsageStats,
    WorkspaceSpec,
)

SHA = "a" * 40
TASK_ID = "01J4QDGJ4W8Z9X7C5V3B2N1M0K"
RUN_ID = "01J4QDGJ4W8Z9X7C5V3B2N1M0A"


def _task(**overrides: object) -> AgentTask:
    base = {
        "task_id": TASK_ID,
        "run_id": RUN_ID,
        "skill_id": "echo-skill",
        "skill_version": "1.0.0",
        "skill_content_sha256": "sha256:" + "2" * 64,
        "revision_sha": SHA,
        "workspace": WorkspaceSpec(checkout_path="var/checkouts/x"),
        "inputs": {"graphSlice": "sha256:" + "3" * 64},
        "permissions": PermissionSet(allowed_commands=["rg"], write_paths=[]),
        "output_schema_id": "finding.v1",
        "limits": TaskLimits(timeout_s=60, max_tokens=1000, max_iterations=5),
    }
    base.update(overrides)
    return AgentTask(**base)  # type: ignore[arg-type]


def _result(status: str = "succeeded", tokens: int = 100) -> AgentResult:
    return AgentResult(
        task_id=TASK_ID,
        status=status,  # type: ignore[arg-type]
        output={"ok": True},
        command_receipts=[CommandReceipt(command="rg x", exit_code=0, duration_ms=5)],
        usage=UsageStats(
            prompt_tokens=tokens,
            completion_tokens=tokens,
            cost_usd=None,
            wall_ms=100,
            model_id="claude-fable-5",
        ),
    )


class TestReplayEngine:
    def test_returns_recorded_result(self, tmp_path: Path) -> None:
        engine = ReplayEngine(tmp_path)
        engine.record(_task(), _result())
        out = engine.run(_task())
        assert out.status == "succeeded"
        assert out.output == {"ok": True}

    def test_cassette_key_depends_on_skill_version(self, tmp_path: Path) -> None:
        engine = ReplayEngine(tmp_path)
        engine.record(_task(), _result())
        with pytest.raises(CassetteMissing):
            engine.run(_task(skill_version="1.1.0"))

    def test_cassette_key_depends_on_inputs(self, tmp_path: Path) -> None:
        engine = ReplayEngine(tmp_path)
        engine.record(_task(), _result())
        with pytest.raises(CassetteMissing):
            engine.run(_task(inputs={"graphSlice": "sha256:" + "9" * 64}))

    def test_missing_cassette_is_explicit(self, tmp_path: Path) -> None:
        with pytest.raises(CassetteMissing, match="echo-skill"):
            ReplayEngine(tmp_path).run(_task())

    def test_recorded_cassette_is_readable_json(self, tmp_path: Path) -> None:
        engine = ReplayEngine(tmp_path)
        engine.record(_task(), _result())
        files = list(tmp_path.glob("*.json"))
        assert len(files) == 1
        payload = json.loads(files[0].read_text(encoding="utf-8"))
        assert payload["result"]["taskId"] == TASK_ID
        assert payload["task"]["skillId"] == "echo-skill"

    def test_replay_is_byte_stable(self, tmp_path: Path) -> None:
        engine = ReplayEngine(tmp_path)
        engine.record(_task(), _result())
        assert engine.run(_task()).contract_dump() == engine.run(_task()).contract_dump()


class TestBudget:
    def test_tracks_and_allows_within_limit(self) -> None:
        budget = TokenBudget(max_run_tokens=5000, max_task_tokens=1000)
        budget.check_task(_task())  # task declares exactly 1000
        budget.consume(_result(tokens=100))
        assert budget.spent == 200

    def test_task_over_per_task_cap_refused_before_dispatch(self) -> None:
        budget = TokenBudget(max_run_tokens=5000, max_task_tokens=500)
        with pytest.raises(BudgetExceeded, match="per-task cap"):
            budget.check_task(_task())  # declares 1000 > 500

    def test_run_budget_exhaustion_raises(self) -> None:
        budget = TokenBudget(max_run_tokens=300, max_task_tokens=500)
        budget.consume(_result(tokens=100))  # 200
        with pytest.raises(BudgetExceeded):
            budget.consume(_result(tokens=100))  # 400 > 300

    def test_task_limit_above_remaining_budget_raises_before_dispatch(self) -> None:
        budget = TokenBudget(max_run_tokens=100, max_task_tokens=500)
        with pytest.raises(BudgetExceeded):
            budget.check_task(_task())  # task may use 1000 > 100 remaining


class TestOutputValidation:
    def test_valid_output_passes(self) -> None:
        from codeatlas.agents.engine import validate_output

        finding = {
            "findingId": "F-0001",
            "category": "security",
            "discoveredBySkill": "reviewer-security",
            "skillVersion": "1.0.0",
            "severity": "high",
            "confidence": 0.8,
            "claim": "x",
            "location": {"path": "a.rs"},
            "evidence": [{"kind": "llm-inference", "producer": "reviewer-security"}],
        }
        assert validate_output({"findings": [finding]}, "findings.v1") == []

    def test_invalid_output_reports_errors(self) -> None:
        from codeatlas.agents.engine import validate_output

        errors = validate_output({"findings": [{"findingId": "nope"}]}, "findings.v1")
        assert errors
