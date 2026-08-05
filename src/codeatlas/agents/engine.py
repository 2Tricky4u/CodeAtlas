"""Agent adapter boundary.

The pipeline dispatches typed AgentTasks and receives typed AgentResults; it
never imports a concrete engine. Output is JSON-Schema-validated at this
boundary, so an engine can only return data the contract allows.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from jsonschema import Draft202012Validator

from codeatlas.models.agent import AgentResult, AgentTask

_SCHEMA_DIR = Path(__file__).resolve().parents[3] / "schemas"


@dataclass(frozen=True, slots=True)
class EngineHealth:
    available: bool
    detail: str


class AgentEngine(Protocol):
    name: str

    def run(self, task: AgentTask) -> AgentResult: ...

    def health_check(self) -> EngineHealth: ...


@lru_cache(maxsize=32)
def _validator(schema_id: str) -> Draft202012Validator:
    """Validator for a schema id like `finding.v1` or the wrapper `findings.v1`."""
    if schema_id.startswith("findings."):
        # A reviewer returns {"findings": [<finding.v1>, ...]}.
        item = json.loads((_SCHEMA_DIR / "finding.v1.json").read_text(encoding="utf-8"))
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "additionalProperties": False,
            "required": ["findings"],
            "properties": {"findings": {"type": "array", "items": item}},
        }
    else:
        schema = json.loads((_SCHEMA_DIR / f"{schema_id}.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def validate_output(output: dict[str, Any] | None, schema_id: str) -> list[str]:
    """Return human-readable schema violations for an agent's output payload."""
    if output is None:
        return ["output is missing"]
    validator = _validator(schema_id)
    return [
        f"{list(e.absolute_path)}: {e.message}"
        for e in sorted(validator.iter_errors(output), key=str)
    ]
