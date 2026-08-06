"""rust-analyzer SCIP extractor: symbols, references, containment, call candidates.

Chosen over live LSP for batch determinism (ADR-0006). The index is parsed with
vendored pinned protobuf bindings. Known limitations are recorded as evidence
confidence/caveats, never hidden: `calls` edges are reference-derived candidates
(confidence 0.9) because macro expansion and dynamic dispatch can add paths the
reference graph cannot see.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codeatlas.core.canonical import sha256_bytes
from codeatlas.core.ids import edge_id
from codeatlas.extractors.base import ExtractorError, GraphFragment, run_receipted
from codeatlas.extractors.rust.scip_pb2 import scip_pb2
from codeatlas.models.graph import Evidence, GraphEdge, GraphNode, NodeKind, SourceLocation
from codeatlas.models.receipts import ExtractorReceipt

_DEFINITION_ROLE = 0x1


class RaScipExtractor:
    name = "rust-analyzer-scip"

    def extract(self, workspace: Path, revision_sha: str) -> tuple[GraphFragment, ExtractorReceipt]:
        ra = shutil.which("rust-analyzer")
        if ra is None:
            raise ExtractorError("rust-analyzer not found on PATH")
        version = _ra_version(ra)

        # Output goes outside the (possibly read-only) workspace.
        with tempfile.TemporaryDirectory(prefix="codeatlas-scip-") as tmp:
            out = Path(tmp) / "index.scip"
            configuration: dict[str, str | float | int | bool | None] = {
                "command": "rust-analyzer scip . --output <tmp>/index.scip",
                "workspace": workspace.name,
            }
            proc, receipt = run_receipted(
                extractor_name=self.name,
                command=[ra, "scip", ".", "--output", str(out)],
                cwd=workspace,
                revision_sha=revision_sha,
                configuration=configuration,
                extractor_version=version,
            )
            if proc.returncode != 0 or not out.exists():
                stderr = proc.stderr.decode("utf-8", "replace")
                raise ExtractorError(
                    f"rust-analyzer scip exited {proc.returncode}: {stderr[:500]}",
                    receipt=receipt,
                )
            index_bytes = out.read_bytes()

        # Record the index hash in the receipt configuration (stdout is progress noise).
        receipt = receipt.model_copy(
            update={"configuration": {**configuration, "indexSha256": sha256_bytes(index_bytes)}}
        )

        index = scip_pb2.Index()  # type: ignore[attr-defined]
        index.ParseFromString(index_bytes)
        fragment = normalize_scip(index, ra_version=version)
        return fragment, receipt


def _ra_version(ra: str) -> str:
    proc = subprocess.run(  # noqa: S603
        [ra, "--version"], capture_output=True, text=True, timeout=30, check=True
    )
    return proc.stdout.strip()


# --- pure normalization -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Definition:
    symbol: str
    path: str  # normalized forward-slash
    start_line: int  # 0-based, from enclosing_range when present
    end_line: int
    node_kind: NodeKind
    display_name: str


# SCIP SymbolInformation.Kind values for things a module can depend on, as
# opposed to a field of a struct. rust-analyzer populates `kind` for every term
# symbol it emits (893 of 893, measured on ripgrep), so this is the tool's own
# classification rather than a guess from the descriptor shape.
#
# Resolved by name from the generated enum, not written as numbers: the first
# attempt hardcoded 79 for StaticVariable, which is actually StaticField, and
# every `static` in the codebase stayed invisible until a reviewer noticed one
# missing edge. The names are in the protocol; the numbers are an implementation
# detail that should never have been retyped.
_CONSTANT_KINDS = frozenset(
    scip_pb2.SymbolInformation.Kind.Value(name)  # type: ignore[attr-defined]
    for name in ("Constant", "StaticVariable")
)


def _classify(symbol: str, kind: int = 0) -> NodeKind | None:
    """Classify a SCIP symbol by its descriptor suffix (stable grammar).

    Term descriptors — a bare trailing `.` — cover constants, statics, struct
    fields and enum variants alike, so the suffix alone cannot separate them.
    Dropping the lot, as this did, silently lost every `const` and `static`:
    on ripgrep that left `printer/src/lib.rs` with no dependents at all despite
    `util.rs` importing its `MAX_LOOK_AHEAD`, and made `default_types.rs` and
    `flags/complete/mod.rs` look like orphans. Five such edges were missed.

    Fields stay out: 803 of ripgrep's 893 term symbols are struct fields, and a
    field is reached through the type that owns it, which is already an edge.
    """
    if symbol.startswith("local "):
        return None
    if symbol.endswith("()."):
        return "function"
    if symbol.endswith("#"):
        return "type"
    if symbol.endswith("/"):
        return "module"
    if symbol.endswith(".") and kind in _CONSTANT_KINDS:
        return "constant"
    return None  # fields, impl blocks, type parameters, meta descriptors


def _display_name(symbol: str, info_names: dict[str, str]) -> str:
    name = info_names.get(symbol, "")
    if name:
        return name
    tail = symbol.rstrip("/#().")
    for sep in ("/", "#", "]", "."):
        if sep in tail:
            tail = tail.rsplit(sep, 1)[-1]
    return tail or symbol


def _ranges(occ: Any) -> tuple[int, int]:
    """(start_line, end_line), 0-based, preferring the enclosing range."""
    r = list(occ.enclosing_range) or list(occ.range)
    start = r[0]
    end = r[2] if len(r) == 4 else r[0]
    return start, end


def normalize_scip(index: Any, ra_version: str) -> GraphFragment:
    """Pure normalization of a SCIP index into a graph fragment."""
    strong = Evidence(
        kind="language-server",
        producer="rust-analyzer",
        producer_version=ra_version,
        confidence=1.0,
    )
    candidate = Evidence(
        kind="language-server",
        producer="rust-analyzer",
        producer_version=ra_version,
        confidence=0.9,
    )

    documents = sorted(index.documents, key=lambda d: d.relative_path.replace("\\", "/"))

    # Pass 1: collect workspace definitions.
    definitions: dict[str, _Definition] = {}
    info_names: dict[str, str] = {}
    info_kinds: dict[str, int] = {}
    for doc in documents:
        for info in doc.symbols:
            if info.display_name:
                info_names[info.symbol] = info.display_name
            if info.kind:
                info_kinds[info.symbol] = info.kind
    for doc in documents:
        path = doc.relative_path.replace("\\", "/")
        for occ in doc.occurrences:
            if not occ.symbol_roles & _DEFINITION_ROLE:
                continue
            kind = _classify(occ.symbol, info_kinds.get(occ.symbol, 0))
            if kind is None or occ.symbol in definitions:
                continue
            start, end = _ranges(occ)
            definitions[occ.symbol] = _Definition(
                symbol=occ.symbol,
                path=path,
                start_line=start,
                end_line=end,
                node_kind=kind,
                display_name=_display_name(occ.symbol, info_names),
            )

    nodes: dict[str, GraphNode] = {}
    edges: dict[str, GraphEdge] = {}

    for doc in documents:
        path = doc.relative_path.replace("\\", "/")
        file_id = f"file:{path}"
        nodes[file_id] = GraphNode(
            id=file_id,
            kind="file",
            label=path,
            language="rust",
            location=SourceLocation(path=path),
            evidence=[strong],
        )

    for defn in definitions.values():
        sym_id = f"sym:scip/{defn.symbol}"
        nodes[sym_id] = GraphNode(
            id=sym_id,
            kind=defn.node_kind,
            label=defn.display_name,
            language="rust",
            location=SourceLocation(
                path=defn.path, start_line=defn.start_line + 1, end_line=defn.end_line + 1
            ),
            evidence=[strong],
        )
        file_id = f"file:{defn.path}"
        eid = edge_id(file_id, "contains", sym_id, None)
        edges[eid] = GraphEdge(
            id=eid, source=file_id, target=sym_id, kind="contains", evidence=[strong]
        )

    # Pass 2: references -> calls candidates and file-level imports.
    for doc in documents:
        path = doc.relative_path.replace("\\", "/")
        file_id = f"file:{path}"
        function_spans = sorted(
            (
                (d.start_line, d.end_line, f"sym:scip/{d.symbol}")
                for d in definitions.values()
                if d.path == path and d.node_kind == "function"
            ),
        )
        for occ in doc.occurrences:
            if occ.symbol_roles & _DEFINITION_ROLE:
                continue
            target_def = definitions.get(occ.symbol)
            if target_def is None:
                continue  # external or unclassified symbol: no node, no edge
            line = occ.range[0]
            enclosing = _innermost_function(function_spans, line)
            target_id = f"sym:scip/{occ.symbol}"
            if enclosing is not None and target_def.node_kind in ("function", "constant"):
                if enclosing != target_id:
                    # A function reaching a constant reads it; reaching another
                    # function calls it. Both are dependencies, and saying which
                    # is which costs nothing.
                    relation = "calls" if target_def.node_kind == "function" else "reads"
                    eid = edge_id(enclosing, relation, target_id, None)
                    edges[eid] = GraphEdge(
                        id=eid,
                        source=enclosing,
                        target=target_id,
                        kind=relation,  # type: ignore[arg-type]
                        evidence=[candidate],
                    )
            elif enclosing is None:
                # Module-level reference (use declarations, signatures at top level).
                eid = edge_id(file_id, "imports", target_id, None)
                edges[eid] = GraphEdge(
                    id=eid, source=file_id, target=target_id, kind="imports", evidence=[strong]
                )

    fragment = GraphFragment(nodes=list(nodes.values()), edges=list(edges.values()))
    fragment.sort()
    return fragment


def _innermost_function(spans: list[tuple[int, int, str]], line: int) -> str | None:
    """Innermost function whose (0-based) span contains `line`."""
    best: tuple[int, str] | None = None
    for start, end, sym in spans:
        if start <= line <= end:
            size = end - start
            if best is None or size < best[0]:
                best = (size, sym)
    return best[1] if best else None
