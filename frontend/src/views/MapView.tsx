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
import { api, type GraphPayload, type GraphView, type GraphViews } from "../api";
import { graphPayload } from "../graph";
import { Badge, Empty, ErrorBox, Loading, Panel } from "../ui";
import { ModuleLink } from "./links";
import { PathView } from "./PathView";
import {
  applyFilters,
  type Filters,
  kindColor,
  positionsFromLevels,
  rankMatches,
  shortLabels,
} from "./layout";
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
    setError(null);
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
        <button
          className="badge"
          onClick={() => setActiveId("path")}
          style={{
            cursor: "pointer",
            color: activeId === "path" ? "var(--accent)" : undefined,
            borderColor: activeId === "path" ? "var(--accent)" : undefined,
          }}
          data-testid="path-tab"
        >
          how does A reach B…
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
      ) : activeId === "path" ? (
        <PathView runId={runId!} onOpenSource={openSource} />
      ) : active.kind === "matrix" ? (
        <MatrixView view={active} />
      ) : (
        <LevelizedView key={active.id} view={active} onOpenSource={openSource} />
      )}

      <SourcePanel request={source} onClose={() => setSource(null)} />
    </div>
  );
}

// --- levelized node-link (packages and per-package modules) ------------------

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
    const positions = positionsFromLevels(view.nodes, view.edges);
    // Within one view the shared path prefix is context the reader already has;
    // spending the label on it is what made every node in `ignore` read
    // `crates/ignore/src/…` and overlap its neighbour.
    const short = shortLabels(view.nodes.map((node) => node.label));
    const maxFanIn = Math.max(1, ...view.nodes.map((node) => node.fanIn ?? 0));
    const maxChurn = Math.max(1, ...view.nodes.map((node) => node.churn ?? 0));
    const elements: cytoscape.ElementDefinition[] = [
      ...view.nodes.map((node) => ({
        data: {
          ...node,
          label: short.get(node.label) ?? node.label,
          fanIn: node.fanIn ?? 0,
          // 0 when unmeasured: the border stays at its 1px base, identical to
          // a run from before the metric — absence never draws as heat.
          churn: node.churn ?? 0,
        } as cytoscape.NodeDataDefinition,
        position: positions.get(node.id),
      })),
      ...view.edges.map((edge) => ({ data: { ...edge } as cytoscape.EdgeDataDefinition })),
    ];
    const cy = cytoscape({
      container: containerRef.current,
      elements,
      layout: { name: "preset" },
      style: cytoscapeStyle(maxFanIn, maxChurn),
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

function cytoscapeStyle(maxFanIn: number, maxChurn: number = 1): cytoscape.StylesheetJson {
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
        // Size carries fan-in, so a glance separates the crate everything
        // depends on from the leaf nobody imports. Eleven identical squares
        // said nothing about which of them mattered.
        width: `mapData(fanIn, 0, ${maxFanIn}, 16, 38)`,
        height: `mapData(fanIn, 0, ${maxFanIn}, 16, 38)`,
        shape: "round-rectangle",
        "background-color": (element: cytoscape.NodeSingular) => {
          const kind = String(element.data("kind"));
          if (element.data("inCycle")) return "#e0af68";
          return kind === "package" ? "#7aa2f7" : "#7dcfff";
        },
        // Border width carries churn — where the project actually gets
        // edited. Size answers "who is depended on", border "who is touched";
        // an unmeasured run keeps every border at the 1px base.
        "border-width": `mapData(churn, 0, ${maxChurn}, 1, 6)`,
        "border-color": "#303952",
      },
    },
    {
      // Colour only: a fixed width here would clobber the churn channel.
      selector: "node[?inCycle]",
      style: { "border-color": "#e0af68" },
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

function MatrixView({ view }: { view: GraphView }) {
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

  // 104 rows over nine crates contain five files called `mod.rs` and three
  // called `lib.rs`. A bare basename makes distinct rows indistinguishable.
  const short = useMemo(() => shortLabels(view.nodes.map((node) => node.label)), [view]);
  const [hover, setHover] = useState<{ row: number; column: number } | null>(null);

  const hovered =
    hover && view.nodes[hover.row] && view.nodes[hover.column]
      ? {
          source: view.nodes[hover.row]!,
          target: view.nodes[hover.column]!,
          weight: cells.get(`${hover.row}:${hover.column}`),
        }
      : null;

  return (
    <div style={{ overflow: "auto", flex: 1 }} data-testid="matrix">
      <p className="note" style={{ marginTop: 0 }}>
        row depends on column · ordered by level, so a clean layering fills the lower
        triangle · cells above the diagonal are cycles · columns carry the same numbers
        as the rows
      </p>
      {/* Without this a reader can see a cell but cannot say what it connects:
          the columns have no room for a name at this size. */}
      <div
        className="matrix-readout"
        data-testid="matrix-readout"
        style={{ minHeight: "1.4em", marginBottom: 6 }}
      >
        {hovered ? (
          <span>
            <strong>{hovered.source.label}</strong>
            {hovered.weight === undefined ? " does not depend on " : " → "}
            <strong>{hovered.target.label}</strong>
            {hovered.weight !== undefined && ` · ${hovered.weight} reference(s)`}
          </span>
        ) : (
          <span className="note">hover a cell to name both ends</span>
        )}
      </div>
      <table style={{ borderCollapse: "collapse" }} onMouseLeave={() => setHover(null)}>
        <thead>
          <tr>
            <th />
            {view.nodes.map((columnNode, columnIndex) => {
              const number = columnIndex + 1;
              // A number over every 14px column runs into its neighbours and
              // reads as noise. Tick every fifth and let the reader count.
              const isTick = number % 5 === 0 || number === 1;
              const isHovered = hover?.column === columnIndex;
              return (
                <th
                  key={columnNode.id}
                  className="matrix-colhead"
                  title={columnNode.label}
                  style={{
                    fontWeight: 400,
                    fontSize: 8,
                    color: isHovered ? "var(--accent)" : "var(--fg-3)",
                  }}
                >
                  {isHovered || isTick ? number : ""}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {view.nodes.map((rowNode, rowIndex) => (
            <tr key={rowNode.id}>
              <th
                style={{
                  textAlign: "right",
                  paddingRight: 8,
                  fontWeight: 400,
                  fontSize: 10,
                  color: hover?.row === rowIndex ? "var(--accent)" : "var(--fg-2)",
                  whiteSpace: "nowrap",
                }}
                title={rowNode.label}
              >
                <span style={{ color: "var(--fg-3)" }}>{rowIndex + 1}</span>{" "}
                {rowNode.path ? (
                  <ModuleLink path={rowNode.path} className="" style={{ color: "inherit" }}>
                    {short.get(rowNode.label) ?? rowNode.label}
                  </ModuleLink>
                ) : (
                  (short.get(rowNode.label) ?? rowNode.label)
                )}
              </th>
              {view.nodes.map((columnNode, columnIndex) => {
                const weight = cells.get(`${rowIndex}:${columnIndex}`);
                const isDiagonal = rowIndex === columnIndex;
                const isCycleCell = weight !== undefined && columnIndex > rowIndex;
                const onAxis = hover?.row === rowIndex || hover?.column === columnIndex;
                return (
                  <td
                    key={columnNode.id}
                    className="matrix-cell"
                    data-testid={weight !== undefined ? "matrix-hit" : undefined}
                    onMouseEnter={() => setHover({ row: rowIndex, column: columnIndex })}
                    title={
                      weight !== undefined
                        ? `${rowNode.label} → ${columnNode.label} (${weight})`
                        : undefined
                    }
                    style={{
                      outline: onAxis ? "1px solid var(--border-strong)" : undefined,
                      background: isDiagonal
                        ? "var(--bg-3)"
                        : weight === undefined
                          ? onAxis
                            ? "var(--bg-2)"
                            : "transparent"
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

/** Toggles for what a neighbourhood shows. Unset means "everything", so the
 *  bar starts as a description of the graph rather than as a restriction. */
function FilterBar({
  available,
  filters,
  onChange,
}: {
  available: { kinds: string[]; edgeKinds: string[]; producers: string[] };
  filters: Filters;
  onChange: (filters: Filters) => void;
}) {
  const groups: { key: keyof Filters; label: string; values: string[] }[] = [
    { key: "kinds", label: "node", values: available.kinds },
    { key: "edgeKinds", label: "edge", values: available.edgeKinds },
    { key: "producers", label: "from", values: available.producers },
  ];

  const toggle = (key: keyof Filters, value: string, all: string[]) => {
    const current = filters[key] ?? new Set(all);
    const next = new Set(current);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    // Back to every value means no filter at all, not a filter that happens to
    // match everything — so the "hid N" line disappears rather than saying zero.
    onChange({ ...filters, [key]: next.size === all.length ? undefined : next });
  };

  return (
    <div style={{ display: "grid", gap: 4, marginTop: 8 }} data-testid="filters">
      {groups
        .filter((group) => group.values.length > 1)
        .map((group) => (
          <div key={group.key} style={{ display: "flex", gap: 4, alignItems: "baseline", flexWrap: "wrap" }}>
            <span className="microlabel" style={{ minWidth: 34 }}>
              {group.label}
            </span>
            {group.values.map((value) => {
              const on = !filters[group.key] || filters[group.key]!.has(value);
              return (
                <button
                  key={value}
                  className="badge"
                  data-testid="filter-toggle"
                  aria-pressed={on}
                  onClick={() => toggle(group.key, value, group.values)}
                  style={{
                    cursor: "pointer",
                    opacity: on ? 1 : 0.4,
                    borderColor: on ? "var(--accent)" : undefined,
                  }}
                >
                  {value}
                </button>
              );
            })}
          </div>
        ))}
    </div>
  );
}

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
  const [filters, setFilters] = useState<Filters>({});
  const [hidden, setHidden] = useState({ nodes: 0, edges: 0 });
  const [capped, setCapped] = useState<{ total: number } | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // The shared memoised payload — the same fetch every module page rides.
    // A raw api.runGraph here was the one bypass of the once-per-run rule.
    graphPayload(runId).then(setGraph).catch(() => setGraph(null));
  }, [runId]);

  // What this graph actually contains, so the filters offer real choices rather
  // than a fixed list that might be empty or missing something.
  const available = useMemo(() => {
    const kinds = new Set<string>();
    const producers = new Set<string>();
    const edgeKinds = new Set<string>();
    for (const node of graph?.elements.nodes ?? []) {
      kinds.add(String(node.data.kind ?? ""));
      for (const producer of (node.data.producers as string[] | undefined) ?? []) {
        producers.add(producer);
      }
    }
    for (const edge of graph?.elements.edges ?? []) edgeKinds.add(String(edge.data.kind ?? ""));
    return {
      kinds: [...kinds].filter(Boolean).sort(),
      edgeKinds: [...edgeKinds].filter(Boolean).sort(),
      producers: [...producers].filter(Boolean).sort(),
    };
  }, [graph]);

  const matches = useMemo(() => {
    if (!graph) return [];
    // Ranked, not filtered: over 4,700 nodes a plain substring match buries the
    // type named `Searcher` under every file whose path contains "searcher".
    const ranked = rankMatches(
      graph.elements.nodes.map((node) => ({
        id: String(node.data.id),
        label: String(node.data.label ?? ""),
        kind: String(node.data.kind ?? ""),
        node,
      })),
      query,
      12,
    );
    return ranked.map((entry) => entry.node);
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
    // The cap is disclosed like the filters are: dropping neighbours without
    // a count reads as "this is the whole neighbourhood" when it is not.
    const totalNeighbours = neighbors.size - 1;
    setCapped(totalNeighbours > NEIGHBOR_LIMIT ? { total: totalNeighbours } : null);
    const inScope = graph.elements.nodes.filter((node) => shownSet.has(node.data.id));
    const scopedEdges = edges.filter(
      (edge) =>
        shownSet.has(String(edge.data.source)) && shownSet.has(String(edge.data.target)),
    );

    const filtered = applyFilters(
      inScope.map((node) => ({
        id: String(node.data.id),
        label: String(node.data.label ?? ""),
        kind: String(node.data.kind ?? ""),
        producers: (node.data.producers as string[] | undefined) ?? [],
        node,
      })),
      scopedEdges.map((edge) => ({
        id: String(edge.data.id ?? `${edge.data.source}->${edge.data.target}`),
        source: String(edge.data.source),
        target: String(edge.data.target),
        kind: String(edge.data.kind ?? ""),
        edge,
      })),
      filters,
      focusId,
    );
    setHidden({ nodes: filtered.hiddenNodes, edges: filtered.hiddenEdges });

    const nodes = filtered.nodes.map((entry) => entry.node);
    const visibleEdges = filtered.edges.map((entry) => entry.edge);

    const shortNeighbours = shortLabels(nodes.map((node) => String(node.data.label ?? "")));
    const cy = cytoscape({
      container: containerRef.current,
      elements: [
        ...nodes.map((node) => ({
          data: {
            ...node.data,
            label: shortNeighbours.get(String(node.data.label ?? "")) ?? node.data.label,
          },
        })),
        ...visibleEdges.map((edge) => ({ data: edge.data })),
      ],
      layout: {
        name: "concentric",
        animate: false,
        concentric: (node) => (node.id() === focusId ? 2 : 1),
        levelWidth: () => 1,
        // A neighbourhood of a dozen nodes was drawing at thumbnail size in the
        // middle of an empty canvas; the ring needs room proportional to how
        // many labels have to fit around it.
        minNodeSpacing: 45,
      },
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
              kindColor(String(element.data("kind"))),
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
      // Higher than the levelized views allow: a 1-hop neighbourhood is small
      // by construction, and capping it at 1.4 wasted three quarters of the
      // canvas on a graph that had room to be read comfortably.
      maxZoom: 2.4,
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
  }, [graph, focusId, filters, onOpenSource]);

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
                // Two crates can both have a module called `searcher`; the id
                // is what tells the identical-looking chips apart.
                title={node.data.id}
              >
                {String(node.data.kind)} · {String(node.data.label)}
              </button>
            ))}
          </div>
        )}
        {focusId && (
          <>
            <FilterBar available={available} filters={filters} onChange={setFilters} />
            <p className="note" style={{ marginBottom: 0 }}>
              showing the 1-hop neighborhood · tap a neighbor to refocus, tap the center to
              open its source
              {(() => {
                // The focused node's module page — the graph surface used to
                // dead-end here while the matrix rows could navigate.
                const focused = graph?.elements.nodes.find(
                  (node) => node.data.id === focusId,
                );
                const path = focused?.data.path as string | undefined;
                return path ? (
                  <span data-testid="focus-module-link">
                    {" · "}
                    <ModuleLink path={path}>explain {path.split("/").pop()}</ModuleLink>
                  </span>
                ) : null;
              })()}
              {capped && (
                <>
                  {" · "}
                  <span data-testid="focus-truncated">
                    showing {NEIGHBOR_LIMIT} of {capped.total} neighbours — the rest are not
                    drawn
                  </span>
                </>
              )}
              {hidden.nodes + hidden.edges > 0 && (
                <>
                  {" · "}
                  <span data-testid="filter-hidden">
                    filters hid {hidden.nodes} node(s) and {hidden.edges} edge(s)
                  </span>
                </>
              )}
            </p>
          </>
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
