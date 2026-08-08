"""Attack-path receipts for validated security findings (roadmap 2.3).

A validated security finding says *that* a flaw is real; it does not say how an
attacker reaches it or what it costs them. This stage asks one more question of
the findings that earned it — the ones validation confirmed and marked
`security` — and attaches the answer to the finding's record.

Why only validated security findings: the receipt is expensive (one agent call
each) and only meaningful where an attacker is the actor. A rejected finding has
no path worth tracing, and a correctness bug's "attack path" is a category
error. The scope is deliberately narrow in v1; widening it to rejected
candidates is a cost decision left for later.

Failure is never fatal: a finding keeps its verdict whether or not its receipt
was produced. The receipt enriches; it does not gate.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine

from codeatlas.agents.budget import TokenBudget
from codeatlas.agents.dispatch import RunnableEngine, build_task, dispatch_with_retry
from codeatlas.agents.registry import SkillRegistry
from codeatlas.artifacts.store import ArtifactStore
from codeatlas.core.logging import get_logger
from codeatlas.models.agent import AgentTask
from codeatlas.models.attack_path import AttackPath
from codeatlas.models.findings import Finding
from codeatlas.validation.validator import ValidationOutcome

log = get_logger("codeatlas.validation.attack_path")

SKILL_ID = "attack-path-analyst"


def eligible_findings(findings: list[Finding], outcome: ValidationOutcome) -> list[Finding]:
    """The validated, security-category findings — and only those."""
    return [
        f
        for f in findings
        if f.category == "security"
        and (result := outcome.results.get(f.finding_id)) is not None
        and result.status == "validated"
    ]


def analyze_attack_paths(
    findings: list[Finding],
    outcome: ValidationOutcome,
    engine: RunnableEngine,
    registry: SkillRegistry,
    run_id: str,
    revision_sha: str,
    checkout: Path,
    db_engine: Engine,
    cas: ArtifactStore,
    budget: TokenBudget | None = None,
) -> tuple[dict[str, dict[str, object]], list[str]]:
    """Trace an attack path for each validated security finding.

    Returns (paths by finding id, ids whose analysis did not complete). A
    finding absent from the first dict simply has no receipt — nothing about
    its verdict changes.
    """
    paths: dict[str, dict[str, object]] = {}
    failed: list[str] = []

    for finding in eligible_findings(findings, outcome):
        result = outcome.results[finding.finding_id]
        candidate_sha = cas.put_json(
            {
                "finding": finding.contract_dump(),
                "validation": result.contract_dump(),
            }
        )

        def task_factory(candidate_sha: str = candidate_sha) -> AgentTask:
            return build_task(
                skill=registry.get(SKILL_ID),
                run_id=run_id,
                revision_sha=revision_sha,
                checkout=checkout,
                inputs={"candidate": candidate_sha},
            )

        try:
            agent_result = dispatch_with_retry(
                engine=engine,
                registry=registry,
                skill_id=SKILL_ID,
                task_factory=task_factory,
                db_engine=db_engine,
                cas=cas,
                budget=budget,
            )
        except Exception as exc:
            log.error("attack_path.dispatch_failed", finding=finding.finding_id, error=str(exc))
            failed.append(finding.finding_id)
            continue
        if agent_result.status != "succeeded" or agent_result.output is None:
            log.error(
                "attack_path.failed",
                finding=finding.finding_id,
                status=agent_result.status,
                error=agent_result.error,
            )
            failed.append(finding.finding_id)
            continue

        model = AttackPath.model_validate(agent_result.output)
        # The analyst may only speak about the finding it was handed.
        model = model.model_copy(update={"finding_id": finding.finding_id})
        paths[finding.finding_id] = model.contract_dump()

    if paths or failed:
        log.info("attack_path.completed", run_id=run_id, traced=len(paths), failed=len(failed))
    return paths, failed
