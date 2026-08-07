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
import { KindDot, Panel } from "../ui";
import { kindColor } from "./layout";
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
  // Which measured definition covers each line — its whole span, not just the
  // first line, so the reader sees where a function begins and ends. Later
  // (inner) definitions overwrite outer ones, so a method colours as itself
  // rather than as the impl block around it. Only measured spans get colour:
  // a highlighter colours text it guessed at.
  const spanAt = new Map<number, GraphNode>();
  if (slice && index) {
    const sliceEnd = slice.startLine + slice.lines.length - 1;
    for (const symbol of index.definitionsInRange(request.path, slice.startLine, sliceEnd)) {
      if (symbol.startLine === undefined) continue;
      definedAt.set(symbol.startLine, symbol);
      const spanEnd = Math.min(symbol.endLine ?? symbol.startLine, sliceEnd);
      for (let line = symbol.startLine; line <= spanEnd; line += 1) {
        spanAt.set(line, symbol);
      }
    }
  }
  const spanKinds = [...new Set([...spanAt.values()].map((symbol) => symbol.kind))].sort();

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
              const covering = spanAt.get(number);
              return (
                <div
                  key={number}
                  className={`line ${highlighted ? "hl" : ""} ${covering ? "defspan" : ""}`}
                  data-testid={covering ? "source-span" : undefined}
                  title={covering ? `${covering.kind} ${covering.label}` : undefined}
                  style={
                    covering
                      ? { borderLeft: `2px solid ${kindColor(covering.kind)}` }
                      : { borderLeft: "2px solid transparent" }
                  }
                >
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
              coloured spans are measured definitions —{" "}
              {spanKinds.map((kind) => (
                <span key={kind} style={{ marginRight: 8 }}>
                  <KindDot kind={kind} /> {kind}
                </span>
              ))}
              — and the badge's count is how many symbols use it. Everything else is
              plain text, not unlinked on purpose — the graph simply has no node for it.
            </p>
          )}
        </>
      )}
    </Panel>
  );
}
