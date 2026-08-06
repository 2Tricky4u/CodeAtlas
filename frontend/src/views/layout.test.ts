// The map's pure geometry and naming. These are the parts that broke at real
// size (ripgrep: 104 modules, an 8-node cycle inside one package, five files
// named `mod.rs`) and none of it is reachable from a Playwright assertion.

import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { KIND_COLORS, kindColor, positionsFromLevels, rankMatches, shortLabels } from "./layout";

const node = (id: string, level: number, label = id) => ({ id, label, level, kind: "module" });

describe("kindColor", () => {
  it("matches the stylesheet it duplicates", () => {
    // The canvas renderer cannot read CSS custom properties, so these values
    // have to be literals — which means they can drift. This is the gate.
    const css = readFileSync(new URL("../theme.css", import.meta.url), "utf8");
    const declared = new Map(
      [...css.matchAll(/--kind-([a-z]+):\s*(#[0-9a-f]{6})/gi)].map(
        (match) => [match[1]!, match[2]!.toLowerCase()] as const,
      ),
    );
    expect(declared.size).toBeGreaterThan(0);
    expect(Object.fromEntries(declared)).toEqual(KIND_COLORS);
  });

  it("falls back rather than rendering nothing for an unknown kind", () => {
    expect(kindColor("something-new")).toMatch(/^#[0-9a-f]{6}$/);
  });
});

describe("shortLabels", () => {
  it("strips the prefix every label shares", () => {
    const short = shortLabels(["crates/ignore/src/dir.rs", "crates/ignore/src/walk.rs"]);
    expect(short.get("crates/ignore/src/dir.rs")).toBe("dir.rs");
    expect(short.get("crates/ignore/src/walk.rs")).toBe("walk.rs");
  });

  it("keeps enough path to stay unique", () => {
    // ripgrep's `ignore` crate has walk.rs three times over.
    const short = shortLabels([
      "crates/ignore/src/walk.rs",
      "crates/ignore/examples/walk.rs",
      "crates/ignore/src/dir.rs",
    ]);
    expect(short.get("crates/ignore/src/walk.rs")).toBe("src/walk.rs");
    expect(short.get("crates/ignore/examples/walk.rs")).toBe("examples/walk.rs");
    expect(short.get("crates/ignore/src/dir.rs")).toBe("dir.rs");
  });

  it("never collapses two different labels onto one name", () => {
    // Five `mod.rs` in one matrix is what made the live matrix unreadable.
    const labels = [
      "crates/core/flags/mod.rs",
      "crates/searcher/src/searcher/mod.rs",
      "crates/printer/src/hyperlink/mod.rs",
      "crates/core/search/mod.rs",
      "build.rs",
    ];
    const short = shortLabels(labels);
    expect(new Set(short.values()).size).toBe(labels.length);
    for (const label of labels) expect(label.endsWith(short.get(label)!)).toBe(true);
  });

  it("leaves a single label alone rather than emptying it", () => {
    expect(shortLabels(["crates/ignore/src/lib.rs"]).get("crates/ignore/src/lib.rs")).toBe(
      "lib.rs",
    );
  });

  it("is stable regardless of input order", () => {
    const a = shortLabels(["a/x.rs", "b/x.rs", "c/y.rs"]);
    const b = shortLabels(["c/y.rs", "b/x.rs", "a/x.rs"]);
    expect([...a.entries()].sort()).toEqual([...b.entries()].sort());
  });
});

describe("positionsFromLevels", () => {
  it("stacks levels bottom-up so dependencies sit below dependents", () => {
    const positions = positionsFromLevels([node("a", 2), node("b", 0)], []);
    expect(positions.get("b")!.y).toBeGreaterThan(positions.get("a")!.y);
  });

  it("spreads a level horizontally", () => {
    const positions = positionsFromLevels([node("a", 0), node("b", 0), node("c", 0)], []);
    const xs = ["a", "b", "c"].map((id) => positions.get(id)!.x);
    expect(new Set(xs).size).toBe(3);
    expect(positions.get("a")!.y).toBe(positions.get("c")!.y);
  });

  it("lifts a cycle out of the row into a ring", () => {
    // Eight mutually-dependent modules share a level. Laid out collinearly the
    // cycle edges — the only edges this view draws — run along the row and
    // cannot be traced. A ring gives every edge angular separation.
    const members = ["m0", "m1", "m2", "m3", "m4", "m5", "m6", "m7"];
    const nodes = members.map((id) => node(id, 3));
    const edges = members.map((id, i) => ({
      id: `e${i}`,
      source: id,
      target: members[(i + 1) % members.length]!,
    }));

    const positions = positionsFromLevels(nodes, edges);
    const ys = members.map((id) => positions.get(id)!.y);
    expect(new Set(ys).size).toBeGreaterThan(1);

    // Every member is a real distance from the ring's centre, so no two sit on
    // top of each other and no edge is collinear with the node row.
    const cx = members.reduce((sum, id) => sum + positions.get(id)!.x, 0) / members.length;
    const cy = ys.reduce((sum, y) => sum + y, 0) / members.length;
    const radii = members.map((id) => {
      const p = positions.get(id)!;
      return Math.hypot(p.x - cx, p.y - cy);
    });
    expect(Math.min(...radii)).toBeGreaterThan(40);
    expect(Math.max(...radii) - Math.min(...radii)).toBeLessThan(1);
  });

  it("gives a ring vertical room instead of letting neighbouring levels sit in it", () => {
    // A ring is tall. With levels a fixed distance apart, the level above lands
    // inside the ring and its labels print on top of the cycle's.
    const members = ["m0", "m1", "m2", "m3", "m4", "m5", "m6", "m7"];
    const nodes = [
      ...members.map((id) => node(id, 1)),
      node("above", 2),
      node("below", 0),
    ];
    const edges = members.map((id, i) => ({
      id: `e${i}`,
      source: id,
      target: members[(i + 1) % members.length]!,
    }));

    const positions = positionsFromLevels(nodes, edges);
    const ringYs = members.map((id) => positions.get(id)!.y);
    // y grows downward, so a higher level sits at a smaller y.
    expect(positions.get("above")!.y).toBeLessThan(Math.min(...ringYs) - 40);
    expect(positions.get("below")!.y).toBeGreaterThan(Math.max(...ringYs) + 40);
  });

  it("takes a tighter vertical step when the caller asks for one", () => {
    // The architecture view stacks six levels of short wide boxes; at the map's
    // spacing that is 650px tall in a panel that is not, and `fit` shrinks the
    // labels to six pixels.
    const nodes = [node("a", 0), node("b", 1)];
    const tight = positionsFromLevels(nodes, [], { spacingY: 90 });
    const loose = positionsFromLevels(nodes, []);
    const span = (p: Map<string, { x: number; y: number }>) =>
      Math.abs(p.get("a")!.y - p.get("b")!.y);
    expect(span(tight)).toBe(90);
    expect(span(tight)).toBeLessThan(span(loose));
  });

  it("leaves a mutual pair in the row", () => {
    // Two nodes are already legible side by side; a ring would be noise.
    const nodes = [node("a", 1), node("b", 1)];
    const edges = [
      { id: "e0", source: "a", target: "b" },
      { id: "e1", source: "b", target: "a" },
    ];
    const positions = positionsFromLevels(nodes, edges);
    expect(positions.get("a")!.y).toBe(positions.get("b")!.y);
  });

  it("keeps a ring from overlapping its neighbours in the row", () => {
    const ring = ["c0", "c1", "c2", "c3"];
    const nodes = [node("solo", 1), ...ring.map((id) => node(id, 1))];
    const edges = ring.map((id, i) => ({
      id: `e${i}`,
      source: id,
      target: ring[(i + 1) % ring.length]!,
    }));
    const positions = positionsFromLevels(nodes, edges);
    const ringXs = ring.map((id) => positions.get(id)!.x);
    const soloX = positions.get("solo")!.x;
    const gap = Math.min(...ringXs.map((x) => Math.abs(x - soloX)));
    expect(gap).toBeGreaterThan(20);
  });

  it("ignores edges that cross levels when finding cycles", () => {
    const nodes = [node("a", 0), node("b", 1)];
    const edges = [{ id: "e", source: "b", target: "a" }];
    const positions = positionsFromLevels(nodes, edges);
    expect(positions.get("a")!.x).toBe(0);
    expect(positions.get("b")!.x).toBe(0);
  });

  it("is a pure function of the data", () => {
    const nodes = [node("a", 0), node("b", 1), node("c", 1)];
    const first = positionsFromLevels(nodes, []);
    const second = positionsFromLevels([...nodes].reverse(), []);
    for (const id of ["a", "b", "c"]) expect(first.get(id)).toEqual(second.get(id));
  });
});

describe("rankMatches", () => {
  const graph = [
    { id: "1", label: "crates/searcher/src/searcher/mod.rs", kind: "file" },
    { id: "2", label: "crates/searcher/src/lib.rs", kind: "file" },
    { id: "3", label: "Searcher", kind: "type" },
    { id: "4", label: "SearcherBuilder", kind: "type" },
    { id: "5", label: "build_searcher", kind: "function" },
  ];

  it("puts the thing you actually named first", () => {
    // The live run ranked twelve file paths above the type named `Searcher`.
    expect(rankMatches(graph, "Searcher", 12)[0]!.label).toBe("Searcher");
  });

  it("prefers a prefix match over a match buried mid-string", () => {
    const ranked = rankMatches(graph, "Searcher", 12).map((n) => n.label);
    expect(ranked.indexOf("SearcherBuilder")).toBeLessThan(ranked.indexOf("build_searcher"));
  });

  it("matches on the basename, not just the whole path", () => {
    const ranked = rankMatches(graph, "lib.rs", 12);
    expect(ranked[0]!.label).toBe("crates/searcher/src/lib.rs");
  });

  it("is case-insensitive", () => {
    expect(rankMatches(graph, "searcher", 12)[0]!.label).toBe("Searcher");
  });

  it("honours the limit and returns nothing for a short query", () => {
    expect(rankMatches(graph, "Searcher", 2)).toHaveLength(2);
    expect(rankMatches(graph, "S", 12)).toHaveLength(0);
  });

  it("breaks ties deterministically", () => {
    const tied = [
      { id: "b", label: "zzz_alpha", kind: "type" },
      { id: "a", label: "zzz_alpha", kind: "type" },
    ];
    expect(rankMatches(tied, "zzz_alpha", 12).map((n) => n.id)).toEqual(["a", "b"]);
  });
});
