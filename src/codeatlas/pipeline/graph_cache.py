"""Reuse of already-computed project graphs, keyed by what produced them.

Analyzing a pull request means extracting two revisions instead of one, and
extraction is the expensive part of a run (rust-analyzer indexes the whole
workspace). The base revision of a pull request, however, is almost always a
commit some earlier run already analyzed — and by ADR-0007 a project graph is a
deterministic function of the revision, the extractor toolchain and our own
normalization code. When all three match, the stored graph *is* the graph that
re-extraction would produce.

That soundness argument is also the design constraint: the key must name all
three inputs. A key missing one of them would serve a stale graph under a fresh
hash, which is the single failure a cache must never have.

Only the **base** revision is served from the cache. The head revision is the
subject of the review, and a review run records its own extractor receipts for
the code it is reviewing rather than inheriting someone else's. A cache entry
keeps the id of the run that produced it, so a reused base graph still leads back
to real receipts.
"""

from __future__ import annotations

import shutil
import subprocess

from sqlalchemy import select
from sqlalchemy.orm import Session

from codeatlas.core.canonical import canonical_sha256
from codeatlas.db.tables import GraphCacheRow

# Bump when graph construction changes shape — normalization, merge rules, id
# derivation. The graph is as much this code's output as the extractors'.
GRAPH_PIPELINE_VERSION = "1.0.0"


def fingerprint_from(
    tool_versions: dict[str, str], pipeline_version: str = GRAPH_PIPELINE_VERSION
) -> str:
    """Hash the full set of producers of a graph. Order-independent."""
    return canonical_sha256(
        {
            "pipelineVersion": pipeline_version,
            "tools": {name: tool_versions[name] for name in sorted(tool_versions)},
        }
    )


def toolchain_fingerprint() -> str:
    """Probe the installed extractor toolchain and fingerprint it.

    Probing costs two `--version` invocations, which is negligible next to the
    extraction it may avoid. A tool that is missing is recorded as absent rather
    than skipped: running with one extractor is a different toolchain, and must
    not collide with a run that had both.
    """
    return fingerprint_from(
        {
            "cargo-metadata": _tool_version("cargo"),
            "rust-analyzer-scip": _tool_version("rust-analyzer"),
        }
    )


def _tool_version(executable: str) -> str:
    path = shutil.which(executable)
    if path is None:
        return "absent"
    try:
        proc = subprocess.run(  # noqa: S603 - fixed executable, list args, no shell
            [path, "--version"], capture_output=True, text=True, timeout=30, check=True
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return f"unavailable: {type(exc).__name__}"
    return proc.stdout.strip()


def lookup(session: Session, revision_id: int, fingerprint: str) -> str | None:
    """The cached graph artifact sha for this revision+toolchain, if any."""
    entry = _entry(session, revision_id, fingerprint)
    return entry.graph_sha256 if entry else None


def lookup_entry(session: Session, revision_id: int, fingerprint: str) -> GraphCacheRow | None:
    """The cache row itself, for callers that need its provenance."""
    return _entry(session, revision_id, fingerprint)


def _entry(session: Session, revision_id: int, fingerprint: str) -> GraphCacheRow | None:
    return session.scalar(
        select(GraphCacheRow).where(
            GraphCacheRow.revision_id == revision_id,
            GraphCacheRow.toolchain_fingerprint == fingerprint,
        )
    )


def remember(
    session: Session,
    revision_id: int,
    fingerprint: str,
    graph_sha256: str,
    produced_by_run_id: str,
) -> None:
    """Record a freshly computed graph. Idempotent; never overwrites.

    An existing entry for the same key is left alone: two runs computing the same
    key must agree by construction, and if they ever did not, silently replacing
    the older entry would erase the evidence of the disagreement.
    """
    if _entry(session, revision_id, fingerprint) is not None:
        return
    session.add(
        GraphCacheRow(
            revision_id=revision_id,
            toolchain_fingerprint=fingerprint,
            graph_sha256=graph_sha256,
            produced_by_run_id=produced_by_run_id,
        )
    )
    session.flush()
