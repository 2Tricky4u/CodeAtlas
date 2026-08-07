"""Contract models: Python bindings for schemas/*.json (the source of truth)."""

from __future__ import annotations

from codeatlas.models.adr_audit import AdrAudit
from codeatlas.models.agent import AgentResult, AgentTask
from codeatlas.models.api import ApiChange, ApiSurface
from codeatlas.models.architecture import Architecture
from codeatlas.models.base import ContractModel
from codeatlas.models.code_answer import CodeAnswer
from codeatlas.models.coverage import ReviewCoverage
from codeatlas.models.diff import GraphDiff
from codeatlas.models.explanation import ChangeExplanation
from codeatlas.models.findings import Finding
from codeatlas.models.graph import ProjectGraph
from codeatlas.models.impact import ChangeImpact
from codeatlas.models.intent import IntentPackage
from codeatlas.models.manifest import RunManifest, SourceLock
from codeatlas.models.overview import ProjectOverview
from codeatlas.models.project_explanation import ProjectExplanation
from codeatlas.models.protocol import ProtocolModel
from codeatlas.models.receipts import ExtractorReceipt
from codeatlas.models.validation import ValidationResult
from codeatlas.models.views import GraphViews

# Schema file -> top-level contract model. The drift test iterates this mapping.
CONTRACT_MODELS: dict[str, type[ContractModel]] = {
    "project-graph.v1.json": ProjectGraph,
    "extractor-receipt.v1.json": ExtractorReceipt,
    "finding.v1.json": Finding,
    "validation-result.v1.json": ValidationResult,
    "intent.v1.json": IntentPackage,
    "protocol-model.v1.json": ProtocolModel,
    "agent-task.v1.json": AgentTask,
    "agent-result.v1.json": AgentResult,
    "run-manifest.v1.json": RunManifest,
    "adr-audit.v1.json": AdrAudit,
    "architecture.v1.json": Architecture,
    "code-answer.v1.json": CodeAnswer,
    "api-surface.v1.json": ApiSurface,
    "api-change.v1.json": ApiChange,
    "graph-diff.v1.json": GraphDiff,
    "change-impact.v1.json": ChangeImpact,
    "change-explanation.v1.json": ChangeExplanation,
    "project-explanation.v1.json": ProjectExplanation,
    "project-overview.v1.json": ProjectOverview,
    "graph-view.v1.json": GraphViews,
    "review-coverage.v1.json": ReviewCoverage,
}

__all__ = [
    "CONTRACT_MODELS",
    "AdrAudit",
    "AgentResult",
    "AgentTask",
    "ApiChange",
    "ApiSurface",
    "Architecture",
    "ChangeExplanation",
    "ChangeImpact",
    "CodeAnswer",
    "ContractModel",
    "ExtractorReceipt",
    "Finding",
    "GraphDiff",
    "GraphViews",
    "IntentPackage",
    "ProjectExplanation",
    "ProjectGraph",
    "ProjectOverview",
    "ProtocolModel",
    "RunManifest",
    "SourceLock",
    "ValidationResult",
]
