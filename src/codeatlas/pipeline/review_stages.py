"""The review half of the pipeline: intent, reviewers, verification, validation,
synthesis, diagrams, ADR audit, and the dry-run payload.

Each stage is a plain function over the dependency container so it can be tested
directly, then composed into the LangGraph in `graph.py`. They persist their own
evidence as they go: a stage that produced findings has rows to show for it, and
a stage that failed leaves the reason behind.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from codeatlas.adr.audit import LayeringRule, audit_layering
from codeatlas.adr.parser import parse_adr_directory
from codeatlas.artifacts.mermaid.gen import sequence_diagram, state_diagram
from codeatlas.artifacts.mermaid.validate import mmdc_path, render
from codeatlas.artifacts.structurizr.gen import generate_dsl, map_graph_to_c4
from codeatlas.artifacts.structurizr.validate import (
    cli_path,
    export_views,
    validate_workspace,
    write_dsl,
)
from codeatlas.core.logging import get_logger
from codeatlas.db import repositories as repo
from codeatlas.db.tables import FileRow, FindingRow
from codeatlas.models.findings import Finding
from codeatlas.models.graph import ProjectGraph
from codeatlas.models.intent import IntentPackage
from codeatlas.pipeline.deps import PipelineDeps
from codeatlas.publication.payload import build_payload
from codeatlas.review.intent_node import reconstruct_intent
from codeatlas.review.reviewers import (
    ReviewOutcome,
    build_reviewer_inputs,
    run_reviewers,
    slice_graph_for_review,
)
from codeatlas.review.scope import ChangedScope
from codeatlas.review.synthesis import ReviewReport, build_report
from codeatlas.validation.validator import ValidationOutcome, validate_findings
from codeatlas.verify.battery import run_battery

log = get_logger("codeatlas.pipeline.review")


@dataclass
class ReviewContext:
    """Accumulated review state, persisted as it is produced."""

    run_id: str
    revision_sha: str
    checkout: Path
    graph: ProjectGraph
    intent: IntentPackage | None = None
    findings: list[Finding] = field(default_factory=list)
    failed_skills: list[str] = field(default_factory=list)
    validation: ValidationOutcome | None = None
    report: ReviewReport | None = None
    artifacts: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def stage_intent(deps: PipelineDeps, ctx: ReviewContext) -> None:
    package, problems, sha = reconstruct_intent(
        engine=deps.agent_engine,  # type: ignore[arg-type]
        registry=deps.registry(),
        run_id=ctx.run_id,
        revision_sha=ctx.revision_sha,
        checkout=ctx.checkout,
        db_engine=deps.engine,
        cas=deps.cas,
        budget=deps.budget,
    )
    ctx.intent = package
    ctx.artifacts["intent"] = sha
    if problems:
        ctx.notes.append(f"{len(problems)} intent citation(s) downgraded to inference")


def stage_reviewers(deps: PipelineDeps, ctx: ReviewContext) -> None:
    source_paths = sorted(
        p.relative_to(ctx.checkout).as_posix()
        for p in ctx.checkout.rglob("*.rs")
        if "target" not in p.parts
    )
    assert ctx.intent is not None
    inputs = build_reviewer_inputs(
        cas=deps.cas,
        intent=ctx.intent,
        source_paths=source_paths,
        graph_slice=slice_graph_for_review(ctx.graph, source_paths),
    )
    outcome: ReviewOutcome = run_reviewers(
        engine=deps.agent_engine,  # type: ignore[arg-type]
        registry=deps.registry(),
        run_id=ctx.run_id,
        revision_sha=ctx.revision_sha,
        checkout=ctx.checkout,
        inputs=inputs,
        db_engine=deps.engine,
        cas=deps.cas,
        budget=deps.budget,
    )
    ctx.findings = outcome.findings
    ctx.failed_skills = outcome.failed_skills
    ctx.artifacts["candidateFindings"] = deps.cas.put_json(
        {"findings": [f.contract_dump() for f in outcome.findings]}
    )
    if outcome.failed_skills:
        ctx.notes.append(f"reviewers that did not complete: {', '.join(outcome.failed_skills)}")


def stage_validate(deps: PipelineDeps, ctx: ReviewContext, revision_db_id: int) -> None:
    battery = run_battery(ctx.checkout, ctx.revision_sha)
    with Session(deps.engine) as session:
        for receipt in battery.receipts:
            repo.record_receipt(session, run_id=ctx.run_id, receipt=receipt)
        session.commit()
    if battery.tools_unavailable:
        ctx.notes.append(f"verification tools unavailable: {', '.join(battery.tools_unavailable)}")

    with Session(deps.engine) as session:
        from sqlalchemy import select

        paths = session.scalars(
            select(FileRow.path).where(FileRow.revision_id == revision_db_id)
        ).all()
    file_lengths = {
        path: len((ctx.checkout / path).read_text(encoding="utf-8", errors="replace").splitlines())
        for path in paths
        if (ctx.checkout / path).is_file()
    }

    ctx.validation = validate_findings(
        findings=ctx.findings,
        index=battery.index,
        file_lengths=file_lengths,
        engine=deps.agent_engine,  # type: ignore[arg-type]
        registry=deps.registry(),
        run_id=ctx.run_id,
        revision_sha=ctx.revision_sha,
        checkout=ctx.checkout,
        db_engine=deps.engine,
        cas=deps.cas,
        budget=deps.budget,
    )
    _persist_findings(deps, ctx)


def _persist_findings(deps: PipelineDeps, ctx: ReviewContext) -> None:
    assert ctx.validation is not None
    with Session(deps.engine) as session:
        for finding in ctx.findings:
            result = ctx.validation.results.get(finding.finding_id)
            session.add(
                FindingRow(
                    run_id=ctx.run_id,
                    finding_id=finding.finding_id,
                    category=finding.category,
                    severity=result.severity if result else finding.severity,
                    confidence=result.confidence if result else finding.confidence,
                    claim=finding.claim,
                    path=finding.location.path,
                    start_line=finding.location.start_line,
                    end_line=finding.location.end_line,
                    status=result.status if result else "candidate",
                    duplicate_of=result.duplicate_of if result else None,
                    discovered_by_skill=finding.discovered_by_skill,
                    skill_version=finding.skill_version,
                    introduced_by_change=result.introduced_by_change if result else None,
                    publication_eligible=bool(result and result.publication_eligible),
                    payload=finding.contract_dump(),
                    validation=result.contract_dump() if result else None,
                )
            )
        session.commit()


def stage_synthesize(deps: PipelineDeps, ctx: ReviewContext) -> None:
    assert ctx.validation is not None
    ctx.report = build_report(
        run_id=ctx.run_id,
        revision_sha=ctx.revision_sha,
        findings=ctx.findings,
        validations=ctx.validation.results,
        failed_skills=ctx.failed_skills,
    )
    from codeatlas.review.synthesis import render_markdown

    ctx.artifacts["reviewMarkdown"] = deps.cas.put(render_markdown(ctx.report).encode("utf-8"))


def stage_diagrams(deps: PipelineDeps, ctx: ReviewContext) -> None:
    """C4 workspace + rendered views. Missing tools degrade the run, not fail it."""
    out = deps.artifacts_dir / ctx.run_id
    mapping = map_graph_to_c4(ctx.graph, system_name=ctx.graph.repository.id.split("/")[-1])
    dsl = generate_dsl(mapping, revision_sha=ctx.revision_sha)
    ctx.artifacts["structurizrDsl"] = deps.cas.put(dsl.encode("utf-8"))

    if cli_path() is None:
        ctx.notes.append("structurizr CLI unavailable: C4 workspace generated but not validated")
        return
    dsl_path = write_dsl(dsl, out / "workspace.dsl")
    try:
        validate_workspace(dsl_path)
        exported = export_views(dsl_path, out / "views")
    except Exception as exc:
        ctx.notes.append(f"C4 export failed: {exc}")
        return
    ctx.artifacts["c4Views"] = deps.cas.put_json([f.name for f in exported.files])

    if mmdc_path() is None:
        ctx.notes.append("mmdc unavailable: C4 views exported but not rendered")
        return
    rendered = []
    for view in exported.files:
        try:
            result = render(view, out / "svg" / (view.stem + ".svg"))
            rendered.append(result.svg.name)
        except Exception as exc:
            ctx.notes.append(f"render failed for {view.name}: {exc}")
    if rendered:
        ctx.artifacts["c4Svg"] = deps.cas.put_json(sorted(rendered))


def stage_protocol_diagrams(
    deps: PipelineDeps, ctx: ReviewContext, model_json: dict[str, Any] | None
) -> None:
    if model_json is None:
        return
    from codeatlas.models.protocol import ProtocolModel

    model = ProtocolModel.model_validate(model_json)
    out = deps.artifacts_dir / ctx.run_id / "protocol"
    for name, text in (
        ("sequence", sequence_diagram(model)),
        ("state", state_diagram(model)),
    ):
        ctx.artifacts[f"protocol{name.title()}"] = deps.cas.put(text.encode("utf-8"))
        if mmdc_path() is None:
            continue
        source = out / f"{name}.mmd"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(text, encoding="utf-8", newline="\n")
        try:
            render(source, out / f"{name}.svg")
        except Exception as exc:
            ctx.notes.append(f"protocol {name} render failed: {exc}")


def stage_adr_audit(deps: PipelineDeps, ctx: ReviewContext) -> None:
    decisions = parse_adr_directory(ctx.checkout / "docs" / "adr", root=ctx.checkout)
    if not decisions:
        ctx.notes.append("no ADRs found; architecture conformance was not audited")
        return
    layers = _infer_layers(ctx.graph)
    audits = []
    for decision in decisions:
        result = audit_layering(
            decision, LayeringRule(layers=layers, module_root=_module_root(ctx.graph)), ctx.graph
        )
        audits.append(
            {
                "adr": result.adr_path,
                "label": result.adr_label,
                "status": result.status,
                "assertion": result.assertion,
                "auditResult": result.audit_result,
                "confidence": result.confidence,
                "requiresHumanDecision": result.requires_human_decision,
                "affectedNodes": result.affected_node_ids,
                "evidence": result.evidence,
                "detail": result.detail,
            }
        )
    ctx.artifacts["adrAudit"] = deps.cas.put_json(audits)
    drifting = [a for a in audits if a["auditResult"] == "probable-drift"]
    if drifting:
        ctx.notes.append(f"{len(drifting)} ADR(s) show probable drift")


def _module_root(graph: ProjectGraph) -> str:
    """The source directory holding the most modules, e.g. 'kvstore/src'.

    Not the common prefix across all files: a workspace with two crates
    (kvstore/ and kvstore-cli/) has no common source root, and asking for one
    yields "" — which made the ADR audit silently unverifiable on exactly the
    multi-crate layouts it exists to check.
    """
    counts: dict[str, int] = {}
    for node in graph.nodes:
        if node.kind != "file" or node.location is None:
            continue
        parent = node.location.path.rsplit("/", 1)[0] if "/" in node.location.path else ""
        counts[parent] = counts.get(parent, 0) + 1
    if not counts:
        return ""
    # Most populous wins; ties break on the shorter (outer) path for stability.
    return sorted(counts.items(), key=lambda item: (-item[1], len(item[0]), item[0]))[0][0]


def _infer_layers(graph: ProjectGraph) -> list[str]:
    """Module names under the source root, ordered outermost-first by convention."""
    root = _module_root(graph)
    names = sorted(
        {
            n.location.path[len(root) + 1 :].removesuffix(".rs")
            for n in graph.nodes
            if n.kind == "file" and n.location and n.location.path.startswith(root + "/")
        }
    )
    names = [n for n in names if "/" not in n and n not in ("lib", "main", "mod")]
    preferred = ["api", "handler", "service", "cache", "domain", "storage", "store", "db"]
    ordered = [n for n in preferred if n in names]
    return ordered + [n for n in names if n not in ordered]


def stage_payload(
    deps: PipelineDeps, ctx: ReviewContext, scope: ChangedScope | None
) -> dict[str, Any] | None:
    """Build the review payload without publishing it (shadow by default)."""
    if ctx.report is None or deps.github_owner is None or deps.pr_number is None:
        return None
    from codeatlas.publication.shadow import run_shadow

    with Session(deps.engine) as session:
        result = run_shadow(
            session,
            run_id=ctx.run_id,
            report=ctx.report,
            findings=ctx.findings,
            scope=scope,
            cas=deps.cas,
            owner=deps.github_owner,
            repo=deps.github_repo or "",
            pr_number=deps.pr_number,
            commit_sha=ctx.revision_sha,
        )
        session.commit()
    ctx.artifacts["reviewPayload"] = result.dry_run.payload_sha256
    return {
        "payloadSha256": result.dry_run.payload_sha256,
        "blocking": result.blocking_ids,
        "nonBlocking": result.non_blocking_ids,
        "scopeCounts": result.scope_counts,
        "secretsDetected": result.dry_run.secrets_detected,
    }


def build_payload_for_report(
    ctx: ReviewContext, owner: str, repo_name: str, pr_number: int, changed: set[str] | None
) -> dict[str, Any]:
    assert ctx.report is not None
    payload = build_payload(
        ctx.report,
        owner=owner,
        repo=repo_name,
        pr_number=pr_number,
        commit_sha=ctx.revision_sha,
        changed_paths=changed,
    )
    dumped: dict[str, Any] = payload.contract_dump()
    return dumped
