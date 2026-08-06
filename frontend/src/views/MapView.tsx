// The project map: packages first, one package's modules at a time, a matrix
// for the whole thing, and a search-driven neighborhood for path-finding.
//
// The layouts here are *data*, not algorithm output: every node carries the
// level the backend computed, so positions are a pure function of the artifact
// and two people looking at the same run see the same picture. The full graph
// is never rendered — that decision was made by measurement (a node-link view
// stops being readable around 25 nodes) and enforced server-side by the
// readability gate; this view honors the refusals it is handed.

import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import cytoscape from "cytoscape";
import {
  api,
  type GraphPayload,
  type GraphView,
  type GraphViews,
  type ViewNode,
} from "../api";
import { Badge, Empty, ErrorBox, Loading, Panel } from "../ui";
import { SourcePanel, type SourceRequest } from "./SourcePanel";

export function MapView() {
  const { runId } = useParams();
  const [views, setViews] = useState<GraphViews | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [source, setSource] = useState<SourceRequest | null>(null);

  useEffect(() => {
    if (!runId) return;
    setViews(null);
    setActiveId(null);
    api
      .views(runId)
      .then((payload) => {
        setViews(payload);
        setActiveId(payload.views[0]?.id ?? null);
      })
      .catch((e: Error) => setError(e.message));
  }, [runId]);

  if (error) return <ErrorBox error={error} />;
  if (!views) return <Loading />;
  if (views.views.length === 0) return <Empty>{views.notes.join("; ") || "no views"}</Empty>;

  const active: GraphView = views.views.find((view) => view.id === activeId) ?? views.views[0]!;
  const openSource = (path: string) => setSource({ revision: views.revision, path });

  return (
    <div data-testid="map-view" style={{ display: "flex", flexDirection: "column", gap: 12, height: "100%" }}>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
        {views.views.map((view) => (
          <button
            key={view.id}
            className="badge"
            onClick={() => setActiveId(view.id)}
            style={{
              cursor: "pointer",
              color: view.id === active.id ? "var(--accent)" : undefined,
              borderColor: view.id === active.id ? "var(--accent)" : undefined,
            }}
          >
            {view.title}
          </button>
        ))}
        <button
          className="badge"
          onClick={() => setActiveId("focus")}
          style={{
            cursor: "pointer",
            color: activeId === "focus" ? "var(--accent)" : undefined,
            borderColor: activeId === "focus" ? "var(--accent)" : undefined,
          }}
          data-testid="focus-tab"
        >
          focus a symbol…
        </button>
      </div>

      {views.refused.length > 0 && (
        <div className="caveat" data-testid="refusals">
          {views.refused.map((refusal) => (
            <div key={refusal.id}>
              <strong>{refusal.id}</strong> was not drawn: {refusal.reason}
            </div>
          ))}
        </div>
      )}

      {activeId === "focus" ? (
        <FocusView runId={runId!} onOpenSource={openSource} />
      ) : active.kind === "matrix" ? (
        <MatrixView view={active} onOpenSource={openSource} />
      ) : (
        <LevelizedView key={active.id} view={active} onOpenSource={openSource} />
      )}

      <SourcePanel request={source} onClose={() => setSource(null)} />
    </div>
  );
}

// --- levelized node-link (packages and per-package modules) ------------------

/** Positions from levels: x spreads within a level, y stacks levels bottom-up. */
function positionsFromLevels(nodes: ViewNode[]): Map<string, { x: number; y: number }> {
  const byLevel = new Map<number, ViewNode[]>();
  for (const node of nodes) {
    const level = node.level ?? 0;
    byLevel.set(level, [...(byLevel.get(level) ?? []), node]);
  }
  const positions = new Map<string, { x: number; y: number }>();
  const maxLevel = Math.max(...[...byLevel.keys()], 0);
  const SPACING_X = 190;
  const SPACING_Y = 110;
  for (const [level, members] of byLevel) {
    members.sort((a, b) => a.label.localeCompare(b.label));
    members.forEach((node, index) => {
      positions.set(node.id, {
        x: (index - (members.length - 1) / 2) * SPACING_X,
        y: (maxLevel - level) * SPACING_Y,
      });
    });
  }
  return positions;
}

