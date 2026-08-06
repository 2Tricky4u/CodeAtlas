"""Print a run's stage timeline, findings and artifacts — the operator's view.

Usage:
  uv run python scripts/show_run.py            # most recent run
  uv run python scripts/show_run.py <run-id>
"""

from __future__ import annotations

import json
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session


def main(run_id: str | None) -> int:
    from codeatlas.artifacts.store import ArtifactStore
    from codeatlas.db.session import app_engine
    from codeatlas.db.tables import (
        AgentInvocationRow,
        ExtractorReceiptRow,
        FindingRow,
        GraphSnapshotRow,
        RunRow,
    )

    engine = app_engine()
    with Session(engine) as s:
        run = (
            s.get(RunRow, run_id)
            if run_id
            else s.scalars(select(RunRow).order_by(RunRow.id.desc()).limit(1)).first()
        )
        if run is None:
            print("no run found", file=sys.stderr)
            return 1

        print(f"run {run.id}  status={run.status}  repo={run.repository_id}  kind={run.kind}")
        print()

        print("stages:")
        for event in run.events:
            mark = "!" if event.level == "error" else " "
            print(f" {mark} {event.stage:<18} {event.event}")
            if event.level == "error" and event.data:
                print(f"      {str(event.data.get('error'))[:200]}")

        receipts = s.scalars(
            select(ExtractorReceiptRow).where(ExtractorReceiptRow.run_id == run.id)
        ).all()
        print(f"\nreceipts ({len(receipts)}):")
        for receipt in receipts:
            print(
                f"  {receipt.extractor:<20} exit={receipt.exit_code}  {receipt.extractor_version}"
            )

        snapshots = s.scalars(
            select(GraphSnapshotRow)
            .where(GraphSnapshotRow.run_id == run.id)
            .order_by(GraphSnapshotRow.role.desc())
        ).all()
        for snapshot in snapshots:
            print(
                f"\ngraph ({snapshot.role}): {snapshot.node_count} nodes, "
                f"{snapshot.edge_count} edges, hash {snapshot.canonical_sha256[7:19]}"
            )

        invocations = s.scalars(
            select(AgentInvocationRow).where(AgentInvocationRow.run_id == run.id)
        ).all()
        if invocations:
            tokens = sum(i.prompt_tokens + i.completion_tokens for i in invocations)
            print(f"\nagent invocations ({len(invocations)}, {tokens:,} tokens):")
            for inv in invocations:
                print(
                    f"  {inv.skill_id:<24} {inv.status:<12} "
                    f"{inv.prompt_tokens + inv.completion_tokens:>7,} tok  {inv.duration_ms:>6} ms"
                )

        findings = s.scalars(select(FindingRow).where(FindingRow.run_id == run.id)).all()
        if findings:
            print(f"\nfindings ({len(findings)}):")
            for f in sorted(findings, key=lambda x: x.finding_id):
                flag = "PUBLISHABLE" if f.publication_eligible else ""
                dup = f" -> {f.duplicate_of}" if f.duplicate_of else ""
                print(
                    f"  {f.finding_id} [{f.category:<12}] {f.severity:<8} {f.status:<10}{dup:<10} "
                    f"{f.path}:{f.start_line} {flag}"
                )
                print(f"      {f.claim[:110]}")

        if run.manifest_sha256:
            cas = ArtifactStore(_workdir_for(run) / "objects")
            try:
                manifest = json.loads(cas.get(run.manifest_sha256))
            except (KeyError, ValueError):
                print(f"\nmanifest: {run.manifest_sha256} (object store not at the default path)")
            else:
                print("\nmanifest outputs:")
                for name, sha in sorted(manifest["outputs"].items()):
                    print(f"  {name:<22} {sha[7:19]}")
    return 0


def _workdir_for(run: object):  # type: ignore[no-untyped-def]
    from pathlib import Path

    for candidate in (Path("var/e2e"), Path("var")):
        if (candidate / "objects").is_dir():
            return candidate
    return Path("var")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else None))
