// How does A reach B — the one node-link task the research this map is built on
// endorses at any size (Ghoniem/Fekete/Castagliola: matrices win everywhere
// else past ~20 nodes, node-link wins at path-finding, always).
//
// Honest about its limits the way the map's other views are: shortest path
// only, dependency edges only, and when nothing connects the two it says so —
// "nothing in this graph connects A to B" is an answer, not an empty canvas.

import { useEffect, useMemo, useRef, useState } from "react";
import cytoscape from "cytoscape";
import { graphIndex, shortestPath, type GraphIndex, type GraphNode, type PathStep } from "../graph";
import { Empty, ErrorBox, Panel } from "../ui";
import { kindColor, rankMatches } from "./layout";

export function PathView({
  runId,
  onOpenSource,
}: {
  runId: string;
  onOpenSource: (path: string) => void;
}) {
  const [index, setIndex] = useState<GraphIndex | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [from, setFrom] = useState<GraphNode | null>(null);
  const [to, setTo] = useState<GraphNode | null>(null);

  useEffect(() => {
    setError(null);
    graphIndex(runId)
      .then(setIndex)
      .catch((e: Error) => {
        setIndex(null);
        setError(e.message);
      });
  }, [runId]);

  const path = useMemo(
    () => (index && from && to ? shortestPath(index, from.id, to.id) : undefined),
    [index, from, to],
  );

  // A terminal failure must not wear the loading message forever.
  if (error) return <ErrorBox error={error} />;
  if (!index) return <Empty>loading the graph…</Empty>;

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 8, minHeight: 380 }}>
      <Panel title="how does A reach B">
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <EndpointPicker
            label="from"
            index={index}
            chosen={from}
            onChoose={setFrom}
            testId="path-from"
            role="from"
          />
          <EndpointPicker
            label="to"
            index={index}
            chosen={to}
            onChoose={setTo}
            testId="path-to"
            role="to"
          />
        </div>
        {path === null && from && to && (
          <div className="caveat" style={{ marginTop: 8 }} data-testid="no-path">
            nothing in this graph connects {from.label} to {to.label} — no chain of
            calls, reads or imports leads from one to the other at this revision
          </div>
        )}
        {path && path.length > 0 && (
          <p className="note" style={{ marginBottom: 0 }} data-testid="path-summary">
            {path.length - 1} hop(s), shortest route only — other routes may exist
          </p>
        )}
      </Panel>

      {path && path.length > 0 ? (
        <PathGraph path={path} index={index} onOpenSource={onOpenSource} />
      ) : (
        !from || !to ? (
          <Empty>name both ends — the whole graph is never rendered</Empty>
        ) : null
      )}
    </div>
  );
}

function EndpointPicker({
  label,
  index,
  chosen,
  onChoose,
  testId,
  role,
}: {
  label: string;
  index: GraphIndex;
  chosen: GraphNode | null;
  onChoose: (node: GraphNode) => void;
  testId: string;
  role: "from" | "to";
}) {
  const [query, setQuery] = useState("");

  // Only endpoints that can participate: a start must depend on something and
  // an end must be depended on. Offering a module anchor or an isolated node
  // guarantees "no path" before the search begins — seen live, where the top
  // match for "matcher" was the module anchor, which by design has no
  // dependency edges at all.
  const candidates = useMemo(
    () =>
      index.nodes.filter((node) =>
        role === "from" ? index.uses(node.id).length > 0 : index.usedBy(node.id).length > 0,
      ),
    [index, role],
  );
  const matches = useMemo(() => rankMatches(candidates, query, 8), [candidates, query]);

  return (
    <div>
      <div className="microlabel" style={{ marginBottom: 4 }}>
        {label}
        {chosen && (
          <span style={{ color: "var(--accent)", marginLeft: 6 }}>{chosen.label}</span>
        )}
      </div>
      <input
        type="search"
        placeholder="search a symbol…  (min 2 chars)"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        data-testid={testId}
        style={{
          width: "100%",
          padding: "6px 9px",
          background: "var(--bg-0)",
          border: "1px solid var(--border-strong)",
          borderRadius: 6,
          color: "var(--fg-0)",
          font: "inherit",
        }}
      />
      {matches.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 6 }}>
          {matches.map((node) => (
            <button
              key={node.id}
              className="badge"
              style={{ cursor: "pointer" }}
              title={node.id}
              data-testid={`${testId}-match`}
              onClick={() => {
                onChoose(node);
                setQuery("");
              }}
            >
              {node.kind} · {node.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function PathGraph({
  path,
  index,
  onOpenSource,
}: {
  path: PathStep[];
  index: GraphIndex;
  onOpenSource: (path: string) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const STEP_X = 210;
    const cy = cytoscape({
      container: containerRef.current,
      elements: [
        ...path.map((step, position) => ({
          data: {
            id: step.node.id,
            label: step.node.label,
            kind: step.node.kind,
            path: step.node.path,
            file: index.fileOf(step.node.id)?.label ?? step.node.path ?? "",
          },
          position: { x: position * STEP_X, y: (position % 2) * 46 },
        })),
        ...path.slice(1).map((step, position) => ({
          data: {
            id: `hop${position}`,
            source: path[position]!.node.id,
            target: step.node.id,
            label: step.viaKind ?? "",
          },
        })),
      ],
      layout: { name: "preset" },
      style: [
        {
          selector: "node",
          style: {
            label: "data(label)",
            color: "#c5cad6",
            "font-size": 11,
            "font-family": "ui-monospace, monospace",
            "text-valign": "bottom",
            "text-margin-y": 5,
            width: 20,
            height: 20,
            shape: "round-rectangle",
            "background-color": (element: cytoscape.NodeSingular) =>
              kindColor(String(element.data("kind"))),
            "border-width": 1,
            "border-color": "#303952",
          },
        },
        {
          selector: "edge",
          style: {
            width: 1.5,
            label: "data(label)",
            "font-size": 9,
            color: "#6b7489",
            "curve-style": "bezier",
            "target-arrow-shape": "triangle",
            "arrow-scale": 0.8,
            "line-color": "#4a5570",
            "target-arrow-color": "#4a5570",
          },
        },
      ],
      wheelSensitivity: 0.2,
      maxZoom: 2.0,
      minZoom: 0.15,
    });
    cy.fit(undefined, 50);
    cy.on("tap", "node", (event) => {
      const nodePath = event.target.data("path") as string | undefined;
      if (nodePath) onOpenSource(nodePath);
    });
    return () => cy.destroy();
  }, [path, index, onOpenSource]);

  return (
    <div
      ref={containerRef}
      className="graph-canvas panel"
      style={{ flex: 1, minHeight: 300 }}
      data-testid="path-graph"
    />
  );
}
