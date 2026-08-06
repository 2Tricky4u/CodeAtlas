"""LangGraph assembly for the walking-skeleton pipeline (M6).

source_lock -> extract -> build_graph -> export_cytoscape -> finalize

Every node is wrapped: it records start/finish run events, updates stage_status,
and on failure records a typed error event, marks the run failed, and re-raises
(the checkpoint before the failed node enables `codeatlas resume`).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from codeatlas.artifacts.cytoscape import to_cytoscape
from codeatlas.core.canonical import canonical_json, canonical_sha256
from codeatlas.core.logging import get_logger
from codeatlas.db import repositories as repo
from codeatlas.extractors.base import ExtractorError, GraphFragment
from codeatlas.extractors.rust.cargo_meta import CargoMetadataExtractor
from codeatlas.extractors.rust.ra_scip import RaScipExtractor
from codeatlas.graph.merge import merge_fragments
from codeatlas.graph.validate import validate_graph
from codeatlas.models.graph import ProjectGraph
from codeatlas.models.manifest import RunCost, RunManifest, SourceLock
from codeatlas.models.overview import ProjectOverview
from codeatlas.pipeline.deps import PipelineDeps
from codeatlas.pipeline.state import PipelineState
from codeatlas.vcs.source_lock import build_source_lock

log = get_logger("codeatlas.pipeline")

NodeFn = Callable[[PipelineState], dict[str, Any]]

EXTRACTORS = (CargoMetadataExtractor, RaScipExtractor)


def _load_file_table(
    session: Session, deps: PipelineDeps, mirror: Path, revision_id: int, sha: str
) -> None:
    """Record the full tree at a revision. Idempotent — revisions are immutable.

    Both revisions of a pull request need this: the file table is the allowlist
    `/api/source` validates against, so a "what it looked like before" view is
    only servable for a base revision whose tree was recorded.
    """
    from sqlalchemy import func as sa_func
    from sqlalchemy import select as sa_select

    from codeatlas.db.tables import FileRow
    from codeatlas.vcs.source_lock import classify_generated

    existing = session.scalar(
        sa_select(sa_func.count()).select_from(FileRow).where(FileRow.revision_id == revision_id)
    )
    if existing:
        return
    entries = deps.git.ls_tree(mirror, sha)
    generated = set(classify_generated([e.path for e in entries]))
    for entry in entries:
        session.add(
            FileRow(
                revision_id=revision_id,
                path=entry.path,
                git_blob_sha=entry.blob_sha,
                language="rust" if entry.path.endswith(".rs") else None,
                is_generated=entry.path in generated,
            )
        )


def _semver_version() -> str:
    from codeatlas.extractors.base import ExtractorError
    from codeatlas.extractors.rust.semver_checks import tool_version

    try:
        return tool_version()
    except ExtractorError:
        return "absent"


def _validated_graph(
    session: Session, graph: ProjectGraph, revision_db_id: int, stage: str
) -> None:
    from sqlalchemy import select

    from codeatlas.db.tables import FileRow

    valid_paths = set(
        session.scalars(select(FileRow.path).where(FileRow.revision_id == revision_db_id))
    )
    violations = validate_graph(graph, valid_paths=valid_paths)
    if violations:
        raise StageFailure(
            stage, f"{len(violations)} constraint violations: " + "; ".join(violations[:5])
        )


class StageFailure(RuntimeError):
    def __init__(self, stage: str, message: str) -> None:
        super().__init__(f"{stage}: {message}")
        self.stage = stage


def _wrap(deps: PipelineDeps, name: str, fn: NodeFn) -> NodeFn:
    def node(state: PipelineState) -> dict[str, Any]:
        run_id = state["run_id"]
        with Session(deps.engine) as session:
            repo.add_run_event(session, run_id=run_id, stage=name, event="started")
            session.commit()
        log.info("stage.started", stage=name, run_id=run_id)
        try:
            if deps.crash_stage == name:
                raise StageFailure(name, "injected crash (fault injection)")
            update = fn(state)
        except Exception as exc:
            with Session(deps.engine) as session:
                repo.add_run_event(
                    session,
                    run_id=run_id,
                    stage=name,
                    event="failed",
                    level="error",
                    data={"error": str(exc)[:2000], "type": type(exc).__name__},
                )
                repo.set_run_status(session, run_id=run_id, status="failed")
                session.commit()
            log.error("stage.failed", stage=name, run_id=run_id, error=str(exc))
            raise
        with Session(deps.engine) as session:
            repo.add_run_event(session, run_id=run_id, stage=name, event="finished")
            session.commit()
        log.info("stage.finished", stage=name, run_id=run_id)
        update.setdefault("stage_status", {})
        update["stage_status"] = {**update["stage_status"], name: "succeeded"}
        return update

    return node


def build_pipeline(deps: PipelineDeps):  # type: ignore[no-untyped-def]
    def source_lock(state: PipelineState) -> dict[str, Any]:
        from codeatlas.pipeline.source import prepare_source, resolve_in_mirror

        repository_id = state["repository_id"]
        ref = state.get("ref", "HEAD")
        base_ref = state.get("base_ref")

        # Works for a local path or a clone URL: the mirror is created first and
        # everything is resolved from it. A crashed run can leave a partial
        # mirror or checkout behind, so anything unusable is rebuilt rather than
        # left to poison every later run.
        prepared = prepare_source(deps, state["repo_path"], repository_id, ref)
        mirror, head_sha = prepared.mirror, prepared.head_sha
        checkout = deps.checkouts / head_sha
        deps.git.ensure_checkout(mirror, head_sha, checkout)

        base_sha = (
            resolve_in_mirror(deps, mirror, base_ref, remote=prepared.remote_url is not None)
            if base_ref
            else None
        )

        lock: SourceLock = build_source_lock(
            mirror,
            repository_id=repository_id,
            head_ref=head_sha,
            base_ref=base_sha,
            git=deps.git,
        )
        lock_bytes = canonical_json(lock.contract_dump())
        lock_sha = deps.cas.put(lock_bytes)

        # The diff the review is scoped against comes from the same pinned
        # revisions the extraction ran on, not from a provider API that could be
        # describing a different head.
        added_lines: dict[str, list[int]] = {}
        if base_sha and lock.merge_base_sha:
            from codeatlas.review.scope import parse_added_lines

            diff = deps.git.unified_diff(mirror, lock.merge_base_sha, head_sha)
            added_lines = {path: sorted(lines) for path, lines in parse_added_lines(diff).items()}

        with Session(deps.engine) as session:
            revision = repo.ensure_revision(
                session, repository_id=repository_id, sha=head_sha, ref_name=ref
            )
            run_row = repo.get_run(session, state["run_id"])
            if run_row is None:
                raise StageFailure("source_lock", f"run {state['run_id']} not found")
            run_row.head_revision_id = revision.id
            run_row.status = "running"
            if base_sha:
                base_revision = repo.ensure_revision(
                    session, repository_id=repository_id, sha=base_sha, ref_name=base_ref
                )
                run_row.base_revision_id = base_revision.id
                run_row.kind = "pr"
                if state.get("pr_number"):
                    run_row.pr_number = int(state["pr_number"])
            repo.index_artifact(
                session,
                sha256=lock_sha,
                kind="source-lock",
                media_type="application/json",
                size_bytes=len(lock_bytes),
                producer="pipeline",
                produced_by_run_id=state["run_id"],
            )
            _load_file_table(session, deps, mirror, revision.id, head_sha)
            session.commit()
            revision_db_id = revision.id

        update: dict[str, Any] = {
            "head_sha": head_sha,
            "revision_db_id": revision_db_id,
            "checkout_path": str(checkout),
            "source_lock_sha256": lock_sha,
            "changed_paths": list(lock.changed_paths),
            "added_lines": added_lines,
        }
        if base_sha:
            update["base_sha"] = base_sha
        return update

    def extract(state: PipelineState) -> dict[str, Any]:
        checkout = Path(state["checkout_path"])
        head_sha = state["head_sha"]
        fragment_shas: list[str] = []
        count = 0
        for factory in EXTRACTORS:
            extractor = factory()
            try:
                fragment, receipt = extractor.extract(checkout, head_sha)
            except ExtractorError as exc:
                if exc.receipt is not None:
                    with Session(deps.engine) as session:
                        repo.record_receipt(session, run_id=state["run_id"], receipt=exc.receipt)
                        session.commit()
                raise
            sha = deps.cas.put_json(fragment.dump())
            fragment_shas.append(sha)
            with Session(deps.engine) as session:
                repo.record_receipt(session, run_id=state["run_id"], receipt=receipt)
                session.commit()
            count += 1
        return {"fragment_shas": fragment_shas, "receipt_count": count}

    def build_graph(state: PipelineState) -> dict[str, Any]:
        fragments = [
            GraphFragment.from_dump(json.loads(deps.cas.get(sha))) for sha in state["fragment_shas"]
        ]
        graph: ProjectGraph = merge_fragments(
            repository_id=state["repository_id"],
            head_sha=state["head_sha"],
            fragments=fragments,
        )
        graph_bytes = canonical_json(graph.contract_dump())
        graph_sha = deps.cas.put(graph_bytes)
        with Session(deps.engine) as session:
            _validated_graph(session, graph, state["revision_db_id"], "build_graph")
            repo.index_artifact(
                session,
                sha256=graph_sha,
                kind="project-graph",
                media_type="application/json",
                size_bytes=len(graph_bytes),
                producer="pipeline",
                produced_by_run_id=state["run_id"],
                schema_id="project-graph.v1",
            )
            snapshot = repo.store_graph_snapshot(
                session,
                run_id=state["run_id"],
                revision_id=state["revision_db_id"],
                graph=graph,
                artifact_sha256=graph_sha,
                role="head",
            )
            session.commit()
            snapshot_id = snapshot.id
        return {"graph_snapshot_id": snapshot_id, "graph_sha256": graph_sha}

    def base_revision(state: PipelineState) -> dict[str, Any]:
        """Analyze the revision this change is measured against.

        A no-op in repository mode, where there is no "before". Extraction is the
        expensive half of a run, so an already-analyzed base is reused when the
        toolchain that produced it still matches — see `graph_cache`. The reuse
        is recorded as a run event, because an invisible cache is one nobody can
        check.
        """
        base_sha = state.get("base_sha")
        if not base_sha:
            return {"base_cache_hit": False}

        from codeatlas.pipeline import graph_cache
        from codeatlas.pipeline.source import mirror_path

        run_id = state["run_id"]
        mirror = mirror_path(deps, state["repository_id"])
        fingerprint = graph_cache.toolchain_fingerprint()

        with Session(deps.engine) as session:
            revision = repo.ensure_revision(
                session, repository_id=state["repository_id"], sha=base_sha
            )
            _load_file_table(session, deps, mirror, revision.id, base_sha)
            session.commit()
            base_revision_db_id = revision.id
            entry = graph_cache.lookup_entry(session, base_revision_db_id, fingerprint)
            cached = entry.graph_sha256 if entry else None
            origin_run = entry.produced_by_run_id if entry else None

        if cached is not None:
            graph_sha = cached
            graph = ProjectGraph.model_validate(json.loads(deps.cas.get(graph_sha)))
            with Session(deps.engine) as session:
                repo.add_run_event(
                    session,
                    run_id=run_id,
                    stage="base_revision",
                    event="base_graph_cache_hit",
                    # `producedByRunId` is the provenance link: this run holds no
                    # extractor receipts for the base, and that is where the ones
                    # that witness this graph live.
                    data={
                        "revision": base_sha,
                        "toolchain": fingerprint,
                        "graph": graph_sha,
                        "producedByRunId": origin_run,
                    },
                )
                session.commit()
        else:
            checkout = deps.checkouts / base_sha
            deps.git.ensure_checkout(mirror, base_sha, checkout)
            fragments: list[GraphFragment] = []
            for factory in EXTRACTORS:
                extractor = factory()
                try:
                    fragment, receipt = extractor.extract(checkout, base_sha)
                except ExtractorError as exc:
                    if exc.receipt is not None:
                        with Session(deps.engine) as session:
                            repo.record_receipt(session, run_id=run_id, receipt=exc.receipt)
                            session.commit()
                    raise
                fragments.append(fragment)
                with Session(deps.engine) as session:
                    repo.record_receipt(session, run_id=run_id, receipt=receipt)
                    session.commit()
            graph = merge_fragments(
                repository_id=state["repository_id"], head_sha=base_sha, fragments=fragments
            )
            graph_bytes = canonical_json(graph.contract_dump())
            graph_sha = deps.cas.put(graph_bytes)
            with Session(deps.engine) as session:
                _validated_graph(session, graph, base_revision_db_id, "base_revision")
                session.commit()

        with Session(deps.engine) as session:
            repo.index_artifact(
                session,
                sha256=graph_sha,
                kind="project-graph",
                media_type="application/json",
                size_bytes=len(deps.cas.get(graph_sha)),
                producer="pipeline",
                produced_by_run_id=run_id,
                schema_id="project-graph.v1",
                role="project-graph-base",
            )
            if cached is None:
                # After indexing, never before: the cache points at an artifact
                # row, so remembering a graph the artifact table does not know
                # about would leave a dangling reference.
                graph_cache.remember(
                    session,
                    revision_id=base_revision_db_id,
                    fingerprint=fingerprint,
                    graph_sha256=graph_sha,
                    produced_by_run_id=run_id,
                )
            snapshot = repo.store_graph_snapshot(
                session,
                run_id=run_id,
                revision_id=base_revision_db_id,
                graph=graph,
                artifact_sha256=graph_sha,
                role="base",
            )
            session.commit()
            snapshot_id = snapshot.id

        return {
            "base_revision_db_id": base_revision_db_id,
            "base_graph_sha256": graph_sha,
            "base_graph_snapshot_id": snapshot_id,
            "base_cache_hit": cached is not None,
        }

    def graph_diff(state: PipelineState) -> dict[str, Any]:
        """What the change did to the structure: symbols and relationships.

        Pure and cheap — two graphs in, a delta out — so it runs before the
        API-surface stage. A missing nightly toolchain then costs a run its API
        narrative without also costing it the structural one.
        """
        base_graph_sha = state.get("base_graph_sha256")
        if not base_graph_sha:
            return {}

        from codeatlas.change.graph import diff_graphs

        base_graph = ProjectGraph.model_validate(json.loads(deps.cas.get(base_graph_sha)))
        head_graph = ProjectGraph.model_validate(json.loads(deps.cas.get(state["graph_sha256"])))
        added = {path: set(lines) for path, lines in (state.get("added_lines") or {}).items()}

        diff = diff_graphs(base_graph, head_graph, added_lines=added or None)
        payload = canonical_json(diff.contract_dump())
        sha = deps.cas.put(payload)
        with Session(deps.engine) as session:
            repo.index_artifact(
                session,
                sha256=sha,
                kind="graph-diff",
                media_type="application/json",
                size_bytes=len(payload),
                producer="pipeline",
                produced_by_run_id=state["run_id"],
                schema_id="graph-diff.v1",
            )
            repo.add_run_event(
                session,
                run_id=state["run_id"],
                stage="graph_diff",
                event="graph_diff_computed",
                data={
                    "nodesAdded": diff.summary.nodes_added,
                    "nodesRemoved": diff.summary.nodes_removed,
                    "nodesTouched": diff.summary.nodes_touched,
                    "edgesAdded": diff.summary.edges_added,
                    "edgesRemoved": diff.summary.edges_removed,
                    # A nonzero count here means some ids were compared raw, so
                    # a version bump can still show as churn for those.
                    "unnormalizedIdentities": diff.unnormalized_identities,
                },
            )
            session.commit()
        return {"graph_diff_sha256": sha}

    def api_change(state: PipelineState) -> dict[str, Any]:
        """What the change did to the public API, decided by tools not opinions.

        A no-op without a base. Failure here is recorded and survived rather than
        fatal: an unavailable nightly toolchain should cost the run its API
        narrative, not its review. What it must never do is report *no* API
        change — every unmeasured package is named in `skipped`, and a package
        cargo-semver-checks could not classify keeps `requiredBump: unknown`.
        """
        base_sha = state.get("base_sha")
        if not base_sha:
            return {}

        from codeatlas.extractors.base import ExtractorError
        from codeatlas.extractors.rust.public_api import PublicApiExtractor
        from codeatlas.extractors.rust.semver_checks import check_package, lint_levels

        run_id = state["run_id"]
        head_checkout = Path(state["checkout_path"])
        base_checkout = deps.checkouts / base_sha
        if not base_checkout.exists():
            from codeatlas.pipeline.source import mirror_path

            deps.git.ensure_checkout(
                mirror_path(deps, state["repository_id"]), base_sha, base_checkout
            )

        extractor = PublicApiExtractor()
        try:
            base_surface, base_receipts = extractor.extract(base_checkout, base_sha)
            head_surface, head_receipts = extractor.extract(head_checkout, state["head_sha"])
        except ExtractorError as exc:
            with Session(deps.engine) as session:
                repo.add_run_event(
                    session,
                    run_id=run_id,
                    stage="api_change",
                    event="api_surface_unavailable",
                    level="warning",
                    data={"error": str(exc)[:500]},
                )
                session.commit()
            return {"api_change_sha256": None}

        with Session(deps.engine) as session:
            for receipt in [*base_receipts, *head_receipts]:
                repo.record_receipt(session, run_id=run_id, receipt=receipt)
            # Each revision's surface is evidence in its own right, and the
            # impact stage needs the head one to know what is publicly exported.
            for role, surface in (
                ("api-surface-base", base_surface),
                ("api-surface-head", head_surface),
            ):
                surface_bytes = canonical_json(surface.contract_dump())
                repo.index_artifact(
                    session,
                    sha256=deps.cas.put(surface_bytes),
                    kind="api-surface",
                    media_type="application/json",
                    size_bytes=len(surface_bytes),
                    producer="pipeline",
                    produced_by_run_id=run_id,
                    schema_id="api-surface.v1",
                    role=role,
                )
            session.commit()

        # Severity is only asked about packages both revisions actually exposed.
        comparable = {p.name for p in base_surface.packages} & {
            p.name for p in head_surface.packages
        }
        lints: dict[str, list[Any]] = {}
        analyzed: set[str] = set()
        unknown_reasons: dict[str, str] = {}
        try:
            levels = lint_levels()
        except ExtractorError:
            levels = {}
        if levels:
            with Session(deps.engine) as session:
                for name in sorted(comparable):
                    result = check_package(
                        head_checkout, base_checkout, name, state["head_sha"], levels=levels
                    )
                    repo.record_receipt(session, run_id=run_id, receipt=result.receipt)
                    lints[name] = result.lints
                    if result.analyzed:
                        analyzed.add(name)
                    elif result.reason:
                        unknown_reasons[name] = result.reason
                session.commit()

        from codeatlas.change.api import diff_surfaces

        change = diff_surfaces(
            base_surface,
            head_surface,
            lints=lints,
            semver_ran_for=analyzed,
            unknown_reasons=unknown_reasons,
            tools={"cargoPublicApi": base_surface.tool, "cargoSemverChecks": _semver_version()},
        )
        payload = canonical_json(change.contract_dump())
        sha = deps.cas.put(payload)
        with Session(deps.engine) as session:
            repo.index_artifact(
                session,
                sha256=sha,
                kind="api-change",
                media_type="application/json",
                size_bytes=len(payload),
                producer="pipeline",
                produced_by_run_id=run_id,
                schema_id="api-change.v1",
            )
            repo.add_run_event(
                session,
                run_id=run_id,
                stage="api_change",
                event="api_change_computed",
                data={
                    "breaking": change.has_breaking_change,
                    "packages": len(change.packages),
                    "skipped": len(change.skipped),
                },
            )
            session.commit()
        return {"api_change_sha256": sha}

    def change_impact(state: PipelineState) -> dict[str, Any]:
        """Who else could this change affect — bounded, ranked, and hedged.

        Runs last of the change stages because it consumes all of them. The
        public-API rank needs the head surface, so when `api_change` could not
        produce one the ranking says so rather than quietly demoting everything.
        """
        diff_sha = state.get("graph_diff_sha256")
        if not diff_sha:
            return {}

        from codeatlas.change.impact import analyze_impact
        from codeatlas.db.repositories import artifact_for_run
        from codeatlas.models.api import ApiSurface
        from codeatlas.models.diff import GraphDiff

        run_id = state["run_id"]
        diff = GraphDiff.model_validate(json.loads(deps.cas.get(diff_sha)))
        head_graph = ProjectGraph.model_validate(json.loads(deps.cas.get(state["graph_sha256"])))
        base_graph = ProjectGraph.model_validate(
            json.loads(deps.cas.get(state["base_graph_sha256"]))
        )

        with Session(deps.engine) as session:
            surface_sha = artifact_for_run(session, run_id, "api-surface-head")
        surface = (
            ApiSurface.model_validate(json.loads(deps.cas.get(surface_sha)))
            if surface_sha
            else None
        )

        impact = analyze_impact(diff, head=head_graph, base=base_graph, api_surface=surface)
        payload = canonical_json(impact.contract_dump())
        sha = deps.cas.put(payload)
        with Session(deps.engine) as session:
            repo.index_artifact(
                session,
                sha256=sha,
                kind="change-impact",
                media_type="application/json",
                size_bytes=len(payload),
                producer="pipeline",
                produced_by_run_id=run_id,
                schema_id="change-impact.v1",
            )
            repo.add_run_event(
                session,
                run_id=run_id,
                stage="change_impact",
                event="change_impact_computed",
                data={
                    "seeds": len(impact.seeds),
                    "impacted": impact.total_impacted,
                    "suppressed": impact.suppressed,
                    "hops": impact.hops,
                },
            )
            session.commit()
        return {"change_impact_sha256": sha}

    def project_overview(state: PipelineState) -> dict[str, Any]:
        """What this project is and where to start reading it.

        Runs on every run, not only pull requests: understanding a codebase and
        reviewing a change to it are separate questions, and a repository nobody
        has opened a pull request against still has a shape worth describing.
        """
        from codeatlas.project.overview import build_overview
        from codeatlas.project.views import build_views

        graph = ProjectGraph.model_validate(json.loads(deps.cas.get(state["graph_sha256"])))
        overview = build_overview(graph, repository_id=state["repository_id"])
        payload = canonical_json(overview.contract_dump())
        sha = deps.cas.put(payload)

        # The views the dashboard can actually draw, each already checked for
        # readability. A view that would be a hairball is refused here rather
        # than left for the browser to attempt.
        views = build_views(graph, overview)
        view_payload = canonical_json(views.contract_dump())
        view_sha = deps.cas.put(view_payload)

        with Session(deps.engine) as session:
            repo.index_artifact(
                session,
                sha256=view_sha,
                kind="graph-views",
                media_type="application/json",
                size_bytes=len(view_payload),
                producer="pipeline",
                produced_by_run_id=state["run_id"],
                schema_id="graph-view.v1",
            )
            repo.index_artifact(
                session,
                sha256=sha,
                kind="project-overview",
                media_type="application/json",
                size_bytes=len(payload),
                producer="pipeline",
                produced_by_run_id=state["run_id"],
                schema_id="project-overview.v1",
            )
            repo.add_run_event(
                session,
                run_id=state["run_id"],
                stage="project_overview",
                event="project_overview_computed",
                data={
                    "modules": len(overview.modules),
                    "levels": len(overview.levels),
                    "cycles": len(overview.cycles),
                    "entryPoints": len(overview.entry_points),
                    "orphans": len(overview.orphans),
                    "views": len(views.views),
                    "viewsRefused": len(views.refused),
                },
            )
            session.commit()
        return {"project_overview_sha256": sha, "graph_views_sha256": view_sha}

    def architecture(state: PipelineState) -> dict[str, Any]:
        """The C4 model, the Structurizr DSL, and the ADR conformance audit.

        All three are deterministic, so they belong here rather than in the
        review half: an architecture diagram of a repository, and whether its
        code still does what its ADRs decided, do not depend on anyone having
        reviewed a change to it. The DSL's *validation* still lives in `review`,
        because that needs the Structurizr CLI installed.
        """
        from codeatlas.artifacts.structurizr.gen import generate_dsl, map_graph_to_c4
        from codeatlas.pipeline.artifacts_out import publish_artifact
        from codeatlas.project.architecture import build_architecture
        from codeatlas.project.decisions import audit_decisions

        graph = ProjectGraph.model_validate(json.loads(deps.cas.get(state["graph_sha256"])))
        overview = ProjectOverview.model_validate(
            json.loads(deps.cas.get(state["project_overview_sha256"]))
        )
        model = build_architecture(graph, overview)
        sha = publish_artifact(
            deps,
            state["run_id"],
            "architecture",
            model.contract_dump(),
            schema_id="architecture.v1",
        )

        # The DSL is generated from the *whole* mapping, not the narrowed one:
        # a Structurizr workspace someone opens elsewhere should describe every
        # container the build resolved, while the drawn diagram stays legible.
        dsl = generate_dsl(
            map_graph_to_c4(graph, system_name=model.system_name),
            revision_sha=state["head_sha"],
        )
        dsl_sha = publish_artifact(
            deps, state["run_id"], "structurizr-dsl", dsl, media_type="text/plain"
        )

        # Published even when empty: "this project records no architecture
        # decisions" is a fact about it, and a missing artifact is
        # indistinguishable from a stage that failed.
        audit = audit_decisions(Path(state["checkout_path"]), graph, state["head_sha"])
        audit_sha = publish_artifact(
            deps, state["run_id"], "adr-audit", audit.contract_dump(), schema_id="adr-audit.v1"
        )

        with Session(deps.engine) as session:
            repo.add_run_event(
                session,
                run_id=state["run_id"],
                stage="architecture",
                event="architecture_derived",
                data={
                    "containers": len(model.containers),
                    "relationships": len(model.relationships),
                    "readable": bool(model.readability and model.readability.passed),
                    "decisions": len(audit.decisions),
                    "drifting": sum(
                        1 for d in audit.decisions if d.audit_result == "probable-drift"
                    ),
                },
            )
            session.commit()
        return {
            "architecture_sha256": sha,
            "structurizr_dsl_sha256": dsl_sha,
            "adr_audit_sha256": audit_sha,
            "review_notes": audit.notes,
        }

    def narrate(state: PipelineState) -> dict[str, Any]:
        """Say what this project is, checked against the overview above.

        Its own node, gated on its own flag. Project comprehension does not
        depend on there being a change to review — that was the plan's claim and
        it was not true while this lived inside `review`.
        """
        if not deps.narration_available:
            reason = (
                "no agent engine configured"
                if deps.agent_engine is None
                else "narration disabled for this run"
            )
            with Session(deps.engine) as session:
                repo.add_run_event(
                    session,
                    run_id=state["run_id"],
                    stage="narrate",
                    event="narration_skipped",
                    data={"reason": reason},
                )
                session.commit()
            return {"review_notes": [f"project narrative skipped: {reason}"]}

        from codeatlas.pipeline.narrate_stage import narrate_project
        from codeatlas.pipeline.protocol_stage import model_project_protocol

        result = narrate_project(
            deps,
            run_id=state["run_id"],
            revision_sha=state["head_sha"],
            checkout=Path(state["checkout_path"]),
            repository_id=state["repository_id"],
            revision_db_id=state["revision_db_id"],
            project_overview_sha=state["project_overview_sha256"],
        )
        # What a project speaks is a fact about the project, so it belongs with
        # the narrative rather than with the review of a change to it.
        protocol = model_project_protocol(
            deps,
            run_id=state["run_id"],
            revision_sha=state["head_sha"],
            checkout=Path(state["checkout_path"]),
            repository_id=state["repository_id"],
            revision_db_id=state["revision_db_id"],
            graph_sha=state["graph_sha256"],
            project_overview_sha=state["project_overview_sha256"],
        )
        with Session(deps.engine) as session:
            repo.add_run_event(
                session,
                run_id=state["run_id"],
                stage="narrate",
                event="narrated" if result.sha256 else "narration_failed",
                level="info" if result.sha256 else "warning",
                data={
                    "droppedClaims": result.dropped,
                    "hasProtocol": protocol.has_protocol,
                    "droppedProtocolElements": protocol.dropped,
                },
            )
            session.commit()
        return {
            "project_explanation_sha256": result.sha256,
            "protocol_model_sha256": protocol.sha256,
            "review_notes": [*result.notes, *protocol.notes],
        }

    def export_cytoscape(state: PipelineState) -> dict[str, Any]:
        graph = ProjectGraph.model_validate(json.loads(deps.cas.get(state["graph_sha256"])))
        payload = to_cytoscape(graph)
        data = canonical_json(payload)
        sha = deps.cas.put(data)
        with Session(deps.engine) as session:
            repo.index_artifact(
                session,
                sha256=sha,
                kind="cytoscape-elements",
                media_type="application/json",
                size_bytes=len(data),
                producer="pipeline",
                produced_by_run_id=state["run_id"],
            )
            session.commit()
        return {"cytoscape_sha256": sha}

    def review(state: PipelineState) -> dict[str, Any]:
        """The review half: intent, reviewers, verification, validation, synthesis.

        Skipped entirely when no agent engine is configured — a deterministic-only
        run is a supported mode, and pretending to review without a reviewer would
        be worse than saying so.
        """
        if not deps.reviews_enabled:
            return {"review_notes": ["review skipped: no agent engine configured"]}

        from codeatlas.pipeline.review_stages import (
            ReviewContext,
            stage_diagrams,
            stage_explain_change,
            stage_intent,
            stage_payload,
            stage_reviewers,
            stage_synthesize,
            stage_validate,
        )

        graph = ProjectGraph.model_validate(json.loads(deps.cas.get(state["graph_sha256"])))
        ctx = ReviewContext(
            run_id=state["run_id"],
            revision_sha=state["head_sha"],
            checkout=Path(state["checkout_path"]),
            graph=graph,
        )

        from codeatlas.pipeline.scope import scope_from_state

        # In pull-request mode this is a real scope, so a finding the change did
        # not introduce is reported without blocking. In repository mode it is
        # None, which means the whole tree is in scope and everything blocks.
        scope = scope_from_state(deps, dict(state))

        # Explaining the change comes first: it is what a reviewer reads before
        # any finding, and it depends only on artifacts already computed.
        graph_diff_sha = state.get("graph_diff_sha256")
        if state.get("base_sha") and graph_diff_sha:
            lock = SourceLock.model_validate(json.loads(deps.cas.get(state["source_lock_sha256"])))
            stage_explain_change(
                deps,
                ctx,
                repository_id=state["repository_id"],
                base_sha=state["base_sha"],
                merge_base_sha=lock.merge_base_sha or state["base_sha"],
                base_revision_db_id=state["base_revision_db_id"],
                head_revision_db_id=state["revision_db_id"],
                graph_diff_sha=graph_diff_sha,
                api_change_sha=state.get("api_change_sha256"),
                impact_sha=state.get("change_impact_sha256"),
            )

        stage_intent(deps, ctx)
        stage_reviewers(deps, ctx)
        stage_validate(deps, ctx, revision_db_id=state["revision_db_id"])
        stage_synthesize(deps, ctx)
        stage_diagrams(deps, ctx, deps.cas.get(state["structurizr_dsl_sha256"]).decode("utf-8"))
        payload = stage_payload(deps, ctx, scope=scope)

        assert ctx.validation is not None
        return {
            "review_artifacts": dict(ctx.artifacts),
            "finding_count": len(ctx.findings),
            "publishable_count": len(ctx.validation.publishable),
            "failed_skills": ctx.failed_skills,
            "review_notes": ctx.notes,
            "payload_summary": payload or {},
        }

    def finalize(state: PipelineState) -> dict[str, Any]:
        with Session(deps.engine) as session:
            run_row = repo.get_run(session, state["run_id"])
            if run_row is None:
                raise StageFailure("finalize", "run row disappeared")
            toolchain = {r.extractor: r.extractor_version for r in run_row.receipts}
            lock = SourceLock.model_validate(json.loads(deps.cas.get(state["source_lock_sha256"])))
            manifest = RunManifest(
                run_id=state["run_id"],
                kind="pr" if run_row.kind == "pr" else "repository",
                source_lock=lock,
                toolchain=toolchain,
                skill_registry_sha256=canonical_sha256({"skills": []}),
                config_sha256=canonical_sha256({"workdir": deps.workdir.name}),
                model_ids=[],
                cassette_ids=[],
                inputs={"sourceLock": state["source_lock_sha256"]},
                outputs={
                    "projectGraph": state["graph_sha256"],
                    "cytoscape": state["cytoscape_sha256"],
                    "projectOverview": state["project_overview_sha256"],
                    "graphViews": state["graph_views_sha256"],
                    **(
                        {"baseProjectGraph": state["base_graph_sha256"]}
                        if state.get("base_graph_sha256")
                        else {}
                    ),
                    **(
                        {"project-explanation": narrative_sha}
                        if (narrative_sha := state.get("project_explanation_sha256"))
                        else {}
                    ),
                    **(
                        {"apiChange": api_change_sha}
                        if (api_change_sha := state.get("api_change_sha256"))
                        else {}
                    ),
                    **(
                        {"graphDiff": graph_diff_sha}
                        if (graph_diff_sha := state.get("graph_diff_sha256"))
                        else {}
                    ),
                    **(
                        {"changeImpact": impact_sha}
                        if (impact_sha := state.get("change_impact_sha256"))
                        else {}
                    ),
                    # Keyed by artifact role, so a manifest entry names exactly
                    # what `/api/runs/{id}/artifact/{role}` will serve.
                    **state.get("review_artifacts", {}),
                },
                cost=RunCost(total_prompt_tokens=0, total_completion_tokens=0),
            )
            manifest_bytes = canonical_json(manifest.contract_dump())
            manifest_sha = deps.cas.put(manifest_bytes)
            repo.index_artifact(
                session,
                sha256=manifest_sha,
                kind="run-manifest",
                media_type="application/json",
                size_bytes=len(manifest_bytes),
                producer="pipeline",
                produced_by_run_id=state["run_id"],
                schema_id="run-manifest.v1",
            )
            run_row.manifest_sha256 = manifest_sha
            # A run where a reviewer failed is not a clean bill of health, and its
            # status must not read like one.
            status = "succeeded_with_gaps" if state.get("failed_skills") else "succeeded"
            repo.set_run_status(session, run_id=state["run_id"], status=status)
            session.commit()
        return {"manifest_sha256": manifest_sha}

    builder = StateGraph(PipelineState)
    stages: dict[str, NodeFn] = {
        "source_lock": source_lock,
        "extract": extract,
        "build_graph": build_graph,
        "base_revision": base_revision,
        "graph_diff": graph_diff,
        "api_change": api_change,
        "change_impact": change_impact,
        "project_overview": project_overview,
        "architecture": architecture,
        "narrate": narrate,
        "export_cytoscape": export_cytoscape,
        "review": review,
        "finalize": finalize,
    }
    for stage_name, stage_fn in stages.items():
        # LangGraph's add_node overloads don't accept plain (TypedDict) -> dict
        # callables under strict mypy; runtime behavior is the documented one.
        builder.add_node(stage_name, _wrap(deps, stage_name, stage_fn))  # type: ignore[call-overload]
    builder.add_edge(START, "source_lock")
    builder.add_edge("source_lock", "extract")
    builder.add_edge("extract", "build_graph")
    builder.add_edge("build_graph", "base_revision")
    builder.add_edge("base_revision", "graph_diff")
    builder.add_edge("graph_diff", "api_change")
    builder.add_edge("api_change", "change_impact")
    builder.add_edge("change_impact", "project_overview")
    builder.add_edge("project_overview", "architecture")
    builder.add_edge("architecture", "narrate")
    builder.add_edge("narrate", "export_cytoscape")
    builder.add_edge("export_cytoscape", "review")
    builder.add_edge("review", "finalize")
    builder.add_edge("finalize", END)

    deps.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    import sqlite3

    conn = sqlite3.connect(str(deps.checkpoint_path), check_same_thread=False)
    return builder.compile(checkpointer=SqliteSaver(conn))
