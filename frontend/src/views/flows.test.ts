// Flows: interaction diagrams derived from call edges, where one exists.
//
// A flow is a real path from an entry point projected onto modules. It is
// worth drawing only when it crosses enough boundaries — a "flow" inside one
// module is just that module's own control flow, which is what the source is
// for. Every arrow corresponds to a dependency edge an extractor produced, so
// a flow cannot invent an interaction; that is the property that separates it
// from an authored diagram, and it is why `protocol-modeler` handles the cases
// that need reading code instead.

import { describe, expect, it } from "vitest";
import { buildIndex } from "../graph";
import { deriveFlows, flowToMermaid, type Flow } from "./flows";

const N = (id: string, kind: string, path?: string) => ({
  data: { id, label: id.split(":").pop() ?? id, kind, path },
});
const E = (source: string, target: string, kind: string) => ({
  data: { id: `${source}>${target}`, source, target, kind },
});

// main -> build (hiargs) -> walk (walker) -> search (searcher); plus a local
// helper chain inside main.rs that must not become a flow.
const PAYLOAD = {
  revision: "b".repeat(40),
  repository: "local/rg",
  elements: {
    nodes: [
      N("f:main.rs", "file", "core/main.rs"),
      N("f:hiargs.rs", "file", "core/hiargs.rs"),
      N("f:walk.rs", "file", "ignore/walk.rs"),
      N("f:search.rs", "file", "searcher/search.rs"),
      N("s:main", "function", "core/main.rs"),
      N("s:helper", "function", "core/main.rs"),
      N("s:build", "function", "core/hiargs.rs"),
      N("s:walk", "function", "ignore/walk.rs"),
      N("s:search", "function", "searcher/search.rs"),
    ],
    edges: [
      E("f:main.rs", "s:main", "contains"),
      E("f:main.rs", "s:helper", "contains"),
      E("f:hiargs.rs", "s:build", "contains"),
      E("f:walk.rs", "s:walk", "contains"),
      E("f:search.rs", "s:search", "contains"),
      E("s:main", "s:helper", "calls"),
      E("s:main", "s:build", "calls"),
      E("s:build", "s:walk", "calls"),
      E("s:walk", "s:search", "calls"),
    ],
  },
};

const index = buildIndex(PAYLOAD);
const ENTRY = [{ path: "core/main.rs", reason: "binary root" }];

describe("deriveFlows", () => {
  it("finds the chain from an entry point, projected onto modules", () => {
    const flows = deriveFlows(index, ENTRY);
    expect(flows).toHaveLength(1);
    expect(flows[0]!.steps.map((s) => s.fromModule)).toEqual([
      "core/main.rs",
      "core/hiargs.rs",
      "ignore/walk.rs",
    ]);
    expect(flows[0]!.steps.map((s) => s.toModule)).toEqual([
      "core/hiargs.rs",
      "ignore/walk.rs",
      "searcher/search.rs",
    ]);
  });

  it("every step names the symbols behind the arrow", () => {
    const [flow] = deriveFlows(index, ENTRY);
    expect(flow!.steps[0]!.viaLabel).toBe("build");
  });

  it("a chain inside one module is not a flow", () => {
    // main -> helper never leaves main.rs; two modules is below the bar too.
    const flows = deriveFlows(index, ENTRY, { minModules: 3 });
    expect(flows.every((flow) => new Set(flow.steps.map((s) => s.toModule)).size >= 2)).toBe(
      true,
    );
    expect(flows.some((flow) => flow.steps.some((s) => s.viaLabel === "helper"))).toBe(false);
  });

  it("an entry point the graph does not know yields nothing", () => {
    expect(deriveFlows(index, [{ path: "ghost.rs", reason: "?" }])).toEqual([]);
  });

  it("no entry crossing enough modules means no flows, not padded ones", () => {
    const flows = deriveFlows(index, ENTRY, { minModules: 9 });
    expect(flows).toEqual([]);
  });

  it("is deterministic", () => {
    const once = deriveFlows(index, ENTRY);
    const twice = deriveFlows(index, ENTRY);
    expect(once).toEqual(twice);
  });

  it("the default bar is exactly three modules", () => {
    // entry + 2 hops = 3 distinct modules: drawable. One hop fewer is not —
    // the constant itself is under test here, not a caller's override.
    const chainOf = (length: number) => {
      const nodes = [];
      const edges = [];
      for (let i = 0; i < length; i += 1) {
        nodes.push(N(`f:m${i}`, "file", `m${i}.rs`), N(`s:fn${i}`, "function", `m${i}.rs`));
        edges.push(E(`f:m${i}`, `s:fn${i}`, "contains"));
        if (i > 0) edges.push(E(`s:fn${i - 1}`, `s:fn${i}`, "calls"));
      }
      return buildIndex({
        revision: "c".repeat(40),
        repository: "local/chain",
        elements: { nodes, edges },
      });
    };
    const entry = [{ path: "m0.rs", reason: "root" }];
    expect(deriveFlows(chainOf(3), entry)).toHaveLength(1);
    expect(deriveFlows(chainOf(2), entry)).toEqual([]);
  });

  it("a long walk is truncated at the cap and says so", () => {
    // The comment above MAX_STEPS promises "a stated remainder"; a silent cut
    // is a disclosure the code advertises and does not make.
    const nodes = [];
    const edges = [];
    for (let i = 0; i < 20; i += 1) {
      nodes.push(N(`f:m${i}`, "file", `m${i}.rs`), N(`s:fn${i}`, "function", `m${i}.rs`));
      edges.push(E(`f:m${i}`, `s:fn${i}`, "contains"));
      if (i > 0) edges.push(E(`s:fn${i - 1}`, `s:fn${i}`, "calls"));
    }
    const long = buildIndex({
      revision: "c".repeat(40),
      repository: "local/long",
      elements: { nodes, edges },
    });
    const [flow] = deriveFlows(long, [{ path: "m0.rs", reason: "root" }]);
    expect(flow!.steps).toHaveLength(14);
    expect(flow!.truncated).toBe(true);
    // A walk that ends because it has nowhere left to go is not truncated.
    const [short] = deriveFlows(index, ENTRY);
    expect(short!.truncated).toBe(false);
  });
});

