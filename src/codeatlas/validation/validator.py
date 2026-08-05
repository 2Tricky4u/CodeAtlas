"""Finding validation: deterministic pre-pass, then adversarial review.

Order is deliberate. Cheap, certain rules run first (dedup, dead locations,
auto-attached tool evidence). Only survivors reach an agent, and that agent gets
the claim without its author's reasoning — a fresh context is the point.
Afterwards the pipeline recomputes publication eligibility from evidence, so the
validator's own opinion cannot promote a finding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import Engine

from codeatlas.agents.budget import TokenBudget
from codeatlas.agents.dispatch import RunnableEngine, build_task, dispatch
from codeatlas.agents.registry import SkillRegistry
from codeatlas.artifacts.store import ArtifactStore
from codeatlas.core.logging import get_logger
from codeatlas.models.findings import Finding
from codeatlas.models.validation import ValidationEvidence, ValidationResult
from codeatlas.validation.rules import (
    deduplicate,
    is_publication_eligible,
    location_exists,
)
from codeatlas.verify.parse import VerificationIndex

log = get_logger("codeatlas.validation")

SKILL_ID = "finding-validator"


@dataclass(slots=True)
class ValidationOutcome:
    results: dict[str, ValidationResult] = field(default_factory=dict)
    publishable: list[str] = field(default_factory=list)

    def status_of(self, finding_id: str) -> str:
        result = self.results.get(finding_id)
        return result.status if result else "unresolved"


def _auto_evidence(finding: Finding, index: VerificationIndex) -> list[ValidationEvidence]:
    """Tool output at the finding's location, attached without asking an agent."""
    evidence: list[ValidationEvidence] = []
    hits = index.diagnostics_near(
        finding.location.path,
        finding.location.start_line or 0,
        finding.location.end_line or finding.location.start_line or 0,
    )
    for diagnostic in hits:
        evidence.append(
            ValidationEvidence(
                kind="static-analysis" if diagnostic.level == "warning" else "compiler",
                command=f"{diagnostic.code}: {diagnostic.message}"[:400],
            )
        )
    return evidence


def _rejected(finding: Finding, reason: str, checked: list[str]) -> ValidationResult:
    return ValidationResult(
        finding_id=finding.finding_id,
        status="rejected",
        severity=finding.severity,
        confidence=1.0,
        introduced_by_change=False,
        location=finding.location,
        claim=finding.claim,
        evidence=[],
        counter_evidence_checked=checked,
        publication_eligible=False,
        reason=reason,
    )


def _duplicate(finding: Finding, canonical_id: str) -> ValidationResult:
    return ValidationResult(
        finding_id=finding.finding_id,
        status="duplicate",
        severity=finding.severity,
        confidence=1.0,
        introduced_by_change=False,
        duplicate_of=canonical_id,
        location=finding.location,
        claim=finding.claim,
        evidence=[],
        counter_evidence_checked=[f"same defect location as {canonical_id}"],
        publication_eligible=False,
        reason=f"restates {canonical_id}",
    )


def validate_findings(
    findings: list[Finding],
    index: VerificationIndex,
    file_lengths: dict[str, int],
    engine: RunnableEngine,
    registry: SkillRegistry,
    run_id: str,
    revision_sha: str,
    checkout: Path,
    db_engine: Engine,
    cas: ArtifactStore,
    budget: TokenBudget | None = None,
) -> ValidationOutcome:
    """Every candidate leaves this stage with a terminal status."""
    outcome = ValidationOutcome()

    for group in deduplicate(findings):
        for duplicate in group.duplicates:
            outcome.results[duplicate.finding_id] = _duplicate(
                duplicate, group.canonical.finding_id
            )

        finding = group.canonical
        if not location_exists(finding.location, file_lengths):
            outcome.results[finding.finding_id] = _rejected(
                finding,
                "the cited location does not exist at the analyzed revision",
                ["file table at the analyzed revision"],
            )
            continue

        auto = _auto_evidence(finding, index)
        payload = {
            "finding": finding.contract_dump(),
            "verification": {
                "diagnosticsAtLocation": [e.contract_dump() for e in auto],
                "failingTests": [t.name for t in index.failing_tests()],
                "summary": index.summary(),
            },
        }
        task = build_task(
            skill=registry.get(SKILL_ID),
            run_id=run_id,
            revision_sha=revision_sha,
            checkout=checkout,
            inputs={"candidate": cas.put_json(payload)},
        )
        try:
            result = dispatch(
                engine=engine,
                registry=registry,
                skill_id=SKILL_ID,
                task=task,
                db_engine=db_engine,
                cas=cas,
                budget=budget,
            )
        except Exception as exc:
            log.error("validator.dispatch_failed", finding=finding.finding_id, error=str(exc))
            outcome.results[finding.finding_id] = _unresolved(finding, str(exc)[:300])
            continue

        if result.status != "succeeded" or result.output is None:
            outcome.results[finding.finding_id] = _unresolved(
                finding, f"validator {result.status}: {result.error or 'no output'}"
            )
            continue

        validated = ValidationResult.model_validate(result.output)
        # The validator may only rule on the finding it was given.
        if validated.finding_id != finding.finding_id:
            validated = validated.model_copy(update={"finding_id": finding.finding_id})
        # Auto-attached tool evidence is ours, not the agent's, and is kept.
        merged_evidence = [*auto, *validated.evidence]
        eligible, reason = is_publication_eligible(
            validated.model_copy(update={"evidence": merged_evidence})
        )
        validated = validated.model_copy(
            update={
                "evidence": merged_evidence,
                "publication_eligible": eligible,
                "reason": validated.reason or reason,
            }
        )
        outcome.results[finding.finding_id] = validated
        if eligible:
            outcome.publishable.append(finding.finding_id)

    # Gate: nothing may leave this stage without a terminal status.
    missing = [f.finding_id for f in findings if f.finding_id not in outcome.results]
    for finding_id in missing:
        finding = next(f for f in findings if f.finding_id == finding_id)
        outcome.results[finding_id] = _unresolved(finding, "not reached by validation")

    log.info(
        "validation.completed",
        run_id=run_id,
        total=len(findings),
        publishable=len(outcome.publishable),
        statuses={
            status: sum(1 for r in outcome.results.values() if r.status == status)
            for status in ("validated", "rejected", "duplicate", "unresolved")
        },
    )
    return outcome


def _unresolved(finding: Finding, reason: str) -> ValidationResult:
    return ValidationResult(
        finding_id=finding.finding_id,
        status="unresolved",
        severity=finding.severity,
        confidence=0.0,
        introduced_by_change=False,
        location=finding.location,
        claim=finding.claim,
        evidence=[],
        counter_evidence_checked=["validation did not complete"],
        publication_eligible=False,
        reason=reason,
    )
