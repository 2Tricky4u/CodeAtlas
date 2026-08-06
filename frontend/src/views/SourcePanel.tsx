// Pinned source viewer: the drill-down target for every citation and finding.
// Lines come from `git cat-file` on the bare mirror, path-allowlisted per
// revision server-side — the panel renders what the evidence points at.
//
// Lines where the graph knows a symbol is *defined* carry a link to that
// symbol's page, with its fan-in inline — so reading a file tells you which of
// its definitions matter. Nothing else is linked: an identifier the graph has
// no node for stays plain text, and the panel says so once rather than
// implying full coverage. A link here means something was measured.

import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, type SourceSlice } from "../api";
import { graphIndex, type GraphIndex, type GraphNode } from "../graph";
import { Panel } from "../ui";
import { SymbolLink } from "./links";

export interface SourceRequest {
  revision: string;
  path: string;
  startLine?: number;
  endLine?: number;
}

const CONTEXT = 6;

export function SourcePanel({
  request,
  onClose,
}: {
  request: SourceRequest | null;
  onClose: () => void;
}) {
  const { runId } = useParams();
  const [slice, setSlice] = useState<SourceSlice | null>(null);
  const [index, setIndex] = useState<GraphIndex | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setSlice(null);
    setError(null);
    if (!request) return;
    const start = Math.max(1, (request.startLine ?? 1) - CONTEXT);
    const end = request.endLine ? request.endLine + CONTEXT : request.startLine ? request.startLine + CONTEXT * 2 : undefined;
    api
      .source(request.revision, request.path, start, end)
      .then(setSlice)
      .catch((e: Error) => setError(e.message));
    // Same memoised index every other view shares — no extra fetch after the first.
    if (runId) graphIndex(runId).then(setIndex).catch(() => setIndex(null));
  }, [request, runId]);

  if (!request) return null;

  const highlightFrom = request.startLine ?? -1;
  const highlightTo = request.endLine ?? request.startLine ?? -1;

  const definedAt = new Map<number, GraphNode>();
  if (slice && index) {
    for (const symbol of index.definitionsInRange(
      request.path,
      slice.startLine,
      slice.startLine + slice.lines.length - 1,
    )) {
      if (symbol.startLine !== undefined) definedAt.set(symbol.startLine, symbol);
    }
  }

  return (
    <Panel
      title={request.path}
      count={`@ ${request.revision.slice(0, 10)}`}
      actions={
        <button onClick={onClose} className="note" aria-label="close source">
          ✕ close
        </button>
      }
      style={{ marginTop: 12 }}
    >
      {error && <p style={{ color: "var(--bad)" }}>{error}</p>}
      {!slice && !error && <p className="note">loading…</p>}
      {slice && (
        <>
          <div className="codeblock" data-testid="source-panel">
            {slice.lines.map((line, lineIndex) => {
              const number = slice.startLine + lineIndex;
              const highlighted = number >= highlightFrom && number <= highlightTo;
              const symbol = definedAt.get(number);
              return (
                <div key={number} className={`line ${highlighted ? "hl" : ""}`}>
                  <span className="ln mono-num">{number}</span>
                  <span>{line || " "}</span>
                  {symbol && (
                    <SymbolLink
                      id={symbol.id}
                      path={request.path}
                      className="badge accent defmark"
                      title={`${symbol.kind} · used by ${
                        index?.usedBy(symbol.id).length ?? 0
                      }`}
                    >
                      <span data-testid="source-symbol">
                        {symbol.label} ← {index?.usedBy(symbol.id).length ?? 0}
                      </span>
                    </SymbolLink>
                  )}
                </div>
              );
            })}
          </div>
          {definedAt.size > 0 && (
            <p className="note" style={{ marginBottom: 0 }} data-testid="source-link-note">
              marked lines define a symbol the graph measured; its count is how many
              symbols use it. Everything else is plain text, not unlinked on purpose —
              the graph simply has no node for it.
            </p>
          )}
        </>
      )}
    </Panel>
  );
}
