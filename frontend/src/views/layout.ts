// Pure geometry and naming for the map.
//
// Everything here is a deterministic function of the artifact — no layout
// algorithm, no randomness, no measurement of the viewport — so two people
// looking at the same run see the same picture, and the picture can be tested
// without a browser.

export interface PositionedNode {
  id: string;
  label: string;
  level?: number | null;
}

export interface PositionedEdge {
  source: string;
  target: string;
}

export interface Point {
  x: number;
  y: number;
}

const SPACING_X = 190;
const SPACING_Y = 130;

/** Below this a cycle is legible laid out flat; at or above it, it gets a ring. */
const RING_MIN = 3;

// --- colour ------------------------------------------------------------------

/**
 * Node fills by kind, duplicated from the `--kind-*` custom properties in
 * `theme.css`.
 *
 * The duplication is forced: cytoscape paints to a canvas and never resolves
 * CSS custom properties, so `var(--kind-type)` silently resolved to the
 * fallback grey and the whole kind encoding did nothing. `layout.test.ts`
 * fails if these drift from the stylesheet.
 */
export const KIND_COLORS: Readonly<Record<string, string>> = {
  package: "#7aa2f7",
  file: "#7dcfff",
  module: "#e0af68",
  type: "#bb9af7",
  function: "#9ece6a",
  constant: "#ff9e64",
};

const UNKNOWN_KIND = "#6b7489";

export function kindColor(kind: string): string {
  return KIND_COLORS[kind] ?? UNKNOWN_KIND;
}

// --- naming ------------------------------------------------------------------

/**
 * The shortest names that stay unique within one view.
 *
 * A view scoped to `crates/ignore` repeats that prefix on every node, and a
 * whole-project matrix has five files called `mod.rs`. Both extremes are
 * unreadable: one wastes the label on shared context, the other makes distinct
 * rows look identical. Strip what everything shares, then keep just enough
 * trailing path to tell the rest apart.
 */
export function shortLabels(labels: readonly string[]): Map<string, string> {
  const unique = [...new Set(labels)];
  const stripped = new Map(unique.map((label) => [label, stripCommonPrefix(label, unique)]));

  // How many trailing segments each name needs. Grow only the names that
  // collide, so an unambiguous `dir.rs` stays `dir.rs` while `walk.rs` becomes
  // `src/walk.rs`.
  const depth = new Map(unique.map((label) => [label, 1]));
  const nameOf = (label: string) => tail(stripped.get(label)!, depth.get(label)!);

  for (let round = 0; round < 8; round += 1) {
    const byName = new Map<string, string[]>();
    for (const label of unique) {
      const name = nameOf(label);
      byName.set(name, [...(byName.get(name) ?? []), label]);
    }
    const colliding = [...byName.values()].filter((group) => group.length > 1).flat();
    if (colliding.length === 0) break;

    let grew = false;
    for (const label of colliding) {
      const next = depth.get(label)! + 1;
      if (next <= segments(stripped.get(label)!).length) {
        depth.set(label, next);
        grew = true;
      }
    }
    // Nothing left to reveal — the remaining collisions are genuinely identical
    // paths, and lengthening further would only add noise.
    if (!grew) break;
  }

  return new Map(unique.map((label) => [label, nameOf(label)]));
}

function segments(path: string): string[] {
  return path.split("/").filter(Boolean);
}

function tail(path: string, count: number): string {
  const parts = segments(path);
  return parts.slice(Math.max(0, parts.length - count)).join("/");
}

function stripCommonPrefix(label: string, all: readonly string[]): string {
  if (all.length < 2) return label;
  const parts = all.map(segments);
  let shared = 0;
  const shortest = Math.min(...parts.map((p) => p.length));
  // Never consume the last segment: a view of names that are all the same file
  // in different directories must keep the file name.
  while (shared < shortest - 1 && parts.every((p) => p[shared] === parts[0]![shared])) {
    shared += 1;
  }
  return segments(label).slice(shared).join("/");
}

// --- positions ---------------------------------------------------------------

