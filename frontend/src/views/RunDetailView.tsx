import cytoscape from "cytoscape";
import { useEffect, useRef, useState } from "react";
import { api, type GraphPayload, type RunDetail, type SourceSlice } from "../api";

const KIND_COLORS: Record<string, string> = {
  package: "#4c78a8",
  file: "#72b7b2",
  module: "#eeca3b",
  type: "#f58518",
  function: "#e45756",
};

export function RunDetailView({ runId }: { runId: string }) {
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [graph, setGraph] = useState<GraphPayload | null>(null);
  const [source, setSource] = useState<SourceSlice | null>(null);
  const [error, setError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setDetail(null);
    setGraph(null);
    setSource(null);
    api.runDetail(runId).then(setDetail).catch((e: Error) => setError(e.message));
    api.runGraph(runId).then(setGraph).catch((e: Error) => setError(e.message));
  }, [runId]);

  useEffect(() => {
    if (!graph || !containerRef.current) return;
    const cy = cytoscape({
      container: containerRef.current,
      elements: [...graph.elements.nodes, ...graph.elements.edges],
      style: [
        {
          selector: "node",
          style: {
            label: "data(label)",
            "font-size": 8,
            width: 14,
            height: 14,
            "background-color": (el: cytoscape.NodeSingular) =>
              KIND_COLORS[String(el.data("kind"))] ?? "#999",
          },
        },
        {
          selector: "edge",
          style: {
            width: 1,
            "curve-style": "bezier",
            "target-arrow-shape": "triangle",
            "arrow-scale": 0.6,
            "line-opacity": 0.5,
          },
        },
      ],
      layout: { name: "cose", animate: false },
    });
    cy.on("tap", "node", (event) => {
      const path = event.target.data("path") as string | undefined;
      if (!path || !graph) return;
      const start = (event.target.data("startLine") as number | undefined) ?? 1;
      const end = event.target.data("endLine") as number | undefined;
      api
        .source(graph.revision, path, start, end ?? start + 40)
        .then(setSource)
        .catch((e: Error) => setError(e.message));
    });
    return () => cy.destroy();
  }, [graph]);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <header style={{ padding: "0.5rem 1rem", borderBottom: "1px solid #8884" }}>
        <strong data-testid="run-status">{detail?.status ?? "…"}</strong>{" "}
        <code>{runId}</code>
        {detail && (
          <span style={{ marginLeft: "1rem" }}>
            {detail.events.filter((e) => e.event === "finished").length} stages finished
          </span>
        )}
        {error && <span role="alert" style={{ color: "crimson" }}> {error}</span>}
      </header>
      <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
        <div ref={containerRef} data-testid="graph" style={{ flex: 2 }} />
        <section
          style={{
            flex: 1,
            borderLeft: "1px solid #8884",
            overflow: "auto",
            padding: "0.5rem",
            fontFamily: "monospace",
            fontSize: 12,
          }}
        >
          {source ? (
            <>
              <p data-testid="source-path">
                {source.path}:{source.startLine}–{source.endLine} @{" "}
                {source.revision.slice(0, 10)}
              </p>
              <pre style={{ whiteSpace: "pre-wrap" }} data-testid="source-lines">
                {source.lines
                  .map((line, i) => `${String(source.startLine + i).padStart(4)} ${line}`)
                  .join("\n")}
              </pre>
            </>
          ) : (
            <p>Click a node with a source location to see pinned source.</p>
          )}
        </section>
      </div>
    </div>
  );
}
