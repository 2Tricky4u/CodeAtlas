"""Load a RunSnapshot from the evidence store, for comparison and reporting."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from codeatlas.db.tables import (
    AgentInvocationRow,
    ExtractorReceiptRow,
    FindingRow,
    GraphSnapshotRow,
    RevisionRow,
    RunRow,
)
from codeatlas.observability.compare import RunSnapshot


def load_snapshot(session: Session, run_id: str) -> RunSnapshot | None:
    run = session.get(RunRow, run_id)
    if run is None:
        return None

    revision = session.get(RevisionRow, run.head_revision_id)
    # The head snapshot explicitly. A pull-request run also holds a base
    # snapshot, and comparing two runs' *base* graphs would report a changed
    # head as reproducible — a false all-clear, which is worse than no answer.
    graph = session.scalar(
        select(GraphSnapshotRow).where(
            GraphSnapshotRow.run_id == run_id, GraphSnapshotRow.role == "head"
        )
    )
    receipts = session.scalars(
        select(ExtractorReceiptRow).where(ExtractorReceiptRow.run_id == run_id)
    ).all()
    findings = session.scalars(select(FindingRow).where(FindingRow.run_id == run_id)).all()

    tokens = session.execute(
        select(
            func.coalesce(func.sum(AgentInvocationRow.prompt_tokens), 0),
            func.coalesce(func.sum(AgentInvocationRow.completion_tokens), 0),
            func.sum(AgentInvocationRow.cost_usd),
        ).where(AgentInvocationRow.run_id == run_id)
    ).one()

    statuses: dict[str, int] = {}
    suppressed_count = 0
    for finding in findings:
        status = finding.status
        if status == "suppressed":
            # ADR-0016: a suppression replays an earlier rejection; folding it
            # keeps two runs at one revision comparing as reproducible.
            status = "rejected"
            suppressed_count += 1
        statuses[status] = statuses.get(status, 0) + 1

    return RunSnapshot(
        run_id=run.id,
        revision_sha=revision.sha if revision else "",
        graph_sha256=graph.canonical_sha256 if graph else None,
        toolchain={r.extractor: r.extractor_version for r in receipts},
        finding_ids=sorted(f.finding_id for f in findings),
        publishable_ids=sorted(f.finding_id for f in findings if f.publication_eligible),
        statuses=statuses,
        suppressed_count=suppressed_count,
        skill_registry_sha256=run.skill_registry_sha256,
        prompt_tokens=int(tokens[0] or 0),
        completion_tokens=int(tokens[1] or 0),
        cost_usd=float(tokens[2]) if tokens[2] is not None else None,
    )
