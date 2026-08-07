"""Cross-run finding memory: remembered rejections suppress repeat validation.

ADR-0016. The validator closes every candidate with a reason and used to
forget; re-running on the same repository re-paid an agent call for every
previously-rejected finding. This module remembers **agent-produced rejections
only**, keyed by (repository, semantic fingerprint, file blob sha), and
suppresses a recurring candidate before dispatch — but only while the file is
byte-identical and the cited spans overlap. Any miss fails open into normal
validation: one wasted agent call is the price of a wrong suppression never
hiding a real defect.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from codeatlas.core.canonical import canonical_sha256
from codeatlas.db.tables import FindingMemoryRow
from codeatlas.models.findings import Finding
from codeatlas.models.graph import ProjectGraph

_DEFINITION_KINDS = frozenset({"function", "type", "module", "constant"})


def enclosing_symbol(graph: ProjectGraph, path: str, start_line: int | None) -> str | None:
    """The *smallest* measured definition span containing `start_line`.

    Ties break on the lexicographic node id — two runs must resolve the same
    symbol or the fingerprint silently never matches. None when the line sits
    outside every definition (module-level code) or the finding has no line.
    """
    if start_line is None:
        return None
    best: tuple[int, str] | None = None
    for node in graph.nodes:
        if node.kind not in _DEFINITION_KINDS:
            continue
        loc = node.location
        if loc is None or loc.path != path:
            continue
        if loc.start_line is None or loc.end_line is None:
            continue
        if not (loc.start_line <= start_line <= loc.end_line):
            continue
        key = (loc.end_line - loc.start_line, node.id)
        if best is None or key < best:
            best = key
    return None if best is None else best[1]


def finding_fingerprint(category: str, path: str, symbol: str | None) -> str:
    """Identity that survives code moving and claims being reworded.

    Deliberately excludes line numbers and claim text; the blob sha in the
    memory key (not in the fingerprint) bounds how long a decision may apply.
    """
    return canonical_sha256({"category": category, "path": path, "enclosingSymbol": symbol})


def spans_overlap(
    a_start: int | None, a_end: int | None, b_start: int | None, b_end: int | None
) -> bool:
    """The dedup overlap rule (`rules._span` normalization, tolerance 0)."""
    a0 = a_start or 0
    a1 = a_end or a0
    b0 = b_start or 0
    b1 = b_end or b0
    return a0 <= b1 and b0 <= a1


@dataclass(frozen=True, slots=True)
class RememberedRejection:
    fingerprint: str
    file_blob_sha: str
    start_line: int | None
    end_line: int | None
    reason: str
    decided_in_run: str


@dataclass(frozen=True, slots=True)
class FindingMemory:
    """One repository's remembered rejections, preloaded for a run.

    Pure after `load`: `match` touches no database, so `validate_findings`
    stays testable without a session.
    """

    repository_id: str
    blob_shas: Mapping[str, str]  # path -> git blob sha at the head revision
    graph: ProjectGraph
    rows: Mapping[tuple[str, str], RememberedRejection]  # (fingerprint, blob) -> row

    @classmethod
    def load(
        cls,
        session: Session,
        repository_id: str,
        blob_shas: Mapping[str, str],
        graph: ProjectGraph,
    ) -> FindingMemory:
        rows: dict[tuple[str, str], RememberedRejection] = {}
        stmt = select(FindingMemoryRow).where(FindingMemoryRow.repository_id == repository_id)
        for row in session.scalars(stmt):
            rows[(row.fingerprint, row.file_blob_sha)] = RememberedRejection(
                fingerprint=row.fingerprint,
                file_blob_sha=row.file_blob_sha,
                start_line=row.start_line,
                end_line=row.end_line,
                reason=row.reason,
                decided_in_run=row.decided_in_run,
            )
        return cls(repository_id=repository_id, blob_shas=blob_shas, graph=graph, rows=rows)

    def fingerprint(self, finding: Finding) -> str:
        symbol = enclosing_symbol(self.graph, finding.location.path, finding.location.start_line)
        return finding_fingerprint(finding.category, finding.location.path, symbol)

    def match(self, finding: Finding) -> RememberedRejection | None:
        """A remembered rejection that applies to this candidate, or None.

        Applies only when the file is byte-identical to when the rejection was
        decided (blob sha) and the cited spans overlap — one rejection must not
        silence a different defect in the same function.
        """
        blob = self.blob_shas.get(finding.location.path)
        if blob is None:
            return None
        row = self.rows.get((self.fingerprint(finding), blob))
        if row is None:
            return None
        if not spans_overlap(
            row.start_line,
            row.end_line,
            finding.location.start_line,
            finding.location.end_line,
        ):
            return None
        return row


def remember_rejection(
    session: Session,
    memory: FindingMemory,
    finding: Finding,
    reason: str,
    run_id: str,
) -> None:
    """Append one agent-produced rejection; existing rows are never overwritten.

    `ON CONFLICT DO NOTHING`: two concurrent runs on one repository may race
    the unique key, and same key ⟹ same decision by construction, so the
    first writer wins and the loser's insert is a no-op.
    """
    blob = memory.blob_shas.get(finding.location.path)
    if blob is None:
        return
    stmt = (
        pg_insert(FindingMemoryRow)
        .values(
            repository_id=memory.repository_id,
            fingerprint=memory.fingerprint(finding),
            file_blob_sha=blob,
            path=finding.location.path,
            start_line=finding.location.start_line,
            end_line=finding.location.end_line,
            category=finding.category,
            severity=finding.severity,
            claim=finding.claim,
            reason=reason,
            decided_in_run=run_id,
        )
        .on_conflict_do_nothing(index_elements=["repository_id", "fingerprint", "file_blob_sha"])
    )
    session.execute(stmt)