function LevelizedView({
  view,
  onOpenSource,
}: {
  view: GraphView;
  onOpenSource: (path: string) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const positions = positionsFromLevels(view.nodes);
    const elements: cytoscape.ElementDefinition[] = [
      ...view.nodes.map((node) => ({
        data: { ...node } as cytoscape.NodeDataDefinition,
        position: positions.get(node.id),
      })),
      ...view.edges.map((edge) => ({ data: { ...edge } as cytoscape.EdgeDataDefinition })),
    ];
    const cy = cytoscape({
      container: containerRef.current,
      elements,
      layout: { name: "preset" },
      style: cytoscapeStyle(),
      wheelSensitivity: 0.2,
      // Without a ceiling, `fit` on a two-node view blows the labels up to
      // headline size and the diagram reads as a poster rather than a map.
      maxZoom: 1.4,
      minZoom: 0.15,
    });
    cy.fit(undefined, 60);
    cy.on("tap", "node", (event) => {
      const path = event.target.data("path") as string | undefined;
      if (path) onOpenSource(path);
    });
    return () => cy.destroy();
  }, [view, onOpenSource]);

  return (
    <div style={{ flex: 1, minHeight: 380, display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ display: "flex", gap: 10, alignItems: "baseline" }}>
        {(view.notes ?? []).map((note, index) => (
          <span key={index} className="note">
            {note}
          </span>
        ))}
        {(view.suppressedEdges ?? 0) > 0 && (
          <Badge tone="info">{view.suppressedEdges} edges carried by the layout</Badge>
        )}
      </div>
      <div ref={containerRef} className="graph-canvas panel" data-testid="graph" />
    </div>
  );
}

function cytoscapeStyle(): cytoscape.StylesheetJson {
  return [
    {
      selector: "node",
      style: {
        label: "data(label)",
        color: "#a8b0c2",
        "font-size": 10,
        "font-family": "ui-monospace, monospace",
        "text-valign": "bottom",
        "text-margin-y": 4,
        width: 18,
        height: 18,
        shape: "round-rectangle",
        "background-color": (element: cytoscape.NodeSingular) => {
          const kind = String(element.data("kind"));
          if (element.data("inCycle")) return "#e0af68";
          return kind === "package" ? "#7aa2f7" : "#7dcfff";
        },
        "border-width": 1,
        "border-color": "#303952",
      },
    },
    {
      selector: "node[?inCycle]",
      style: { "border-color": "#e0af68", "border-width": 2 },
    },
    {
      selector: "edge",
      style: {
        width: "mapData(weight, 1, 20, 1, 4)",
        "curve-style": "bezier",
        "target-arrow-shape": "triangle",
        "arrow-scale": 0.7,
        "line-color": "#303952",
        "target-arrow-color": "#303952",
      },
    },
    {
      selector: "edge[?violatesLevels]",
      style: { "line-color": "#e0af68", "target-arrow-color": "#e0af68" },
    },
  ];
}

// --- matrix ------------------------------------------------------------------

