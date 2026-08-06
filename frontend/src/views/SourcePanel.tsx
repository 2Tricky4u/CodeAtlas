// Pinned source viewer: the drill-down target for every citation and finding.
// Lines come from `git cat-file` on the bare mirror, path-allowlisted per
// revision server-side — the panel just renders what the evidence points at.

import { useEffect, useState } from "react";
import { api, type SourceSlice } from "../api";
import { Panel } from "../ui";

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
  const [slice, setSlice] = useState<SourceSlice | null>(null);
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
  }, [request]);

  if (!request) return null;

  const highlightFrom = request.startLine ?? -1;
  const highlightTo = request.endLine ?? request.startLine ?? -1;

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
        <div className="codeblock" data-testid="source-panel">
          {slice.lines.map((line, index) => {
            const number = slice.startLine + index;
            const highlighted = number >= highlightFrom && number <= highlightTo;
            return (
              <div key={number} className={`line ${highlighted ? "hl" : ""}`}>
                <span className="ln mono-num">{number}</span>
                <span>{line || " "}</span>
              </div>
            );
          })}
        </div>
      )}
    </Panel>
  );
}