describe("flowToMermaid", () => {
  it("emits a sequenceDiagram whose arrows are the steps", () => {
    const [flow] = deriveFlows(index, ENTRY);
    const source = flowToMermaid(flow!);
    expect(source.startsWith("sequenceDiagram")).toBe(true);
    expect(source).toContain("main.rs");
    expect(source).toContain("->>");
    // one arrow per step, no invented ones
    expect(source.match(/->>/g)).toHaveLength(flow!.steps.length);
  });

  it("participants appear once each, in order of first use", () => {
    const [flow] = deriveFlows(index, ENTRY);
    const source = flowToMermaid(flow!);
    const participants = source
      .split("\n")
      .filter((line) => line.trim().startsWith("participant"));
    expect(participants).toHaveLength(4);
  });

  const participantIds = (source: string) =>
    source
      .split("\n")
      .filter((line) => line.trim().startsWith("participant"))
      .map((line) => line.trim().split(" ")[1]!);

  it("modules that clean to the same string still get distinct participants", () => {
    // crates/foo-bar vs crates/foo_bar is routine in Rust (hyphenated crate
    // dir, underscored module). If both alias to one id, Mermaid merges the
    // boxes and every arrow between them becomes a self-loop — a diagram of
    // something that does not exist.
    const flow: Flow = {
      entry: "crates/foo-bar/lib.rs",
      reason: "root",
      moduleCount: 2,
      truncated: false,
      steps: [
        {
          fromModule: "crates/foo-bar/lib.rs",
          toModule: "crates/foo_bar/lib.rs",
          viaLabel: "run",
          viaKind: "calls",
        },
      ],
    };
    const ids = participantIds(flowToMermaid(flow));
    expect(new Set(ids).size).toBe(2);
  });

  it("participant ids never start with a digit", () => {
    // Mermaid rejects `2fars` as a participant id; the module is real, the
    // diagram must still render.
    const flow: Flow = {
      entry: "2fa.rs",
      reason: "root",
      moduleCount: 2,
      truncated: false,
      steps: [
        { fromModule: "2fa.rs", toModule: "auth.rs", viaLabel: "verify", viaKind: "calls" },
      ],
    };
    for (const id of participantIds(flowToMermaid(flow))) {
      expect(id).toMatch(/^[A-Za-z]/);
    }
  });

  it("hostile symbol labels cannot corrupt the diagram", () => {
    // A viaLabel with a newline or semicolon would inject Mermaid syntax —
    // extra lines mean extra arrows, and every arrow claims to be measured.
    const flow: Flow = {
      entry: "a.rs",
      reason: "root",
      moduleCount: 2,
      truncated: false,
      steps: [
        { fromModule: "a.rs", toModule: "b.rs", viaLabel: "bad\nname;x", viaKind: "calls" },
      ],
    };
    const source = flowToMermaid(flow);
    expect(source.match(/->>/g)).toHaveLength(1);
    // Every line must belong to the grammar we emit — header, participant, or
    // arrow. A label fragment floating on its own line is an injection.
    for (const line of source.split("\n")) {
      if (line.trim() === "") continue;
      expect(line).toMatch(/^(sequenceDiagram$|\s+participant \S+ as \S|\s+\S+->>\S+: \S)/);
    }
  });
});
