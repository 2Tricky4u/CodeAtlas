"""The review half of the pipeline: intent, reviewers, verification, validation,
synthesis, C4 validation, and the dry-run payload.

Everything here needs an agent engine or an external toolchain. What does not —
the project overview, the architecture model, the ADR conformance audit, the
project narrative's own node — lives in the deterministic half, where it can be
had without paying for a review.

Each stage is a plain function over the dependency container so it can be tested
directly, then composed into the LangGraph in `graph.py`. They persist their own
evidence as they go: a stage that produced findings has rows to show for it, and
a stage that failed leaves the reason behind.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from codeatlas.artifacts.mermaid.validate import mmdc_path, render
from codeatlas.artifacts.structurizr.validate import (
    cli_path,
    export_views,
    validate_workspace,
    write_dsl,
)
from codeatlas.core.logging import get_logger
from codeatlas.db import repositories as repo
from codeatlas.db.tables import FileRow, FindingRow
from codeatlas.models.coverage import ReviewCoverage, ReviewerCoverage
from codeatlas.models.explanation import ChangeExplanation
from codeatlas.models.findings import Finding
from codeatlas.models.graph import ProjectGraph
from codeatlas.models.intent import IntentPackage
from codeatlas.pipeline.artifacts_out import adopt_artifact, publish_artifact
from codeatlas.pipeline.deps import PipelineDeps
from codeatlas.review.intent_node import reconstruct_intent
from codeatlas.review.reviewers import (
    ReviewOutcome,
    build_reviewer_inputs,
    run_reviewers,
    slice_graph_for_review,
)
from codeatlas.review.scope import ChangedScope
from codeatlas.review.synthesis import ReviewReport, build_report
from codeatlas.validation.memory import FindingMemory, remember_rejection
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
    explanation: ChangeExplanation | None = None
    notes: list[str] = field(default_factory=list)
    _artifacts: dict[str, str] = field(default_factory=dict, init=False, repr=False)

    @property
    def artifacts(self) -> Mapping[str, str]:
        """What this run produced, by role. Read-only — see `publish`."""
        return MappingProxyType(self._artifacts)

    def publish(
        self,
        deps: PipelineDeps,
        role: str,
        payload: object,
        *,
        schema_id: str | None = None,
        media_type: str = "application/json",
        producer: str = "pipeline",
    ) -> str:
        """Store an artifact, record that this run owns it, and return its sha.

        One act, deliberately. Storing content and indexing membership used to be
        two calls at seven sites, and five of them only did the first — so five
        artifacts were named in the run manifest and returned 404 from the API.
        `artifacts` is read-only precisely so this is the only way in.
        """
        sha = publish_artifact(
            deps,
            self.run_id,
            role,
            payload,
            schema_id=schema_id,
            media_type=media_type,
            producer=producer,
        )
        self._artifacts[role] = sha
        return sha

    def adopt(self, deps: PipelineDeps, role: str, sha256: str) -> str:
        """Claim an artifact another component already stored and indexed."""
        self._artifacts[role] = adopt_artifact(deps, self.run_id, role, sha256)
        return sha256


def stage_intent(deps: PipelineDeps, ctx: ReviewContext) -> None:
    package, problems, _sha = reconstruct_intent(
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
    # `reconstruct_intent` stores the package itself; publishing is what records
    # the membership row that makes it fetchable. Same content, same address.
    ctx.publish(deps, "intent", package.contract_dump(), schema_id="intent.v1")
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
    ctx.publish(
        deps,
        "candidate-findings",
        {"findings": [f.contract_dump() for f in outcome.findings]},
    )
    if outcome.failed_skills:
        ctx.notes.append(f"reviewers that did not complete: {', '.join(outcome.failed_skills)}")

    # Coverage, measured not claimed: what the engine saw each reviewer read,
    # diffed against the files every reviewer was offered. A reviewer whose
    # engine reported nothing carries measured=False with empty lists —
    # unknown is a third state, never rendered as read or unread.
    offered = set(source_paths)
    coverage = ReviewCoverage(
        revision=ctx.revision_sha,
        source_path_count=len(source_paths),
        reviewers=[
            ReviewerCoverage(
                skill_id=skill_id,
                measured=read is not None,
                files_read=sorted(offered & set(read)) if read is not None else [],
                not_read=sorted(offered - set(read)) if read is not None else [],
            )
            for skill_id, read in sorted(outcome.files_read.items())
        ],
    )
    ctx.publish(
        deps,
        "review-coverage",
        coverage.contract_dump(),
        schema_id="review-coverage.v1",
    )


def stage_validate(
    deps: PipelineDeps, ctx: ReviewContext, revision_db_id: int, repository_id: str
) -> None:
    battery = run_battery(ctx.checkout, ctx.revision_sha)
    with Session(deps.engine) as session:
        for receipt in battery.receipts:
            repo.record_receipt(session, run_id=ctx.run_id, receipt=receipt)
        session.commit()
    if battery.tools_unavailable:
        ctx.notes.append(f"verification tools unavailable: {', '.join(battery.tools_unavailable)}")

    with Session(deps.engine) as session:
        file_rows = session.execute(
            select(FileRow.path, FileRow.git_blob_sha).where(FileRow.revision_id == revision_db_id)
        ).all()
        blob_shas: dict[str, str] = {row.path: row.git_blob_sha for row in file_rows}
        # One repository's remembered rejections, preloaded so validation
        # itself never touches the database (ADR-0016).
        memory = FindingMemory.load(
            session, repository_id=repository_id, blob_shas=blob_shas, graph=ctx.graph
        )
    file_lengths = {
        path: len((ctx.checkout / path).read_text(encoding="utf-8", errors="replace").splitlines())
        for path in blob_shas
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
        memory=memory,
    )
    _persist_findings(deps, ctx, memory=memory)
    if ctx.validation.suppressed:
        ctx.notes.append(
            f"{len(ctx.validation.suppressed)} finding(s) suppressed by cross-run memory"
        )


def _persist_findings(
    deps: PipelineDeps, ctx: ReviewContext, memory: FindingMemory | None = None
) -> None:
    assert ctx.validation is not None
    outcome = ctx.validation
    with Session(deps.engine) as session:
        for finding in ctx.findings:
            remembered = outcome.suppressed.get(finding.finding_id)
            if remembered is not None:
                # No agent ran; the record is the remembered rejection. This is
                # deliberately NOT a validation-result.v1 payload — that schema
                # gates agent output, and an agent must never emit "suppressed".
                session.add(
                    FindingRow(
                        run_id=ctx.run_id,
                        finding_id=finding.finding_id,
                        category=finding.category,
                        severity=finding.severity,
                        confidence=finding.confidence,
                        claim=finding.claim,
                        path=finding.location.path,
                        start_line=finding.location.start_line,
                        end_line=finding.location.end_line,
                        status="suppressed",
                        duplicate_of=None,
                        discovered_by_skill=finding.discovered_by_skill,
                        skill_version=finding.skill_version,
                        introduced_by_change=None,
                        publication_eligible=False,
                        payload=finding.contract_dump(),
                        validation={
                            "status": "suppressed",
                            "memoryFingerprint": remembered.fingerprint,
                            "decidedInRun": remembered.decided_in_run,
                            "reason": remembered.reason,
                            "rememberedBlobSha": remembered.file_blob_sha,
                        },
                    )
                )
                continue
            result = outcome.results.get(finding.finding_id)
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
        if memory is not None:
            # Same transaction as the finding rows: the memory that justifies
            # a future suppression must never exist without its evidence.
            findings_by_id = {f.finding_id: f for f in ctx.findings}
            for finding_id in sorted(outcome.dispatched):
                result = outcome.results.get(finding_id)
                if result is not None and result.status == "rejected":
                    remember_rejection(
                        session,
                        memory,
                        findings_by_id[finding_id],
                        reason=result.reason,
                        run_id=ctx.run_id,
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
        suppressed=ctx.validation.suppressed,
    )
    from codeatlas.review.synthesis import render_markdown

    ctx.publish(deps, "review-markdown", render_markdown(ctx.report), media_type="text/markdown")


def stage_diagrams(deps: PipelineDeps, ctx: ReviewContext, dsl: str) -> None:
    """Validate the C4 workspace with the Structurizr CLI. Missing tools degrade the run.

    The DSL itself is produced deterministically upstream — an architecture does
    not depend on anyone reviewing a change. What happens here is the *check*
    that it parses, plus the rendered SVG. Neither is an artifact: they live on
    disk under the run's artifacts directory, and giving them a role would name
    content the store does not hold, which is the same category error as an
    artifact only the manifest knows about.
    """
    out = deps.artifacts_dir / ctx.run_id

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

    if mmdc_path() is None:
        ctx.notes.append("mmdc unavailable: C4 views exported but not rendered")
        return
    for view in exported.files:
        try:
            render(view, out / "svg" / (view.stem + ".svg"))
        except Exception as exc:
            ctx.notes.append(f"render failed for {view.name}: {exc}")


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


def stage_explain_change(
    deps: PipelineDeps,
    ctx: ReviewContext,
    *,
    repository_id: str,
    base_sha: str,
    merge_base_sha: str,
    base_revision_db_id: int,
    head_revision_db_id: int,
    graph_diff_sha: str,
    api_change_sha: str | None,
    impact_sha: str | None,
) -> None:
    """Explain the change, then delete every claim that does not check out.

    The diff is recomputed here with context rather than reused from
    `source_lock`: that one is zero-context because its only consumer is
    added-line extraction, and a reader — human or model — needs the lines
    around a change to say what it did.
    """
    from codeatlas.models.api import ApiChange
    from codeatlas.models.diff import GraphDiff
    from codeatlas.models.impact import ChangeImpact
    from codeatlas.pipeline.source import mirror_path
    from codeatlas.review.explainer import build_index, explain_change

    mirror = mirror_path(deps, repository_id)
    diff_text = deps.git.unified_diff(mirror, merge_base_sha, ctx.revision_sha, context=3)

    diff = GraphDiff.model_validate(json.loads(deps.cas.get(graph_diff_sha)))
    api_change = (
        ApiChange.model_validate(json.loads(deps.cas.get(api_change_sha)))
        if api_change_sha
        else None
    )
    impact = (
        ChangeImpact.model_validate(json.loads(deps.cas.get(impact_sha))) if impact_sha else None
    )

    index = build_index(
        db_engine=deps.engine,
        base_revision_id=base_revision_db_id,
        head_revision_id=head_revision_db_id,
        base_sha=base_sha,
        head_sha=ctx.revision_sha,
        diff=diff,
        api_change=api_change,
        impact=impact,
    )

    def read_lines(revision: str, path: str) -> int:
        revision_id = base_revision_db_id if revision == base_sha else head_revision_db_id
        with Session(deps.engine) as session:
            row = session.scalar(
                select(FileRow).where(FileRow.revision_id == revision_id, FileRow.path == path)
            )
        if row is None:
            raise FileNotFoundError(path)
        blob = deps.git.cat_file(mirror, row.git_blob_sha)
        return len(blob.decode("utf-8", "replace").splitlines())

    explanation, dropped = explain_change(
        engine=deps.agent_engine,  # type: ignore[arg-type]
        registry=deps.registry(),
        run_id=ctx.run_id,
        head_sha=ctx.revision_sha,
        checkout=ctx.checkout,
        db_engine=deps.engine,
        cas=deps.cas,
        diff_text=diff_text,
        diff=diff,
        api_change=api_change,
        impact=impact,
        index=index,
        budget=deps.budget,
        read_lines=read_lines,
    )
    if explanation is None:
        ctx.failed_skills.append("change-explainer")
        ctx.notes.append("change explanation unavailable: the explainer did not complete")
        return

    ctx.explanation = explanation
    ctx.publish(
        deps,
        "change-explanation",
        explanation.contract_dump(),
        schema_id="change-explanation.v1",
        producer="change-explainer",
    )
    if dropped:
        ctx.notes.append(
            f"{len(dropped)} explanation claim(s) removed: their citations did not "
            "resolve against this run's evidence"
        )
    log.info(
        "review.explained",
        run_id=ctx.run_id,
        claims=explanation.claim_count,
        dropped=len(dropped),
    )


def stage_payload(
    deps: PipelineDeps, ctx: ReviewContext, scope: ChangedScope | None
) -> dict[str, Any] | None:
    """Build the review payload without publishing it (shadow by default)."""
    if ctx.report is None or deps.github_owner is None or deps.pr_number is None:
        return None
    from codeatlas.publication.shadow import run_shadow
    from codeatlas.review.explainer import condensed_markdown

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
            explanation_markdown=(condensed_markdown(ctx.explanation) if ctx.explanation else None),
        )
        session.commit()
    ctx.adopt(deps, "review-payload-dry-run", result.dry_run.payload_sha256)
    return {
        "payloadSha256": result.dry_run.payload_sha256,
        "blocking": result.blocking_ids,
        "nonBlocking": result.non_blocking_ids,
        "scopeCounts": result.scope_counts,
        "secretsDetected": result.dry_run.secrets_detected,
    }
