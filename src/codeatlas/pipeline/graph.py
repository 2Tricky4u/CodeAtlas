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
from codeatlas.pipeline.deps import PipelineDeps
from codeatlas.pipeline.state import PipelineState
from codeatlas.vcs.source_lock import build_source_lock

log = get_logger("codeatlas.pipeline")

NodeFn = Callable[[PipelineState], dict[str, Any]]


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
        repo_path = Path(state["repo_path"])
        repository_id = state["repository_id"]
        ref = state.get("ref", "HEAD")

        head_sha = deps.git.resolve_sha(repo_path, ref)
        mirror = deps.mirrors / (repository_id.replace("/", "_") + ".git")
        if not mirror.exists():
            deps.git.mirror_clone(str(repo_path), mirror)
        else:
            deps.git.fetch(mirror)
        checkout = deps.checkouts / head_sha
        if not checkout.exists():
            deps.git.pinned_checkout(mirror, head_sha, checkout)

        lock: SourceLock = build_source_lock(
            mirror, repository_id=repository_id, head_ref=head_sha, git=deps.git
        )
        lock_sha = deps.cas.put(canonical_json(lock.contract_dump()))

        with Session(deps.engine) as session:
            revision = repo.ensure_revision(
                session, repository_id=repository_id, sha=head_sha, ref_name=ref
            )
            run_row = repo.get_run(session, state["run_id"])
            if run_row is None:
                raise StageFailure("source_lock", f"run {state['run_id']} not found")
            run_row.head_revision_id = revision.id
            run_row.status = "running"
            repo.index_artifact(
                session,
                sha256=lock_sha,
                kind="source-lock",
                media_type="application/json",
                size_bytes=len(canonical_json(lock.contract_dump())),
                producer="pipeline",
                produced_by_run_id=state["run_id"],
            )
            # file table: full tree at revision (idempotent — revisions are immutable)
            from sqlalchemy import func as sa_func
            from sqlalchemy import select as sa_select

            from codeatlas.db.tables import FileRow
            from codeatlas.vcs.source_lock import classify_generated

            existing = session.scalar(
                sa_select(sa_func.count())
                .select_from(FileRow)
                .where(FileRow.revision_id == revision.id)
            )
            if not existing:
                entries = deps.git.ls_tree(mirror, head_sha)
                generated = set(classify_generated([e.path for e in entries]))
                for entry in entries:
                    session.add(
                        FileRow(
                            revision_id=revision.id,
                            path=entry.path,
                            git_blob_sha=entry.blob_sha,
                            language="rust" if entry.path.endswith(".rs") else None,
                            is_generated=entry.path in generated,
                        )
                    )
            session.commit()
            revision_db_id = revision.id

        return {
            "head_sha": head_sha,
            "revision_db_id": revision_db_id,
            "checkout_path": str(checkout),
            "source_lock_sha256": lock_sha,
        }

    def extract(state: PipelineState) -> dict[str, Any]:
        checkout = Path(state["checkout_path"])
        head_sha = state["head_sha"]
        fragment_shas: list[str] = []
        count = 0
        for extractor in (CargoMetadataExtractor(), RaScipExtractor()):
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
        with Session(deps.engine) as session:
            from sqlalchemy import select

            from codeatlas.db.tables import FileRow

            valid_paths = set(
                session.scalars(
                    select(FileRow.path).where(FileRow.revision_id == state["revision_db_id"])
                )
            )
        violations = validate_graph(graph, valid_paths=valid_paths)
        if violations:
            raise StageFailure(
                "build_graph",
                f"{len(violations)} constraint violations: " + "; ".join(violations[:5]),
            )

        dump = graph.contract_dump()
        graph_bytes = canonical_json(dump)
        graph_sha = deps.cas.put(graph_bytes)
        with Session(deps.engine) as session:
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
            )
            session.commit()
            snapshot_id = snapshot.id
        return {"graph_snapshot_id": snapshot_id, "graph_sha256": graph_sha}

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

    def finalize(state: PipelineState) -> dict[str, Any]:
        with Session(deps.engine) as session:
            run_row = repo.get_run(session, state["run_id"])
            if run_row is None:
                raise StageFailure("finalize", "run row disappeared")
            toolchain = {r.extractor: r.extractor_version for r in run_row.receipts}
            lock = SourceLock.model_validate(json.loads(deps.cas.get(state["source_lock_sha256"])))
            manifest = RunManifest(
                run_id=state["run_id"],
                kind="repository",
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
            repo.set_run_status(session, run_id=state["run_id"], status="succeeded")
            session.commit()
        return {"manifest_sha256": manifest_sha}

    builder = StateGraph(PipelineState)
    builder.add_node("source_lock", _wrap(deps, "source_lock", source_lock))
    builder.add_node("extract", _wrap(deps, "extract", extract))
    builder.add_node("build_graph", _wrap(deps, "build_graph", build_graph))
    builder.add_node("export_cytoscape", _wrap(deps, "export_cytoscape", export_cytoscape))
    builder.add_node("finalize", _wrap(deps, "finalize", finalize))
    builder.add_edge(START, "source_lock")
    builder.add_edge("source_lock", "extract")
    builder.add_edge("extract", "build_graph")
    builder.add_edge("build_graph", "export_cytoscape")
    builder.add_edge("export_cytoscape", "finalize")
    builder.add_edge("finalize", END)

    deps.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    import sqlite3

    conn = sqlite3.connect(str(deps.checkpoint_path), check_same_thread=False)
    return builder.compile(checkpointer=SqliteSaver(conn))
