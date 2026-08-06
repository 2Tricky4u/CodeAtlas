// The graph index: one fetch per run, pure lookups for every drill-down view.
//
// Two rules are inherited from the backend and pinned by tests:
//
// "Defined in" is the `contains` edge — the relation an extractor measured —
// never path equality, which would also sweep in module anchors that happen to
// live at the same path.
//
// Module anchors are excluded from usages. Resolving `use crate::cache::Cache`
// emits references to every module on the way, and counting those as
// dependencies once collapsed 25 of memchr's 35 modules into a single false
// cycle (see graph/symbols.py for the full mechanism). The edges stay in the
// payload; they are simply not what "who uses this" means.

import { api, type GraphPayload } from "./api";

export interface GraphNode {
  id: string;
  label: string;
  kind: string;
  path?: string;
  startLine?: number;
  endLine?: number;
  producers?: string[];
}

/** Edge kinds that mean "depends on", as the overview defines them. */
const DEPENDENCY_KINDS = new Set(["calls", "reads", "imports", "implements", "extends"]);

const ANCHOR_DESCRIPTORS = new Set(["crate/", "super/", "self/"]);

/** Mirrors graph/symbols.py::is_namespace_root plus the module-kind rule. */
function isAnchor(node: GraphNode): boolean {
  if (node.kind === "module") return true;
  const match = /^sym:scip\/\S+ \S+ \S+ \S+ (.+)$/.exec(node.id);
  return match !== null && ANCHOR_DESCRIPTORS.has(match[1]!);
}

function byLabel(a: GraphNode, b: GraphNode): number {
  return a.label.localeCompare(b.label) || a.id.localeCompare(b.id);
}

export interface GraphIndex {
  revision: string;
  nodes: GraphNode[];
  node(id: string): GraphNode | undefined;
  fileByPath(path: string): GraphNode | undefined;
  /** What this file defines — its `contains` targets, anchors excluded. */
  definitionsOf(fileId: string): GraphNode[];
  /** The file a symbol is defined in. */
  fileOf(symbolId: string): GraphNode | undefined;
  /** Symbols that depend on this one. Anchors appear on neither side. */
  usedBy(symbolId: string): GraphNode[];
  uses(symbolId: string): GraphNode[];
  /** Definitions of `path` whose startLine falls in [from, to]. */
  definitionsInRange(path: string, from: number, to: number): GraphNode[];
  /** This file's outgoing dependencies, grouped by the file they land in. */
  moduleImports(fileId: string): [GraphNode, GraphNode[]][];
  /** Who uses this file's definitions, grouped by the file they come from. */
  moduleUsers(fileId: string): [GraphNode, GraphNode[]][];
  /** The dependency edge kind between two symbols, if one exists. */
  edgeKind(sourceId: string, targetId: string): string | undefined;
}

