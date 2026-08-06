// The graph index: the pure lookups every drill-down view is built on.
//
// The subtleties here are inherited from hard-won backend lessons, so they are
// pinned: "defined in" is the measured `contains` edge rather than path
// equality, and module anchors are excluded from usages — counting them once
// made 25 of memchr's 35 modules collapse into a single false cycle
// (graph/symbols.py documents the mechanism).

import { describe, expect, it } from "vitest";
import { buildIndex, shortestPath } from "./graph";

const N = (id: string, kind: string, extra: Record<string, unknown> = {}) => ({
  data: { id, label: id.split("/").pop() ?? id, kind, producers: ["rust-analyzer"], ...extra },
});
const E = (source: string, target: string, kind: string) => ({
  data: { id: `${source}->${target}:${kind}`, source, target, kind },
});

const PAYLOAD = {
  revision: "a".repeat(40),
  repository: "local/kv",
  elements: {
    nodes: [
      N("file:src/cache.rs", "file", { path: "src/cache.rs" }),
      N("file:src/api.rs", "file", { path: "src/api.rs" }),
      N("sym:Cache#", "type", { path: "src/cache.rs", startLine: 6 }),
      N("sym:put().", "function", { path: "src/cache.rs", startLine: 23 }),
      N("sym:evict().", "function", { path: "src/cache.rs", startLine: 41 }),
      N("sym:handle().", "function", { path: "src/api.rs", startLine: 15 }),
      // A module anchor: the thing `use crate::cache::…` references on the way.
      N("sym:cache/", "module", { path: "src/cache.rs" }),
    ],
    edges: [
      E("file:src/cache.rs", "sym:Cache#", "contains"),
      E("file:src/cache.rs", "sym:put().", "contains"),
      E("file:src/cache.rs", "sym:evict().", "contains"),
      E("file:src/api.rs", "sym:handle().", "contains"),
      E("sym:put().", "sym:evict().", "calls"),
      E("sym:handle().", "sym:put().", "calls"),
      E("sym:handle().", "sym:Cache#", "reads"),
      // Namespace traffic that must not count as usage.
      E("sym:handle().", "sym:cache/", "imports"),
      E("sym:cache/", "sym:Cache#", "contains"),
    ],
  },
};

const index = buildIndex(PAYLOAD);

describe("definitions", () => {
  it("come from the contains edge, not from sharing a path", () => {
    // The module anchor also lives at src/cache.rs; a path-equality rule would
    // list it as a definition of the file. The measured relation does not.
    const defined = index.definitionsOf("file:src/cache.rs").map((n) => n.id);
    expect(defined).toEqual(["sym:Cache#", "sym:evict().", "sym:put()."]);
  });

  it("resolve a file by its path", () => {
    expect(index.fileByPath("src/cache.rs")?.id).toBe("file:src/cache.rs");
  });

  it("an unknown file yields nothing rather than throwing", () => {
    expect(index.definitionsOf("file:src/ghost.rs")).toEqual([]);
    expect(index.fileByPath("src/ghost.rs")).toBeUndefined();
  });
});

describe("usages", () => {
  it("who uses this symbol, as symbols", () => {
    expect(index.usedBy("sym:evict().").map((n) => n.id)).toEqual(["sym:put()."]);
    expect(index.usedBy("sym:put().").map((n) => n.id)).toEqual(["sym:handle()."]);
  });

  it("what this symbol uses", () => {
    expect(index.uses("sym:handle().").map((n) => n.id)).toEqual(["sym:Cache#", "sym:put()."]);
  });

  it("module anchors never appear on either side", () => {
    // handle() imports the `cache/` anchor; that is path resolution, not a
    // dependency, and counting it is how the false 25-module cycle happened.
    expect(index.uses("sym:handle().").map((n) => n.id)).not.toContain("sym:cache/");
    expect(index.usedBy("sym:Cache#").map((n) => n.id)).toEqual(["sym:handle()."]);
  });

  it("contains is not a usage", () => {
    expect(index.usedBy("sym:put().").map((n) => n.id)).not.toContain("file:src/cache.rs");
  });

  it("an unknown symbol yields nothing rather than throwing", () => {
    expect(index.usedBy("sym:ghost")).toEqual([]);
    expect(index.uses("sym:ghost")).toEqual([]);
  });
});

describe("definitions in a line range", () => {
  it("finds the symbols defined between two lines of a file", () => {
    const hits = index.definitionsInRange("src/cache.rs", 20, 45).map((n) => n.id);
    expect(hits).toEqual(["sym:put().", "sym:evict()."]);
  });

  it("a symbol without a start line is never ranged", () => {
    expect(index.definitionsInRange("src/cache.rs", 1, 999).map((n) => n.id)).not.toContain(
      "sym:cache/",
    );
  });
});

describe("shortestPath", () => {
  it("finds the dependency path between two symbols", () => {
    const path = shortestPath(index, "sym:handle().", "sym:evict().");
    expect(path?.map((step) => step.node.id)).toEqual([
      "sym:handle().",
      "sym:put().",
      "sym:evict().",
    ]);
    expect(path?.[1]?.viaKind).toBe("calls");
  });

  it("reports absence rather than inventing a route", () => {
    // evict() depends on nothing; there is no path outward from it.
    expect(shortestPath(index, "sym:evict().", "sym:handle().")).toBeNull();
  });

  it("never routes through a module anchor", () => {
    // The only route to Cache# from handle() ignoring anchors is the direct
    // reads edge; via the anchor would be imports -> contains, which is not a
    // dependency chain.
    const path = shortestPath(index, "sym:handle().", "sym:Cache#");
    expect(path?.map((step) => step.node.id)).toEqual(["sym:handle().", "sym:Cache#"]);
  });

  it("a path from a node to itself is that node", () => {
    const path = shortestPath(index, "sym:put().", "sym:put().");
    expect(path?.map((step) => step.node.id)).toEqual(["sym:put()."]);
  });

  it("each hop names the real edge kind, not a default", () => {
    // handle() *reads* Cache#; a hop that reported "calls" here would be a
    // stub pretending to be data.
    const path = shortestPath(index, "sym:handle().", "sym:Cache#");
    expect(path?.[1]?.viaKind).toBe("reads");
  });
});

describe("edgeKind", () => {
  it("answers for a dependency edge and not for contains", () => {
    expect(index.edgeKind("sym:put().", "sym:evict().")).toBe("calls");
    expect(index.edgeKind("file:src/cache.rs", "sym:put().")).toBeUndefined();
  });
});

describe("module-level rollup", () => {
  it("aggregates a file's imports by target module", () => {
    const imports = index.moduleImports("file:src/api.rs");
    expect(imports.map(([file, symbols]) => [file.id, symbols.map((s) => s.id)])).toEqual([
      ["file:src/cache.rs", ["sym:Cache#", "sym:put()."]],
    ]);
  });

  it("aggregates who uses a file's definitions, by their module", () => {
    const users = index.moduleUsers("file:src/cache.rs");
    expect(users.map(([file, symbols]) => [file.id, symbols.map((s) => s.id)])).toEqual([
      ["file:src/api.rs", ["sym:handle()."]],
    ]);
  });

  it("intra-file traffic is not a module dependency", () => {
    // put() calls evict(), both in cache.rs — that must not make cache.rs
    // appear to import or be used by itself.
    expect(index.moduleImports("file:src/cache.rs")).toEqual([]);
    expect(index.moduleUsers("file:src/api.rs")).toEqual([]);
  });
});