function MatrixView({
  view,
  onOpenSource,
}: {
  view: GraphView;
  onOpenSource: (path: string) => void;
}) {
  const index = useMemo(() => new Map(view.nodes.map((node, i) => [node.id, i])), [view]);
  const cells = useMemo(() => {
    const set = new Map<string, number>();
    for (const edge of view.edges) {
      const row = index.get(edge.source);
      const column = index.get(edge.target);
      if (row !== undefined && column !== undefined) {
        set.set(`${row}:${column}`, edge.weight ?? 1);
      }
    }
    return set;
  }, [view, index]);

  const shortLabel = (node: ViewNode) => node.label.split("/").pop() ?? node.label;

  return (
    <div style={{ overflow: "auto", flex: 1 }} data-testid="matrix">
      <p className="note" style={{ marginTop: 0 }}>
        row depends on column · ordered by level, so a clean layering fills the lower
        triangle · cells above the diagonal are cycles
      </p>
      <table style={{ borderCollapse: "collapse" }}>
        <tbody>
          {view.nodes.map((rowNode, rowIndex) => (
            <tr key={rowNode.id}>
              <th
                style={{
                  textAlign: "right",
                  paddingRight: 8,
                  fontWeight: 400,
                  fontSize: 10,
                  color: "var(--fg-2)",
                  whiteSpace: "nowrap",
                  cursor: rowNode.path ? "pointer" : "default",
                }}
                onClick={() => rowNode.path && onOpenSource(rowNode.path)}
                title={rowNode.label}
              >
                {shortLabel(rowNode)}
              </th>
              {view.nodes.map((columnNode, columnIndex) => {
                const weight = cells.get(`${rowIndex}:${columnIndex}`);
                const isDiagonal = rowIndex === columnIndex;
                const isCycleCell = weight !== undefined && columnIndex > rowIndex;
                return (
                  <td
                    key={columnNode.id}
                    className="matrix-cell"
                    title={
                      weight !== undefined
                        ? `${rowNode.label} → ${columnNode.label} (${weight})`
                        : undefined
                    }
                    style={{
                      background: isDiagonal
                        ? "var(--bg-3)"
                        : weight === undefined
                          ? "transparent"
                          : isCycleCell
                            ? "var(--warn)"
                            : `color-mix(in srgb, var(--accent) ${Math.min(25 + weight * 8, 90)}%, transparent)`,
                    }}
                  />
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// --- focus: search -> context -> expand --------------------------------------

// The van Ham & Perer interaction: never show everything, let the reader name
// what they care about, show its immediate context, expand on demand. This is
// the one place node-link wins at any size — following a specific path.

const NEIGHBOR_LIMIT = 24;

function FocusView({
  runId,
  onOpenSource,
}: {
  runId: string;
  onOpenSource: (path: string) => void;
}) {
  const [graph, setGraph] = useState<GraphPayload | null>(null);
  const [query, setQuery] = useState("");
  const [focusId, setFocusId] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.runGraph(runId).then(setGraph).catch(() => setGraph(null));
  }, [runId]);

  const matches = useMemo(() => {
    if (!graph || query.length < 2) return [];
    const needle = query.toLowerCase();
    return graph.elements.nodes
      .filter((node) => String(node.data.label ?? "").toLowerCase().includes(needle))
      .slice(0, 12);
  }, [graph, query]);

  useEffect(() => {
    if (!graph || !focusId || !containerRef.current) return;

    const neighbors = new Set<string>([focusId]);
    const edges = graph.elements.edges.filter((edge) => {
      const source = String(edge.data.source);
      const target = String(edge.data.target);
      return source === focusId || target === focusId;
    });
    for (const edge of edges) {
      neighbors.add(String(edge.data.source));
      neighbors.add(String(edge.data.target));
    }
    const shown = [...neighbors].slice(0, NEIGHBOR_LIMIT + 1);
    const shownSet = new Set(shown);
    const nodes = graph.elements.nodes.filter((node) => shownSet.has(node.data.id));
    const visibleEdges = edges.filter(
      (edge) =>
        shownSet.has(String(edge.data.source)) && shownSet.has(String(edge.data.target)),
    );

    const cy = cytoscape({
      container: containerRef.current,
      elements: [...nodes, ...visibleEdges.map((edge) => ({ data: edge.data }))],
      layout: { name: "concentric", animate: false, concentric: (node) => (node.id() === focusId ? 2 : 1), levelWidth: () => 1 },
      style: [
        {
          selector: "node",
          style: {
            label: "data(label)",
            color: "#a8b0c2",
            "font-size": 9,
            "font-family": "ui-monospace, monospace",
            width: 14,
            height: 14,
            "background-color": (element: cytoscape.NodeSingular) =>
              `var(--kind-${String(element.data("kind"))}, #6b7489)` as unknown as string,
          },
        },
        {
          selector: `node[id = "${focusId.replace(/"/g, '\\"')}"]`,
          style: { width: 24, height: 24, "border-width": 2, "border-color": "#7aa2f7" },
        },
        {
          selector: "edge",
          style: {
            width: 1,
            label: "data(kind)",
            "font-size": 7,
            color: "#6b7489",
            "curve-style": "bezier",
            "target-arrow-shape": "triangle",
            "arrow-scale": 0.6,
            "line-color": "#303952",
            "target-arrow-color": "#303952",
          },
        },
      ],
      wheelSensitivity: 0.2,
      maxZoom: 1.4,
      minZoom: 0.15,
    });
    cy.fit(undefined, 40);
    cy.on("tap", "node", (event) => {
      const id = String(event.target.id());
      if (id !== focusId) {
        // expand on demand: refocus on the tapped neighbor
        setFocusId(id);
      } else {
        const path = event.target.data("path") as string | undefined;
        if (path) onOpenSource(path);
      }
    });
    return () => cy.destroy();
  }, [graph, focusId, onOpenSource]);

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 8, minHeight: 380 }}>
      <Panel title="focus">
        <input
          type="search"
          placeholder="search a symbol, file or package…  (min 2 chars)"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          data-testid="focus-search"
          style={{
            width: "100%",
            padding: "7px 10px",
            background: "var(--bg-0)",
            border: "1px solid var(--border-strong)",
            borderRadius: 6,
            color: "var(--fg-0)",
            font: "inherit",
          }}
        />
        {matches.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 8 }}>
            {matches.map((node) => (
              <button
                key={node.data.id}
                className="badge"
                style={{ cursor: "pointer" }}
                onClick={() => setFocusId(node.data.id)}
                data-testid="focus-match"
              >
                {String(node.data.kind)} · {String(node.data.label)}
              </button>
            ))}
          </div>
        )}
        {focusId && (
          <p className="note" style={{ marginBottom: 0 }}>
            showing the 1-hop neighborhood · tap a neighbor to refocus, tap the center to
            open its source
          </p>
        )}
      </Panel>
      {focusId ? (
        <div ref={containerRef} className="graph-canvas panel" style={{ flex: 1 }} data-testid="focus-graph" />
      ) : (
        <Empty>name what you care about — the whole graph is never rendered</Empty>
      )}
    </div>
  );
}
