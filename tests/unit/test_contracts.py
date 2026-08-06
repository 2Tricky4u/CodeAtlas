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
    "api-surface.v1.json",
    "api-change.v1.json",
    "graph-diff.v1.json",
    "change-impact.v1.json",
    "change-explanation.v1.json",
    "project-explanation.v1.json",
    "project-overview.v1.json",
    "architecture.v1.json",
    "adr-audit.v1.json",
    "code-answer.v1.json",
    "graph-view.v1.json",
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
    "schemaVersion": "1.0.0",
    "protocol": {
        "id": "kvstore-wire",
        "version": "1",
        "transport": "tcp",
        "framing": "length-prefixed JSON",
        "participants": [
            {"name": "client", "description": "", "evidence": {"path": "src/main.rs"}},
            {"name": "server", "description": "", "evidence": {"path": "src/proto.rs"}},
        ],
        "states": ["Idle", "AwaitingReply"],
        "messages": [
            {
                "name": "Get",
                "producer": "client",
                "consumer": "server",
                "schema": None,
                "evidence": {"path": "src/proto.rs", "startLine": 12, "endLine": 20},
            }
        ],
        "timeouts": [{"state": "AwaitingReply", "duration": "PT5S", "transition": "Idle"}],
        "evidence": [{"path": "src/proto.rs", "symbol": "handle_get"}],
    },
    "droppedElements": [
        {
            "kind": "message",
            "name": "Subscribe",
            "reason": "src/pubsub.rs does not exist at this revision",
        }
    ],
    "notes": [],
}

