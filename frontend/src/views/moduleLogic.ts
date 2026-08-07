// Pure decisions behind the module page, extracted so they can be pinned by
// unit tests without a DOM: how a file's definitions are ordered, and which
// API-delta items actually name one of them.

import type { ApiChange } from "../api";
import type { GraphIndex, GraphNode } from "../graph";

// Types before functions: a file's types are its vocabulary and the reason a
// reader opens it. walk.rs has 148 functions; alphabetical order buried
// WalkBuilder below all of them.
const KIND_ORDER = ["type", "constant", "function"];

/** Definitions grouped by kind (KIND_ORDER first, unknown kinds after), each
 *  group most-used first — fan-in is why a definition matters. */
export function orderDefinitions(
  definitions: GraphNode[],
  index: GraphIndex,
): [string, GraphNode[]][] {
  const grouped = new Map<string, GraphNode[]>();
  for (const definition of definitions) {
    grouped.set(definition.kind, [...(grouped.get(definition.kind) ?? []), definition]);
  }
  for (const list of grouped.values()) {
    list.sort(
      (a, b) =>
        index.usedBy(b.id).length - index.usedBy(a.id).length ||
        a.label.localeCompare(b.label),
    );
  }
  return [...grouped.entries()].sort(
    ([a], [b]) =>
      (KIND_ORDER.indexOf(a) + 1 || 99) - (KIND_ORDER.indexOf(b) + 1 || 99) ||
      a.localeCompare(b),
  );
}

/** The API-delta items that name one of this file's definitions.
 *
 *  Whole-identifier match, not substring: `put` occurs inside
 *  `compute_output`, and attributing someone else's API change to this file
 *  would be a false claim on an evidentiary panel. */
export function apiItemsFor(
  apiChange: ApiChange | null,
  labels: ReadonlySet<string>,
): { item: string; what: "added" | "removed" }[] {
  if (!apiChange || labels.size === 0) return [];
  const patterns = [...labels].map(
    (label) =>
      new RegExp(
        `(?<![A-Za-z0-9_])${label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?![A-Za-z0-9_])`,
      ),
  );
  const namesOne = (item: string) => patterns.some((pattern) => pattern.test(item));
  return apiChange.packages.flatMap((pkg) =>
    [
      ...pkg.added.map((item) => ({ item, what: "added" as const })),
      ...pkg.removed.map((item) => ({ item, what: "removed" as const })),
    ].filter(({ item }) => namesOne(item)),
  );
}
