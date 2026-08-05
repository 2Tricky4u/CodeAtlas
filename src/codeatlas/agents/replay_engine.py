"""Record/replay engine: deterministic agent results for CI and pipeline tests.

Cassettes are keyed by (skill_id, skill_version, canonical hash of the task's
semantic inputs). Bumping a skill version deliberately invalidates its cassettes
— a changed instruction set must be re-recorded and reviewed, never silently
replayed.
"""

from __future__ import annotations

import json
from pathlib import Path

from codeatlas.core.canonical import canonical_json, canonical_sha256
from codeatlas.models.agent import AgentResult, AgentTask


class CassetteMissing(RuntimeError):
    """No recorded result exists for this task."""


def cassette_key(task: AgentTask) -> str:
    payload = {
        "skillId": task.skill_id,
        "skillVersion": task.skill_version,
        "skillContentSha256": task.skill_content_sha256,
        "outputSchemaId": task.output_schema_id,
        "inputs": task.inputs,
        "revisionSha": task.revision_sha,
    }
    digest = canonical_sha256(payload).removeprefix("sha256:")
    return f"{task.skill_id}-{task.skill_version}-{digest[:16]}"


class ReplayEngine:
    name = "replay"

    def __init__(self, cassette_dir: Path) -> None:
        self.cassette_dir = cassette_dir
        self.cassette_dir.mkdir(parents=True, exist_ok=True)

    def health_check(self):  # type: ignore[no-untyped-def]
        from codeatlas.agents.engine import EngineHealth

        return EngineHealth(available=True, detail=f"cassettes at {self.cassette_dir}")

    def _path(self, task: AgentTask) -> Path:
        return self.cassette_dir / f"{cassette_key(task)}.json"

    def record(self, task: AgentTask, result: AgentResult) -> None:
        payload = {"task": task.contract_dump(), "result": result.contract_dump()}
        self._path(task).write_bytes(canonical_json(payload))

    def run(self, task: AgentTask) -> AgentResult:
        path = self._path(task)
        if not path.exists():
            raise CassetteMissing(
                f"no cassette for skill {task.skill_id}@{task.skill_version} "
                f"(expected {path.name}); re-record with the live engine"
            )
        payload = json.loads(path.read_text(encoding="utf-8"))
        result = AgentResult.model_validate(payload["result"])
        # The cassette was recorded for a different task id; replay under the
        # current one so downstream persistence links correctly.
        return result.model_copy(update={"task_id": task.task_id})