/**
 * Positions from levels: levels stack bottom-up, members spread across a row.
 *
 * The one exception is a cycle. Levelization puts every member of a strongly
 * connected component on the same level, and this view draws *only* cycle
 * edges — so a large component laid out in a straight row draws all of its
 * edges along that row, on top of the nodes, where none of them can be
 * followed. Those components get lifted onto a ring instead, which is also an
 * honest signal: a circle in a levelized diagram means a cycle.
 */
export function positionsFromLevels(
  nodes: readonly PositionedNode[],
  edges: readonly PositionedEdge[] = [],
  options: { spacingY?: number } = {},
): Map<string, Point> {
  const spacingY = options.spacingY ?? SPACING_Y;
  const byLevel = new Map<number, PositionedNode[]>();
  for (const node of nodes) {
    const level = node.level ?? 0;
    byLevel.set(level, [...(byLevel.get(level) ?? []), node]);
  }

  const positions = new Map<string, Point>();

  // Levels top to bottom, each given the vertical room it actually needs. A
  // fixed step would put the level above a ring inside it.
  const rows = [...byLevel.keys()]
    .sort((a, b) => b - a)
    .map((level) => {
      const groups = componentsWithin([...byLevel.get(level)!].sort(byLabel), edges);
      const halfHeight = Math.max(
        0,
        ...groups.map((group) => (group.length >= RING_MIN ? ringRadius(group.length) : 0)),
      );
      return { groups, halfHeight };
    });

  let cursorY = 0;
  for (const { groups, halfHeight } of rows) {
    cursorY += halfHeight;
    const y = cursorY;
    cursorY += halfHeight + spacingY;

    // Width each group needs along the row.
    const widths = groups.map((group) =>
      group.length >= RING_MIN ? 2 * ringRadius(group.length) + SPACING_X : group.length * SPACING_X,
    );
    const total = widths.reduce((sum, width) => sum + width, 0);

    let cursor = -total / 2;
    groups.forEach((group, index) => {
      const width = widths[index]!;
      const centre = cursor + width / 2;
      cursor += width;

      if (group.length >= RING_MIN) {
        const radius = ringRadius(group.length);
        group.forEach((node, position) => {
          const angle = (2 * Math.PI * position) / group.length - Math.PI / 2;
          positions.set(node.id, {
            x: centre + radius * Math.cos(angle),
            y: y + radius * Math.sin(angle),
          });
        });
      } else {
        group.forEach((node, position) => {
          positions.set(node.id, {
            x: centre + (position - (group.length - 1) / 2) * SPACING_X,
            y,
          });
        });
      }
    });
  }
  return positions;
}

/** Arc per ring member. Less than a row's spacing: `shortLabels` has already
 *  taken the shared prefix off, so a ring label is a file name, not a path. */
const RING_ARC = 120;

function ringRadius(size: number): number {
  return Math.max(80, (size * RING_ARC) / (2 * Math.PI));
}

function byLabel(a: PositionedNode, b: PositionedNode): number {
  return a.label.localeCompare(b.label) || a.id.localeCompare(b.id);
}

/**
 * Connected components among nodes of one level, using only the edges drawn
 * inside that level. Those edges are exactly the cycle edges — a levelized view
 * carries every acyclic dependency in the layout and draws none of it.
 */
function componentsWithin(
  members: readonly PositionedNode[],
  edges: readonly PositionedEdge[],
): PositionedNode[][] {
  const rank = new Map(members.map((node, index) => [node.id, index]));
  const parent = members.map((_, index) => index);

  const find = (index: number): number => {
    let root = index;
    while (parent[root] !== root) root = parent[root]!;
    let walk = index;
    while (parent[walk] !== walk) {
      const next = parent[walk]!;
      parent[walk] = root;
      walk = next;
    }
    return root;
  };

  for (const edge of edges) {
    const a = rank.get(edge.source);
    const b = rank.get(edge.target);
    if (a === undefined || b === undefined) continue;
    const rootA = find(a);
    const rootB = find(b);
    if (rootA !== rootB) parent[Math.max(rootA, rootB)] = Math.min(rootA, rootB);
  }

  const grouped = new Map<number, PositionedNode[]>();
  members.forEach((node, index) => {
    const root = find(index);
    grouped.set(root, [...(grouped.get(root) ?? []), node]);
  });
  // Keyed by the lowest member index, so group order follows label order.
  return [...grouped.entries()].sort((a, b) => a[0] - b[0]).map(([, group]) => group);
}

