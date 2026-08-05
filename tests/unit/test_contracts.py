"""Contract tests: schemas/*.json are the source of truth; Pydantic models must conform.

Two-directional check on golden examples:
1. every example validates against its JSON Schema (Draft 2020-12, via `jsonschema`);
2. every example parses into its Pydantic model, and the model's canonical dump
   re-validates against the same JSON Schema (no drift in either direction).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from codeatlas.models import CONTRACT_MODELS

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO_ROOT / "schemas"

EXPECTED_SCHEMAS = {
    "project-graph.v1.json",
    "extractor-receipt.v1.json",
    "finding.v1.json",
    "validation-result.v1.json",
    "intent.v1.json",
    "protocol-model.v1.json",
    "agent-task.v1.json",
    "agent-result.v1.json",
    "run-manifest.v1.json",
}


def _load_schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))  # type: ignore[no-any-return]


# --- golden examples (minimal but structurally complete) --------------------

GRAPH_EXAMPLE: dict[str, Any] = {
    "schemaVersion": "1.0.0",
    "repository": {"id": "local/kvstore", "url": "https://example.org/kvstore.git"},
    "revision": {"head": "a" * 40},
    "nodes": [
        {
            "id": "pkg:cargo/kvstore@0.1.0",
            "kind": "package",
            "label": "kvstore 0.1.0",
            "language": "rust",
            "evidence": [
                {"kind": "build-system", "producer": "cargo", "producerVersion": "1.94.1"}
            ],
        },
        {
            "id": "file:src/lib.rs",
            "kind": "file",
            "label": "src/lib.rs",
            "location": {"path": "src/lib.rs"},
            "evidence": [{"kind": "language-server", "producer": "rust-analyzer"}],
        },
    ],
    "edges": [
        {
            "id": "edge:3d1c2a",
            "source": "pkg:cargo/kvstore@0.1.0",
            "target": "file:src/lib.rs",
            "kind": "contains",
            "evidence": [{"kind": "build-system", "producer": "cargo", "confidence": 1.0}],
        }
    ],
}

RECEIPT_EXAMPLE: dict[str, Any] = {
    "extractor": "cargo-metadata",
    "extractorVersion": "cargo 1.94.1",
    "revision": "a" * 40,
    "configuration": {"command": "cargo metadata --format-version 1 --locked"},
    "startedAt": "2026-08-05T12:00:00Z",
    "completedAt": "2026-08-05T12:00:03Z",
    "exitCode": 0,
    "stdoutSha256": "sha256:" + "0" * 64,
    "stderrSha256": "sha256:" + "0" * 64,
}

FINDING_EXAMPLE: dict[str, Any] = {
    "findingId": "F-0001",
    "category": "security",
    "discoveredBySkill": "reviewer-security",
    "skillVersion": "1.0.0",
    "severity": "high",
    "confidence": 0.85,
    "claim": "join() with untrusted key allows path traversal out of the store root.",
    "location": {"path": "src/store.rs", "startLine": 41, "endLine": 55},
    "evidence": [
        {
            "kind": "llm-inference",
            "producer": "reviewer-security",
            "confidence": 0.85,
        }
    ],
    "proposedReproduction": 'store.get("../../secret") escapes the root',
}

VALIDATION_EXAMPLE: dict[str, Any] = {
    "findingId": "F-0001",
    "status": "validated",
    "severity": "high",
    "confidence": 0.96,
    "introducedByChange": True,
    "location": {"path": "src/store.rs", "startLine": 41, "endLine": 55},
    "claim": "join() with untrusted key allows path traversal out of the store root.",
    "evidence": [
        {
            "kind": "test",
            "command": "cargo test path_traversal_blocked",
            "exitCode": 101,
            "artifact": "sha256:" + "1" * 64,
        }
    ],
    "counterEvidenceChecked": ["input sanitization at caller", "canonicalize() before use"],
    "publicationEligible": True,
}

INTENT_EXAMPLE: dict[str, Any] = {
    "schemaVersion": "1.0.0",
    "requirements": [
        {
            "id": "REQ-001",
            "sourceKind": "adr",
            "sourceRef": "docs/adr/adr-0002.md",
            "text": "Storage layer must not depend on the API layer.",
            "acceptanceCriteria": ["no storage->api import edge in the project graph"],
        },
        {
            "id": "REQ-002",
            "sourceKind": "inferred",
            "sourceRef": None,
            "text": "Keys are untrusted input.",
            "acceptanceCriteria": [],
        },
    ],
    "nonGoals": ["performance tuning"],
    "compatibilityObligations": [],
    "unresolvedQuestions": ["is eviction order documented anywhere?"],
}

PROTOCOL_EXAMPLE: dict[str, Any] = {
    "protocol": {
        "id": "kvstore-wire",
        "version": "1",
        "transport": "tcp",
        "framing": "length-prefixed JSON",
        "participants": ["client", "server"],
        "states": ["Idle", "AwaitingReply"],
        "messages": [{"name": "Get", "producer": "client", "consumer": "server", "schema": None}],
        "timeouts": [{"state": "AwaitingReply", "duration": "PT5S", "transition": "Idle"}],
        "evidence": [{"path": "src/proto.rs", "symbol": "handle_get"}],
    }
}

AGENT_TASK_EXAMPLE: dict[str, Any] = {
    "taskId": "01J4QDGJ4W8Z9X7C5V3B2N1M0K",
    "runId": "01J4QDGJ4W8Z9X7C5V3B2N1M0A",
    "skillId": "reviewer-security",
    "skillVersion": "1.0.0",
    "skillContentSha256": "sha256:" + "2" * 64,
    "revisionSha": "a" * 40,
    "workspace": {"checkoutPath": "var/repos/kvstore/worktrees/aaaa", "mountMode": "ro"},
    "inputs": {"graphSlice": "sha256:" + "3" * 64},
    "permissions": {"allowedCommands": ["rg", "git show"], "network": False, "writePaths": []},
    "outputSchemaId": "finding.v1",
    "limits": {"timeoutS": 600, "maxTokens": 200000, "maxIterations": 30},
}

AGENT_RESULT_EXAMPLE: dict[str, Any] = {
    "taskId": "01J4QDGJ4W8Z9X7C5V3B2N1M0K",
    "status": "succeeded",
    "output": {"findings": []},
    "commandReceipts": [{"command": "rg -n unsafe src/", "exitCode": 1, "durationMs": 40}],
    "usage": {
        "promptTokens": 1200,
        "completionTokens": 300,
        "costUsd": None,
        "wallMs": 5000,
        "modelId": "claude-fable-5",
    },
    "transcriptRef": "sha256:" + "4" * 64,
    "error": None,
}

MANIFEST_EXAMPLE: dict[str, Any] = {
    "schemaVersion": "1.0.0",
    "runId": "01J4QDGJ4W8Z9X7C5V3B2N1M0A",
    "kind": "repository",
    "sourceLock": {
        "repositoryId": "local/kvstore",
        "remoteUrl": None,
        "headSha": "a" * 40,
        "baseSha": None,
        "mergeBaseSha": None,
        "changedPaths": [],
        "generatedPaths": [],
    },
    "toolchain": {"cargo": "1.94.1", "rust-analyzer": "1.94.0"},
    "skillRegistrySha256": "sha256:" + "5" * 64,
    "configSha256": "sha256:" + "6" * 64,
    "modelIds": [],
    "cassetteIds": [],
    "inputs": {},
    "outputs": {"projectGraph": "sha256:" + "7" * 64},
    "cost": {"totalPromptTokens": 0, "totalCompletionTokens": 0, "totalCostUsd": None},
}

EXAMPLES: dict[str, dict[str, Any]] = {
    "project-graph.v1.json": GRAPH_EXAMPLE,
    "extractor-receipt.v1.json": RECEIPT_EXAMPLE,
    "finding.v1.json": FINDING_EXAMPLE,
    "validation-result.v1.json": VALIDATION_EXAMPLE,
    "intent.v1.json": INTENT_EXAMPLE,
    "protocol-model.v1.json": PROTOCOL_EXAMPLE,
    "agent-task.v1.json": AGENT_TASK_EXAMPLE,
    "agent-result.v1.json": AGENT_RESULT_EXAMPLE,
    "run-manifest.v1.json": MANIFEST_EXAMPLE,
}


# --- tests ------------------------------------------------------------------


def test_all_expected_schema_files_exist() -> None:
    present = {p.name for p in SCHEMA_DIR.glob("*.json")}
    assert present >= EXPECTED_SCHEMAS


@pytest.mark.parametrize("name", sorted(EXPECTED_SCHEMAS))
def test_schema_is_valid_draft_2020_12(name: str) -> None:
    schema = _load_schema(name)
    Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"].endswith(name)


@pytest.mark.parametrize("name", sorted(EXPECTED_SCHEMAS))
def test_example_validates_against_schema(name: str) -> None:
    validator = Draft202012Validator(_load_schema(name))
    errors = sorted(validator.iter_errors(EXAMPLES[name]), key=str)
    assert not errors, "\n".join(e.message for e in errors)


@pytest.mark.parametrize("name", sorted(EXPECTED_SCHEMAS))
def test_model_roundtrip_revalidates_against_schema(name: str) -> None:
    model_cls = CONTRACT_MODELS[name]
    instance = model_cls.model_validate(EXAMPLES[name])
    dumped = instance.contract_dump()
    validator = Draft202012Validator(_load_schema(name))
    errors = sorted(validator.iter_errors(dumped), key=str)
    assert not errors, "\n".join(e.message for e in errors)


def test_models_reject_unknown_fields() -> None:
    from pydantic import ValidationError

    model_cls = CONTRACT_MODELS["extractor-receipt.v1.json"]
    bad = dict(RECEIPT_EXAMPLE, sneaky="x")
    with pytest.raises(ValidationError):
        model_cls.model_validate(bad)


def test_graph_model_rejects_bad_sha_and_empty_evidence() -> None:
    from pydantic import ValidationError

    model_cls = CONTRACT_MODELS["project-graph.v1.json"]
    bad_sha = json.loads(json.dumps(GRAPH_EXAMPLE))
    bad_sha["revision"]["head"] = "not-a-sha"
    with pytest.raises(ValidationError):
        model_cls.model_validate(bad_sha)

    no_evidence = json.loads(json.dumps(GRAPH_EXAMPLE))
    no_evidence["nodes"][0]["evidence"] = []
    with pytest.raises(ValidationError):
        model_cls.model_validate(no_evidence)