# The common case, and the one the skill is written to reach for.
PROTOCOL_NONE_EXAMPLE: dict[str, Any] = {
    "schemaVersion": "1.0.0",
    "protocol": None,
    "notes": ["this project is a batch tool; nothing is exchanged with another party"],
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

API_SURFACE_EXAMPLE: dict[str, Any] = {
    "schemaVersion": "1.0.0",
    "revision": "a" * 40,
    "tool": "cargo-public-api 0.52.0 (rustdoc: rustc 1.99.0-nightly)",
    "packages": [
        {
            "name": "kvstore",
            "version": "0.1.0",
            "manifestPath": "kvstore/Cargo.toml",
            "items": [
                "pub fn kvstore::cache::Cache::evict_oldest(&mut self, usize)",
                "pub struct kvstore::cache::Cache",
            ],
        }
    ],
    "skipped": [{"name": "kvstore-cli", "reason": "no library target to expose an API"}],
}

API_CHANGE_EXAMPLE: dict[str, Any] = {
    "schemaVersion": "1.0.0",
    "baseRevision": "a" * 40,
    "headRevision": "b" * 40,
    "packages": [
        {
            "name": "kvstore",
            "added": ["pub fn kvstore::cache::Cache::evict(&mut self, usize) -> usize"],
            "removed": ["pub fn kvstore::cache::Cache::evict_oldest(&mut self, usize)"],
            "unchangedCount": 112,
            "requiredBump": "major",
            "lints": [
                {
                    "id": "inherent_method_missing",
                    "level": "major",
                    "summary": "inherent method is no longer available",
                    "locations": ["kvstore/src/cache.rs:41"],
                }
            ],
        }
    ],
    "skipped": [{"name": "kvstore-cli", "reason": "at base: no library target to expose an API"}],
    "tools": {"cargoPublicApi": "0.52.0", "cargoSemverChecks": "0.44.0"},
}

GRAPH_DIFF_EXAMPLE: dict[str, Any] = {
    "schemaVersion": "1.0.0",
    "baseRevision": "a" * 40,
    "headRevision": "b" * 40,
    "nodes": {
        "added": [
            {
                "stableKey": "sym:scip/rust-analyzer cargo kvstore cache/Cache#evict().",
                "id": "sym:scip/rust-analyzer cargo kvstore 0.1.0 cache/Cache#evict().",
                "kind": "function",
                "label": "evict",
                "path": "kvstore/src/cache.rs",
                "startLine": 41,
                "endLine": 55,
            }
        ],
        "removed": [
            {
                "stableKey": "sym:scip/rust-analyzer cargo kvstore cache/Cache#evict_oldest().",
                "id": "sym:scip/rust-analyzer cargo kvstore 0.1.0 cache/Cache#evict_oldest().",
                "kind": "function",
                "label": "evict_oldest",
                "path": "kvstore/src/cache.rs",
                "startLine": 41,
                "endLine": 48,
            }
        ],
        "moved": [
            {
                "stableKey": "sym:scip/rust-analyzer cargo kvstore cache/Cache#",
                "kind": "type",
                "label": "Cache",
                "beforePath": "kvstore/src/cache.rs",
                "afterPath": "kvstore/src/eviction.rs",
            }
        ],
        "touched": [],
    },
    "edges": {
        "added": [],
        "removed": [
            {
                "id": "edge:3d1c2a9f8b7e6d5c4a3b2c1d",
                "kind": "calls",
                "sourceKey": "sym:scip/rust-analyzer cargo kvstore cache/Cache#put().",
                "targetKey": "sym:scip/rust-analyzer cargo kvstore cache/Cache#evict_oldest().",
                "sourceLabel": "put",
                "targetLabel": "evict_oldest",
                "sourcePath": "kvstore/src/cache.rs",
                "targetPath": "kvstore/src/cache.rs",
            }
        ],
    },
    "packageVersionChanges": [{"name": "kvstore", "before": "0.1.0", "after": "0.2.0"}],
    "likelyRenamed": [
        {
            "beforeKey": "sym:scip/rust-analyzer cargo kvstore cache/Cache#evict_oldest().",
            "afterKey": "sym:scip/rust-analyzer cargo kvstore cache/Cache#evict().",
            "beforeLabel": "evict_oldest",
            "afterLabel": "evict",
            "path": "kvstore/src/cache.rs",
            "confidence": 0.75,
            "basis": "same file and overlapping source range; name similarity 0.71",
        }
    ],
    "unnormalizedIdentities": 0,
    "summary": {
        "nodesAdded": 1,
        "nodesRemoved": 1,
        "nodesMoved": 1,
        "nodesTouched": 0,
        "edgesAdded": 0,
        "edgesRemoved": 1,
    },
}

CHANGE_IMPACT_EXAMPLE: dict[str, Any] = {
    "schemaVersion": "1.0.0",
    "baseRevision": "a" * 40,
    "headRevision": "b" * 40,
    "hops": 1,
    "maxHops": 2,
    "seeds": [
        {
            "stableKey": "sym:scip/rust-analyzer cargo kvstore cache/Cache#evict_oldest().",
            "label": "evict_oldest",
            "path": "kvstore/src/cache.rs",
            "reason": "removed",
        }
    ],
    "impacted": [
        {
            "stableKey": "sym:scip/rust-analyzer cargo kvstore cache/Cache#put().",
            "label": "put",
            "kind": "function",
            "path": "kvstore/src/cache.rs",
            "startLine": 23,
            "endLine": 30,
            "hop": 1,
            "rank": "public-api",
            "claimStrength": "referred-to-removed-symbol",
            "viaSeed": "sym:scip/rust-analyzer cargo kvstore cache/Cache#evict_oldest().",
            "viaEdgeKind": "calls",
        }
    ],
    "totalImpacted": 1,
    "suppressed": 0,
    "basis": "bounded reverse reachability over calls and imports",
    "caveat": "Static change-impact analysis reports possibilities, not certainties.",
    "notes": [],
}

IMPACT_KEY = "sym:scip/rust-analyzer cargo kvstore api/handle_request()."

CHANGE_EXPLANATION_EXAMPLE: dict[str, Any] = {
    "schemaVersion": "1.0.0",
    "summary": "Replaces Cache::evict_oldest with Cache::evict and adds Cache::capacity.",
    "sections": [
        {
            "id": "before",
            "title": "What it did before",
            "claims": [
                {
                    "text": "evict_oldest looped 0..=n, removing one entry more than asked for.",
                    "citations": [
                        {
                            "kind": "source",
                            "revision": "base",
                            "path": "kvstore/src/cache.rs",
                            "startLine": 41,
                            "endLine": 48,
                        }
                    ],
                }
            ],
        },
        {
            "id": "impact",
            "title": "What else could be affected",
            "claims": [
                {
                    "text": "handle_request reaches this code and could be affected.",
                    "citations": [
                        {
                            "kind": "impact",
                            "stableKey": IMPACT_KEY,
                        }
                    ],
                }
            ],
        },
    ],
    "sequenceDiagram": None,
    "droppedClaims": [
        {
            "sectionId": "risks",
            "text": "The retry loop was removed.",
            "reason": "kvstore/src/scheduler.rs does not exist at the head revision",
        }
    ],
    "notes": [],
}

PROJECT_EXPLANATION_EXAMPLE: dict[str, Any] = {
    "schemaVersion": "1.0.0",
    "summary": "kvstore is a small in-process key-value store with an HTTP front end.",
    "sections": [
        {
            "id": "entry",
            "title": "Where to start",
            "claims": [
                {
                    "text": "Execution starts in the binary root, which wires store to API.",
                    "citations": [
                        {"kind": "source", "path": "kvstore/src/main.rs", "startLine": 1},
                        {"kind": "module", "key": "kvstore/src/main.rs"},
                    ],
                }
            ],
        },
        {
            "id": "caution",
            "title": "What will surprise you",
            "claims": [
                {
                    "text": "api and storage depend on each other, so neither can be read alone.",
                    "citations": [
                        {
                            "kind": "cycle",
                            "members": ["kvstore/src/api.rs", "kvstore/src/storage.rs"],
                        }
                    ],
                }
            ],
        },
    ],
    "droppedClaims": [
        {
            "sectionId": "hotspots",
            "text": "The scheduler is the busiest module.",
            "reason": "kvstore/src/scheduler.rs is not a module this overview measured",
        }
    ],
    "notes": [],
}

CODE_ANSWER_EXAMPLE: dict[str, Any] = {
    "schemaVersion": "1.0.0",
    "question": "what does eviction actually remove?",
    "scope": "kvstore/src/cache.rs",
    "answer": "One entry more than asked for: the loop is inclusive.",
    "claims": [
        {
            "text": "evict_oldest loops 0..=n, removing n+1 entries.",
            "citations": [
                {"kind": "source", "path": "kvstore/src/cache.rs", "startLine": 41, "endLine": 48}
            ],
        }
    ],
    "refused": None,
    "droppedClaims": [
        {
            "sectionId": "answer",
            "text": "The scheduler compensates for this.",
            "reason": "kvstore/src/scheduler.rs does not exist at this revision",
        }
    ],
    "notes": [],
}

ADR_AUDIT_EXAMPLE: dict[str, Any] = {
    "schemaVersion": "1.0.0",
    "revision": "a" * 40,
    "decisions": [
        {
            "adr": "docs/adr/adr-0001-layering.md",
            "label": "ADR-0001",
            "number": 1,
            "title": "Layering",
            "status": "accepted",
            "date": "2026-01-15",
            "supersededBy": None,
            "assertion": "Dependencies flow downward through api -> cache -> storage.",
            "auditResult": "probable-drift",
            "confidence": 0.85,
            "requiresHumanDecision": True,
            "affectedNodes": ["file:kvstore/src/storage.rs"],
            "evidence": [{"edge": "edge:70615f911899", "from": "storage", "to": "api"}],
            "detail": "storage.rs imports crate::api::Response, which the decision prohibits.",
        }
    ],
    "notes": ["1 decision(s) show probable drift from the code"],
}

ARCHITECTURE_EXAMPLE: dict[str, Any] = {
    "schemaVersion": "1.0.0",
    "repositoryId": "local/kvstore",
    "revision": "a" * 40,
    "systemName": "kvstore",
    "containers": [
        {
            "key": "kvstore",
            "name": "kvstore",
            "description": "kvstore 0.1.0",
            "technology": "rust",
            "level": 0,
            "fanIn": 1,
            "fanOut": 0,
            "evidenceNodeId": "pkg:cargo/kvstore@0.1.0",
            "path": "kvstore/Cargo.toml",
        },
        {
            "key": "kvstore_cli",
            "name": "kvstore-cli",
            "description": "kvstore-cli 0.1.0",
            "technology": "rust",
            "level": 1,
            "fanIn": 0,
            "fanOut": 1,
            "evidenceNodeId": "pkg:cargo/kvstore-cli@0.1.0",
            "path": "kvstore-cli/Cargo.toml",
        },
    ],
    "relationships": [
        {
            "sourceKey": "kvstore_cli",
            "targetKey": "kvstore",
            "description": "depends-on",
            "evidenceEdgeId": "edge:9f2c1b7a4d8e",
        }
    ],
    "readability": {
        "passed": True,
        "checks": [{"name": "node-budget", "passed": True, "value": 2, "limit": 25}],
    },
    "notes": [],
}

PROJECT_OVERVIEW_EXAMPLE: dict[str, Any] = {
    "schemaVersion": "1.0.0",
    "repositoryId": "local/kvstore",
    "revision": "a" * 40,
    "packages": [
        {
            "name": "kvstore",
            "version": "0.1.0",
            "manifestPath": "kvstore/Cargo.toml",
            "fileCount": 4,
            "symbolCount": 21,
        }
    ],
    "modules": [
        {
            "key": "file:kvstore/src/storage.rs",
            "path": "kvstore/src/storage.rs",
            "package": "kvstore",
            "fanIn": 2,
            "fanOut": 0,
            "level": 0,
            "symbolCount": 6,
        }
    ],
    "levels": [{"level": 0, "modules": ["kvstore/src/storage.rs"]}],
    "cycles": [
        {
            "members": ["kvstore/src/a.rs", "kvstore/src/b.rs"],
            "edges": [{"from": "kvstore/src/a.rs", "to": "kvstore/src/b.rs"}],
        }
    ],
    "hubs": {
        "dependedOn": [
            {
                "key": "file:kvstore/src/storage.rs",
                "path": "kvstore/src/storage.rs",
                "package": "kvstore",
                "fanIn": 2,
                "fanOut": 0,
                "level": 0,
                "symbolCount": 6,
            }
        ],
        "dependsOn": [],
    },
    "orphans": [],
    "entryPoints": [
        {
            "key": "file:kvstore/src/lib.rs",
            "path": "kvstore/src/lib.rs",
            "reason": "library root (lib.rs)",
        }
    ],
    "startHere": [
        {
            "key": "file:kvstore/src/lib.rs",
            "path": "kvstore/src/lib.rs",
            "reason": "library root (lib.rs)",
        }
    ],
    "counts": {"packages": 1, "files": 4, "symbols": 21, "edges": 30},
    "notes": [],
}

GRAPH_VIEW_EXAMPLE: dict[str, Any] = {
    "schemaVersion": "1.0.0",
    "repositoryId": "local/kvstore",
    "revision": "a" * 40,
    "views": [
        {
            "id": "packages",
            "kind": "package-dependencies",
            "title": "Packages",
            "layout": "elk-layered",
            "nodes": [{"id": "pkg:kvstore", "label": "kvstore", "kind": "package", "fanIn": 1}],
            "edges": [
                {
                    "id": "pkgedge:cli->kvstore",
                    "source": "pkg:kvstore-cli",
                    "target": "pkg:kvstore",
                    "kind": "depends-on",
                    "weight": 4,
                }
            ],
            "suppressedEdges": 0,
            "readability": {
                "passed": True,
                "checks": [
                    {"name": "node-budget", "passed": True, "value": 2, "limit": 25},
                    {"name": "edge-density", "passed": True, "value": 0.5, "limit": 3},
                    {"name": "max-degree", "passed": True, "value": 1, "limit": 10},
                ],
            },
            "notes": ["open here: one box per package"],
        }
    ],
    "refused": [
        {
            "id": "modules:kvstore",
            "kind": "levelized-modules",
            "failedCheck": "node-budget",
            "reason": "node-budget 41 exceeds the limit of 25; this would be a hairball",
        }
    ],
    "notes": [],
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
    "api-surface.v1.json": API_SURFACE_EXAMPLE,
    "api-change.v1.json": API_CHANGE_EXAMPLE,
    "graph-diff.v1.json": GRAPH_DIFF_EXAMPLE,
    "change-impact.v1.json": CHANGE_IMPACT_EXAMPLE,
    "change-explanation.v1.json": CHANGE_EXPLANATION_EXAMPLE,
    "project-explanation.v1.json": PROJECT_EXPLANATION_EXAMPLE,
    "project-overview.v1.json": PROJECT_OVERVIEW_EXAMPLE,
    "architecture.v1.json": ARCHITECTURE_EXAMPLE,
    "adr-audit.v1.json": ADR_AUDIT_EXAMPLE,
    "code-answer.v1.json": CODE_ANSWER_EXAMPLE,
    "graph-view.v1.json": GRAPH_VIEW_EXAMPLE,
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


def test_a_project_with_no_protocol_is_expressible() -> None:
    """The common case, and the one the schema exists to allow.

    Before this, `protocol` was required — so a batch tool could only be
    described by inventing a protocol for it, which is precisely the artifact
    this pipeline refuses to produce.
    """
    validator = Draft202012Validator(_load_schema("protocol-model.v1.json"))
    assert not sorted(validator.iter_errors(PROTOCOL_NONE_EXAMPLE), key=str)

    model = CONTRACT_MODELS["protocol-model.v1.json"].model_validate(PROTOCOL_NONE_EXAMPLE)
    assert not sorted(validator.iter_errors(model.contract_dump()), key=str)


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