// --- filtering ---------------------------------------------------------------

export interface FilterableNode {
  id: string;
  label: string;
  kind: string;
  producers?: string[];
}

export interface FilterableEdge {
  id: string;
  source: string;
  target: string;
  kind: string;
}

export interface Filters {
  /** Node kinds to keep. Absent means every kind. */
  kinds?: ReadonlySet<string>;
  /** Edge kinds to keep. Absent means every kind. */
  edgeKinds?: ReadonlySet<string>;
  /** Extractors to keep. A node passes if any of its producers is enabled. */
  producers?: ReadonlySet<string>;
}

export interface FilterResult<N, E> {
  nodes: N[];
  edges: E[];
  hiddenNodes: number;
  hiddenEdges: number;
}

/**
 * Narrow a neighbourhood by kind and by which extractor produced it.
 *
 * Two rules the counts depend on. An edge whose other end was hidden goes with
 * it — an arrow to a node that is not drawn is the same defect the protocol
 * model refuses. And the node the reader named is never hidden: filtering away
 * the thing just searched for produces a blank page with no explanation.
 */
export function applyFilters<N extends FilterableNode, E extends FilterableEdge>(
  nodes: readonly N[],
  edges: readonly E[],
  filters: Filters,
  pinned?: string,
): FilterResult<N, E> {
  const keepNode = (node: N): boolean => {
    if (node.id === pinned) return true;
    if (filters.kinds && !filters.kinds.has(node.kind)) return false;
    if (filters.producers) {
      const producers = node.producers ?? [];
      if (!producers.some((p) => filters.producers!.has(p))) return false;
    }
    return true;
  };

  const kept = nodes.filter(keepNode);
  const visible = new Set(kept.map((node) => node.id));
  const keptEdges = edges.filter(
    (edge) =>
      (!filters.edgeKinds || filters.edgeKinds.has(edge.kind)) &&
      visible.has(edge.source) &&
      visible.has(edge.target),
  );

  return {
    nodes: kept,
    edges: keptEdges,
    hiddenNodes: nodes.length - kept.length,
    hiddenEdges: edges.length - keptEdges.length,
  };
}

// --- search ------------------------------------------------------------------

export interface SearchableNode {
  id: string;
  label: string;
  kind?: string;
}

/**
 * Rank search hits so the thing the reader named comes first.
 *
 * A plain substring filter over 4,700 nodes buries the type `Searcher` under
 * every file whose *path* contains "searcher". The reader named a thing; the
 * first result has to be that thing.
 */
export function rankMatches<T extends SearchableNode>(
  nodes: readonly T[],
  query: string,
  limit: number,
): T[] {
  const needle = query.trim().toLowerCase();
  if (needle.length < 2) return [];

  const scored: Array<{ node: T; score: number }> = [];
  for (const node of nodes) {
    const label = node.label.toLowerCase();
    const base = label.split("/").pop() ?? label;
    let score: number;
    if (label === needle) score = 0;
    else if (base === needle) score = 1;
    else if (label.startsWith(needle)) score = 2;
    else if (base.startsWith(needle)) score = 3;
    else if (base.includes(needle)) score = 4;
    else if (label.includes(needle)) score = 5;
    else continue;
    scored.push({ node, score });
  }

  scored.sort(
    (a, b) =>
      a.score - b.score ||
      a.node.label.length - b.node.label.length ||
      a.node.label.localeCompare(b.node.label) ||
      a.node.id.localeCompare(b.node.id),
  );
  return scored.slice(0, limit).map((entry) => entry.node);
}
