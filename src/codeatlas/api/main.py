"""Read-only FastAPI application.

Strictly GET-only: the dashboard can inspect everything and change nothing.
Approval decisions happen exclusively through the CLI (ADR-0011). Pinned source
is served from the bare mirrors via `git cat-file`, with the requested path
validated against the `file` table for that revision — no filesystem access.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from codeatlas.artifacts.store import ArtifactStore
from codeatlas.db.tables import (
    ArtifactRow,
    FileRow,
    GraphSnapshotRow,
    RevisionRow,
    RunRow,
)
from codeatlas.vcs.git import GitClient, GitError

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_ARTIFACT_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ROLE_RE = re.compile(r"^[a-z][a-z0-9-]{0,59}$")
# Served as text rather than JSON. Deliberately an allowlist: this endpoint must
# never become a way to stream arbitrary stored bytes.
_TEXT_MEDIA = frozenset({"text/plain", "text/markdown"})


def create_app(
    engine: Engine,
    cas: ArtifactStore,
    mirrors: Path,
    ask_deps: object | None = None,
) -> FastAPI:
    """The dashboard's API.

    ADR-0014: no external writes, no approval decisions. `ask_deps` — a
    `PipelineDeps` with an agent engine — enables the one local-analysis
    endpoint; absent (the default), the app is exactly as GET-only as before.
    """
    app = FastAPI(title="CodeAtlas", version="0.1.0", docs_url="/api/docs")
    # Kept on the app so a caller can reach the store the routes were built
    # over without reconstructing it from a path and guessing the layout.
    app.state.cas = cas
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    def session() -> Iterator[Session]:  # pragma: no cover - generator plumbing
        with Session(engine) as s:
            yield s

    @app.get("/api/runs")
    def list_runs(s: Session = Depends(session)) -> list[dict[str, object]]:  # noqa: B008
        rows = s.scalars(select(RunRow).order_by(RunRow.id.desc()).limit(100)).all()
        return [_run_summary(s, r) for r in rows]

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: str, s: Session = Depends(session)) -> dict[str, object]:  # noqa: B008
        run = s.get(RunRow, run_id)
        if run is None:
            raise HTTPException(404, "unknown run")
        detail = _run_summary(s, run)
        detail["events"] = [
            {
                "stage": e.stage,
                "event": e.event,
                "level": e.level,
                "at": e.at.isoformat(),
                "data": e.data,
            }
            for e in run.events
        ]
        detail["receipts"] = [r.payload for r in run.receipts]
        return detail

    @app.get("/api/runs/{run_id}/graph")
    def run_graph(run_id: str, s: Session = Depends(session)) -> dict[str, object]:  # noqa: B008
        run = s.get(RunRow, run_id)
        if run is None:
            raise HTTPException(404, "unknown run")
        # Membership, not producer: identical content is shared between runs, so
        # a repeat run's graph is attributed to whichever run first produced it.
        from codeatlas.db.repositories import artifact_for_run

        sha = artifact_for_run(s, run_id, "cytoscape-elements")
        if sha is None:
            raise HTTPException(404, "no graph artifact for this run")
        return json.loads(cas.get(sha))  # type: ignore[no-any-return]

    @app.get("/api/runs/{run_id}/overview")
    def run_overview(run_id: str, s: Session = Depends(session)) -> dict[str, object]:  # noqa: B008
        """What this project is: entry points, levels, cycles, where to start."""
        from codeatlas.db.repositories import artifact_for_run

        if s.get(RunRow, run_id) is None:
            raise HTTPException(404, "unknown run")
        sha = artifact_for_run(s, run_id, "project-overview")
        if sha is None:
            raise HTTPException(404, "no project overview for this run")
        return json.loads(cas.get(sha))  # type: ignore[no-any-return]

    @app.get("/api/runs/{run_id}/artifact/{role}")
    def run_artifact(
        run_id: str,
        role: str,
        s: Session = Depends(session),  # noqa: B008
    ) -> object:
        """One of this run's JSON artifacts, addressed by its role.

        Roles are membership rows this run actually owns (`run_artifact`), so
        the endpoint can never serve another run's content, and an arbitrary
        role string is simply not found rather than an error to reason about.
        """
        from codeatlas.db.repositories import artifact_for_run

        if not _ROLE_RE.match(role):
            raise HTTPException(400, "malformed artifact role")
        if s.get(RunRow, run_id) is None:
            raise HTTPException(404, "unknown run")
        sha = artifact_for_run(s, run_id, role)
        if sha is None:
            raise HTTPException(404, f"this run has no {role!r} artifact")
        row = s.get(ArtifactRow, sha)
        if row is None:
            raise HTTPException(404, f"this run has no {role!r} artifact")
        if row.media_type == "application/json":
            return json.loads(cas.get(sha))
        # Text artifacts — the Structurizr DSL, the rendered review — are read
        # as text, not as a JSON string. Anything outside this allowlist is
        # refused rather than streamed: the API never hands back arbitrary bytes.
        if row.media_type in _TEXT_MEDIA:
            return PlainTextResponse(
                cas.get(sha).decode("utf-8", "replace"), media_type=row.media_type
            )
        raise HTTPException(415, f"{row.media_type} is not servable")

    @app.get("/api/runs/{run_id}/findings")
    def run_findings(run_id: str, s: Session = Depends(session)) -> list[dict[str, object]]:  # noqa: B008
        from codeatlas.db.tables import FindingRow

        if s.get(RunRow, run_id) is None:
            raise HTTPException(404, "unknown run")
        rows = s.scalars(
            select(FindingRow).where(FindingRow.run_id == run_id).order_by(FindingRow.finding_id)
        ).all()
        return [
            {
                "findingId": r.finding_id,
                "category": r.category,
                "severity": r.severity,
                "confidence": r.confidence,
                "claim": r.claim,
                "path": r.path,
                "startLine": r.start_line,
                "endLine": r.end_line,
                "status": r.status,
                "publicationEligible": r.publication_eligible,
                "introducedByChange": r.introduced_by_change,
                "discoveredBySkill": r.discovered_by_skill,
                "validation": r.validation,
            }
            for r in rows
        ]

    @app.get("/api/runs/{run_id}/approval")
    def run_approval(run_id: str, s: Session = Depends(session)) -> list[dict[str, object]]:  # noqa: B008
        """Publication approvals for this run, decided or not.

        The gate is what stands between an analysis and a comment on someone's
        pull request, and it was invisible here: a reader could see findings and
        a payload but not whether anyone had agreed to send it. `decision` being
        null is the important state, not an incomplete one.
        """
        from codeatlas.db.tables import ApprovalRow

        if s.get(RunRow, run_id) is None:
            raise HTTPException(404, "unknown run")
        rows = s.scalars(
            select(ApprovalRow)
            .where(ApprovalRow.run_id == run_id)
            .order_by(ApprovalRow.requested_at)
        ).all()
        return [
            {
                "id": r.id,
                "actionKind": r.action_kind,
                "payloadSha256": r.payload_sha256,
                "requestedAt": r.requested_at.isoformat(),
                "decidedAt": r.decided_at.isoformat() if r.decided_at else None,
                "decidedBy": r.decided_by,
                "decision": r.decision,
            }
            for r in rows
        ]

    @app.get("/api/runs/{run_id}/views")
    def run_views(run_id: str, s: Session = Depends(session)) -> dict[str, object]:  # noqa: B008
        """Bounded, readable views of the project graph, with refusals stated."""
        from codeatlas.db.repositories import artifact_for_run

        if s.get(RunRow, run_id) is None:
            raise HTTPException(404, "unknown run")
        sha = artifact_for_run(s, run_id, "graph-views")
        if sha is None:
            raise HTTPException(404, "no graph views for this run")
        return json.loads(cas.get(sha))  # type: ignore[no-any-return]

    @app.get("/api/source/{revision_sha}")
    def source(
        revision_sha: str,
        path: str = Query(min_length=1),
        start: int = Query(default=1, ge=1),
        end: int | None = Query(default=None, ge=1),
        s: Session = Depends(session),  # noqa: B008
    ) -> dict[str, object]:
        if not _SHA_RE.match(revision_sha):
            raise HTTPException(400, "malformed revision sha")
        revision = s.scalar(select(RevisionRow).where(RevisionRow.sha == revision_sha))
        if revision is None:
            raise HTTPException(404, "unknown revision")
        # Path allowlist: must exist in the file table at this revision. This is
        # the traversal defense — arbitrary strings simply aren't known paths.
        file_row = s.scalar(
            select(FileRow).where(FileRow.revision_id == revision.id, FileRow.path == path)
        )
        if file_row is None:
            raise HTTPException(404, "path not present at this revision")

        mirror = _mirror_for(s, mirrors, revision)
        if mirror is None:
            raise HTTPException(404, "no mirror for this repository")
        try:
            blob = GitClient().cat_file(mirror, file_row.git_blob_sha)
        except GitError as exc:
            raise HTTPException(500, f"git error: {exc}") from exc
        lines = blob.decode("utf-8", "replace").splitlines()
        end_line = min(end if end is not None else len(lines), len(lines))
        if start > len(lines):
            raise HTTPException(400, "start beyond end of file")
        return {
            "revision": revision_sha,
            "path": path,
            "startLine": start,
            "endLine": end_line,
            "lines": lines[start - 1 : end_line],
        }

    @app.post("/api/runs/{run_id}/ask")
    def ask(
        run_id: str,
        body: dict[str, str],
        s: Session = Depends(session),  # noqa: B008
    ) -> object:
        """Ask one question about one module; get a cited answer or a refusal.

        The single local-analysis endpoint ADR-0014 permits. It spends agent
        quota and stores an artifact; it has no path to publication or
        approval. Answers are cached by (revision, scope, question), so asking
        twice costs once.
        """
        import os

        # The same switch that stops every other agent invocation.
        if os.environ.get("CODEATLAS_KILL_SWITCH"):
            raise HTTPException(503, "agent invocations are disabled by the kill switch")
        if ask_deps is None:
            raise HTTPException(403, "asking is not enabled on this server; start it with --ask")

        scope = (body.get("scope") or "").strip()
        question = (body.get("question") or "").strip()
        if not scope or not question:
            raise HTTPException(422, "both 'scope' and 'question' are required")
        if len(question) > 2000:
            raise HTTPException(422, "question too long")

        run = s.get(RunRow, run_id)
        if run is None:
            raise HTTPException(404, "unknown run")
        head = s.get(RevisionRow, run.head_revision_id)
        if head is None:
            # Unreachable while head_revision_id is non-nullable, but a bare
            # assert here would strip under -O and crash as a 500 if the
            # schema ever relaxes. Typed, like every other refusal.
            raise HTTPException(409, "run has no locked head revision")

        # The scope must be a path this revision actually has — the same
        # allowlist /api/source enforces.
        if not s.scalar(
            select(FileRow).where(FileRow.revision_id == head.id, FileRow.path == scope)
        ):
            raise HTTPException(404, f"{scope} is not a path at this revision")

        from codeatlas.api.ask import answer_or_cached

        return answer_or_cached(
            ask_deps,  # type: ignore[arg-type]
            run_id=run_id,
            revision_sha=head.sha,
            revision_db_id=head.id,
            repository_id=run.repository_id,
            scope=scope,
            question=question,
        )

    @app.get("/api/artifacts/{ref}")
    def artifact(ref: str, s: Session = Depends(session)) -> object:  # noqa: B008
        if not _ARTIFACT_RE.match(ref):
            raise HTTPException(400, "malformed artifact ref")
        row = s.get(ArtifactRow, ref)
        if row is None:
            raise HTTPException(404, "unknown artifact")
        data = cas.get(ref)
        if row.media_type == "application/json":
            return json.loads(data)
        raise HTTPException(415, "artifact is not JSON-servable via this endpoint")

    return app


def _run_summary(s: Session, run: RunRow) -> dict[str, object]:
    head = s.get(RevisionRow, run.head_revision_id)
    base = s.get(RevisionRow, run.base_revision_id) if run.base_revision_id else None
    # A pull-request run holds two snapshots; "the graph" here means the head.
    snapshot = s.scalar(
        select(GraphSnapshotRow).where(
            GraphSnapshotRow.run_id == run.id, GraphSnapshotRow.role == "head"
        )
    )
    base_snapshot = (
        s.scalar(
            select(GraphSnapshotRow).where(
                GraphSnapshotRow.run_id == run.id, GraphSnapshotRow.role == "base"
            )
        )
        if base
        else None
    )
    return {
        "id": run.id,
        "repositoryId": run.repository_id,
        "kind": run.kind,
        "status": run.status,
        "headSha": head.sha if head else None,
        "baseSha": base.sha if base else None,
        "prNumber": run.pr_number,
        "createdAt": run.created_at.isoformat(),
        "manifestSha256": run.manifest_sha256,
        "graph": _graph_summary(snapshot),
        "baseGraph": _graph_summary(base_snapshot),
    }


def _graph_summary(snapshot: GraphSnapshotRow | None) -> dict[str, object] | None:
    if snapshot is None:
        return None
    return {
        "snapshotId": snapshot.id,
        "nodeCount": snapshot.node_count,
        "edgeCount": snapshot.edge_count,
        "canonicalSha256": snapshot.canonical_sha256,
    }


def _mirror_for(s: Session, mirrors: Path, revision: RevisionRow) -> Path | None:
    candidate = mirrors / (revision.repository_id.replace("/", "_") + ".git")
    return candidate if candidate.exists() else None
