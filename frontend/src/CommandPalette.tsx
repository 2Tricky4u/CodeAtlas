// ⌘K / Ctrl-K from any tab: search everything the graph measured, land on the
// page that explains it. Modules land on their module page; symbols land on
// their definition, expanded. The ranking is the same rankMatches focus mode
// and path-finding use — one search behaviour everywhere.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { graphIndex, type GraphIndex, type GraphNode } from "./graph";
import { KindDot } from "./ui";
import { rankMatches } from "./views/layout";
import { modulePath } from "./views/links";

export function CommandPalette() {
  const { runId } = useParams();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState<GraphIndex | null>(null);
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((wasOpen) => !wasOpen);
      }
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (!open || !runId) return;
    setQuery("");
    setCursor(0);
    graphIndex(runId).then(setIndex).catch(() => setIndex(null));
    // The palette just opened; the input exists after this render.
    setTimeout(() => inputRef.current?.focus(), 0);
  }, [open, runId]);

  const matches = useMemo(
    () => (index ? rankMatches(index.nodes, query, 12) : []),
    [index, query],
  );

  const go = useCallback(
    (node: GraphNode) => {
      if (!runId) return;
      setOpen(false);
      if (node.kind === "file" && node.path) {
        navigate(modulePath(runId, node.path));
      } else if (node.path) {
        // A symbol: its module page, with the definition expanded.
        navigate(`${modulePath(runId, node.path)}?symbol=${encodeURIComponent(node.id)}`);
      } else if (index) {
        const file = index.fileOf(node.id);
        if (file?.path) {
          navigate(`${modulePath(runId, file.path)}?symbol=${encodeURIComponent(node.id)}`);
        }
      }
    },
    [runId, navigate, index],
  );

  if (!open || !runId) return null;

  return (
    <div
      onClick={() => setOpen(false)}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(6, 9, 15, 0.6)",
        zIndex: 60,
        display: "flex",
        justifyContent: "center",
        alignItems: "flex-start",
        paddingTop: "12vh",
      }}
      data-testid="palette-backdrop"
    >
      <div
        onClick={(event) => event.stopPropagation()}
        className="panel"
        style={{ width: "min(560px, 92vw)", padding: 10 }}
        data-testid="palette"
      >
        <input
          ref={inputRef}
          type="search"
          placeholder="jump to a module or symbol…"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setCursor(0);
          }}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              // max(…, 0): with zero matches, min(c+1, -1) would park the
              // cursor below the list and desync the highlight.
              setCursor((c) => Math.min(c + 1, Math.max(matches.length - 1, 0)));
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              setCursor((c) => Math.max(c - 1, 0));
            } else if (event.key === "Enter" && matches[cursor]) {
              go(matches[cursor]!);
            }
          }}
          data-testid="palette-input"
          style={{
            width: "100%",
            padding: "8px 11px",
            background: "var(--bg-0)",
            border: "1px solid var(--border-strong)",
            borderRadius: 6,
            color: "var(--fg-0)",
            font: "inherit",
          }}
        />
        {query.length >= 2 && (
          <ul style={{ listStyle: "none", margin: "8px 0 0", padding: 0 }}>
            {matches.length === 0 && (
              <li className="note" style={{ padding: "4px 6px" }}>
                nothing in this run's graph matches
              </li>
            )}
            {matches.map((node, position) => (
              <li key={node.id}>
                <button
                  onClick={() => go(node)}
                  onMouseEnter={() => setCursor(position)}
                  data-testid="palette-match"
                  style={{
                    display: "flex",
                    gap: 8,
                    alignItems: "baseline",
                    width: "100%",
                    textAlign: "left",
                    padding: "5px 8px",
                    borderRadius: 5,
                    background: position === cursor ? "var(--bg-2)" : "transparent",
                    color: "var(--fg-0)",
                  }}
                >
                  <KindDot kind={node.kind} />
                  <span>{node.label}</span>
                  <span className="note" style={{ marginLeft: "auto" }}>
                    {node.kind} · {node.path ?? ""}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
        <p className="note" style={{ margin: "8px 0 0" }}>
          ↑↓ to choose · enter to open · esc to close — everything here is a node the
          graph measured
        </p>
      </div>
    </div>
  );
}