export function buildIndex(payload: GraphPayload): GraphIndex {
  const nodes = payload.elements.nodes.map((n) => n.data as unknown as GraphNode);
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const anchors = new Set(nodes.filter(isAnchor).map((n) => n.id));

  const definitions = new Map<string, GraphNode[]>();
  const definedIn = new Map<string, string>();
  const usedByMap = new Map<string, GraphNode[]>();
  const usesMap = new Map<string, GraphNode[]>();
  const edgeKinds = new Map<string, string>();

  for (const raw of payload.elements.edges) {
    const edge = raw.data as unknown as { source: string; target: string; kind: string };
    const source = byId.get(edge.source);
    const target = byId.get(edge.target);
    if (!source || !target) continue;

    if (edge.kind === "contains" && source.kind === "file" && !anchors.has(target.id)) {
      definitions.set(source.id, [...(definitions.get(source.id) ?? []), target]);
      definedIn.set(target.id, source.id);
      continue;
    }
    if (!DEPENDENCY_KINDS.has(edge.kind)) continue;
    if (anchors.has(source.id) || anchors.has(target.id)) continue;
    usedByMap.set(target.id, [...(usedByMap.get(target.id) ?? []), source]);
    usesMap.set(source.id, [...(usesMap.get(source.id) ?? []), target]);
    edgeKinds.set(JSON.stringify([source.id, target.id]), edge.kind);
  }

  for (const list of [...definitions.values(), ...usedByMap.values(), ...usesMap.values()]) {
    list.sort(byLabel);
  }

  const files = new Map(
    nodes.filter((n) => n.kind === "file" && n.path).map((n) => [n.path!, n]),
  );

  const dedupe = (list: GraphNode[]) => [...new Map(list.map((n) => [n.id, n])).values()];

  const groupByFile = (symbols: GraphNode[]): [GraphNode, GraphNode[]][] => {
    const grouped = new Map<string, GraphNode[]>();
    for (const symbol of symbols) {
      const fileId = definedIn.get(symbol.id);
      if (!fileId) continue;
      grouped.set(fileId, [...(grouped.get(fileId) ?? []), symbol]);
    }
    return [...grouped.entries()]
      .flatMap(([fileId, list]) => {
        const file = byId.get(fileId);
        return file ? [[file, dedupe(list).sort(byLabel)] as [GraphNode, GraphNode[]]] : [];
      })
      .sort(([a], [b]) => byLabel(a, b));
  };

  return {
    revision: payload.revision,
    nodes,
    node: (id) => byId.get(id),
    fileByPath: (path) => files.get(path),
    definitionsOf: (fileId) => definitions.get(fileId) ?? [],
    fileOf: (symbolId) => {
      const fileId = definedIn.get(symbolId);
      return fileId ? byId.get(fileId) : undefined;
    },
    usedBy: (symbolId) => usedByMap.get(symbolId) ?? [],
    uses: (symbolId) => usesMap.get(symbolId) ?? [],
    definitionsInRange: (path, from, to) => {
      const file = files.get(path);
      if (!file) return [];
      return (definitions.get(file.id) ?? [])
        .filter((n) => n.startLine !== undefined && n.startLine >= from && n.startLine <= to)
        .sort((a, b) => a.startLine! - b.startLine!);
    },
    moduleImports: (fileId) => {
      const own = definitions.get(fileId) ?? [];
      const targets = own.flatMap((symbol) => usesMap.get(symbol.id) ?? []);
      return groupByFile(targets.filter((t) => definedIn.get(t.id) !== fileId));
    },
    moduleUsers: (fileId) => {
      const own = definitions.get(fileId) ?? [];
      const callers = own.flatMap((symbol) => usedByMap.get(symbol.id) ?? []);
      return groupByFile(callers.filter((c) => definedIn.get(c.id) !== fileId));
    },
    edgeKind: (sourceId, targetId) => edgeKinds.get(JSON.stringify([sourceId, targetId])),
  };
}

// --- path-finding ------------------------------------------------------------

export interface PathStep {
  node: GraphNode;
  /** The edge kind that led here; undefined on the first step. */
  viaKind?: string;
}

/**
 * The shortest dependency path from one symbol to another, or null.
 *
 * BFS over the same dependency edges the usages use, so a path can never route
 * through a module anchor — an "A reaches B" that goes through `crate/` would
 * be path resolution wearing the costume of a call chain.
 */
export function shortestPath(
  index: GraphIndex,
  fromId: string,
  toId: string,
): PathStep[] | null {
  const from = index.node(fromId);
  const to = index.node(toId);
  if (!from || !to) return null;
  if (fromId === toId) return [{ node: from }];

  const parent = new Map<string, { previous: string; viaKind: string }>();
  const queue = [fromId];
  const seen = new Set([fromId]);

  while (queue.length > 0) {
    const current = queue.shift()!;
    for (const next of index.uses(current)) {
      if (seen.has(next.id)) continue;
      seen.add(next.id);
      parent.set(next.id, {
        previous: current,
        viaKind: index.edgeKind(current, next.id) ?? "depends-on",
      });
      if (next.id === toId) {
        return reconstruct(index, parent, fromId, toId);
      }
      queue.push(next.id);
    }
  }
  return null;
}

function reconstruct(
  index: GraphIndex,
  parent: Map<string, { previous: string; viaKind: string }>,
  fromId: string,
  toId: string,
): PathStep[] {
  const steps: PathStep[] = [];
  let cursor: string | undefined = toId;
  while (cursor !== undefined && cursor !== fromId) {
    const entry = parent.get(cursor);
    steps.unshift({ node: index.node(cursor)!, viaKind: entry?.viaKind });
    cursor = entry?.previous;
  }
  steps.unshift({ node: index.node(fromId)! });
  return steps;
}

// --- the shared, memoised fetch ----------------------------------------------

const cache = new Map<string, Promise<GraphIndex>>();

/** The index for a run. Fetched once; every later call is the same promise. */
export function graphIndex(runId: string): Promise<GraphIndex> {
  let promise = cache.get(runId);
  if (!promise) {
    promise = api.runGraph(runId).then(buildIndex);
    cache.set(runId, promise);
  }
  return promise;
}
