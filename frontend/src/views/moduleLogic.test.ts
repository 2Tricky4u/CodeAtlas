// The module page's pure decisions: how definitions are ordered, and which
// API-delta items belong to this file. Extracted logic, pinned without a DOM.
//
// The ordering rules exist because of walk.rs: 148 alphabetical functions
// buried WalkBuilder, the one symbol a reader opens the file for.

import { describe, expect, it } from "vitest";
import { buildIndex } from "../graph";
import { apiItemsFor, orderDefinitions } from "./moduleLogic";

const N = (id: string, kind: string, path?: string) => ({
  data: { id, label: id.split(":").pop() ?? id, kind, path },
});
const E = (source: string, target: string, kind: string) => ({
  data: { id: `${source}>${target}`, source, target, kind },
});

const index = buildIndex({
  revision: "a".repeat(40),
  repository: "local/kv",
  elements: {
    nodes: [
      N("f:cache.rs", "file", "cache.rs"),
      N("f:api.rs", "file", "api.rs"),
      N("s:Cache", "type", "cache.rs"),
      N("s:put", "function", "cache.rs"),
      N("s:evict", "function", "cache.rs"),
      N("s:LIMIT", "constant", "cache.rs"),
      N("s:weird", "widget", "cache.rs"),
      N("s:handle", "function", "api.rs"),
      N("s:route", "function", "api.rs"),
    ],
    edges: [
      E("f:cache.rs", "s:Cache", "contains"),
      E("f:cache.rs", "s:put", "contains"),
      E("f:cache.rs", "s:evict", "contains"),
      E("f:cache.rs", "s:LIMIT", "contains"),
      E("f:cache.rs", "s:weird", "contains"),
      E("f:api.rs", "s:handle", "contains"),
      E("f:api.rs", "s:route", "contains"),
      // evict has fan-in 2, put has fan-in 1: evict must list first.
      E("s:handle", "s:evict", "calls"),
      E("s:route", "s:evict", "calls"),
      E("s:handle", "s:put", "calls"),
    ],
  },
});

const definitions = index.definitionsOf("f:cache.rs");

describe("orderDefinitions", () => {
  it("groups types before constants before functions, unknown kinds last", () => {
    const kinds = orderDefinitions(definitions, index).map(([kind]) => kind);
    expect(kinds).toEqual(["type", "constant", "function", "widget"]);
  });

  it("within a kind, most-used first, ties alphabetical", () => {
    const groups = new Map(orderDefinitions(definitions, index));
    expect(groups.get("function")!.map((n) => n.id)).toEqual(["s:evict", "s:put"]);
  });
});

describe("apiItemsFor", () => {
  const change = (added: string[], removed: string[] = []) => ({
    baseRevision: "b".repeat(40),
    headRevision: "a".repeat(40),
    packages: [
      {
        name: "kvstore",
        added,
        removed,
        unchangedCount: 0,
        requiredBump: "minor" as const,
      },
    ],
    skipped: [],
    tools: {},
  });

  it("matches a definition on the public surface", () => {
    const items = apiItemsFor(change(["pub fn put(&mut self, key: K, value: V)"]),
      new Set(["put"]));
    expect(items).toEqual([
      { item: "pub fn put(&mut self, key: K, value: V)", what: "added" },
    ]);
  });

  it("does not match a definition inside another identifier", () => {
    // `put` appears inside `compute_output` twice; a substring rule attributes
    // someone else's API change to this file, on an evidentiary panel.
    expect(
      apiItemsFor(change(["pub fn compute_output(&self) -> usize"]), new Set(["put"])),
    ).toEqual([]);
  });

  it("matches labels that end in symbols without matching fragments", () => {
    expect(
      apiItemsFor(change(["impl Iterator for Walk"]), new Set(["Walk"])),
    ).toHaveLength(1);
    expect(
      apiItemsFor(change(["impl Iterator for WalkBuilder"]), new Set(["Walk"])),
    ).toEqual([]);
  });

  it("removed items carry their direction", () => {
    const items = apiItemsFor(change([], ["pub fn evict_oldest(&mut self)"]),
      new Set(["evict_oldest"]));
    expect(items).toEqual([{ item: "pub fn evict_oldest(&mut self)", what: "removed" }]);
  });

  it("no delta means no items, not a crash", () => {
    expect(apiItemsFor(null, new Set(["put"]))).toEqual([]);
  });
});
