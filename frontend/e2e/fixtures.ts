// Route-mock payloads shaped exactly like the real API. The Python contract
// tests pin those shapes against schemas/*.json, so a drift there fails on the
// backend rather than silently passing here.

export const HEAD = "f".repeat(40);
export const BASE = "e".repeat(40);
export const RUN_ID = "01J4QDGJ4W8Z9X7C5V3B2N1M0K";

export const RUN = {
  id: RUN_ID,
  repositoryId: "local/kvstore",
  kind: "pr",
  status: "succeeded",
  headSha: HEAD,
  baseSha: BASE,
  prNumber: 7,
  createdAt: "2026-08-06T12:00:00+00:00",
  manifestSha256: "sha256:" + "1".repeat(64),
  graph: { snapshotId: 1, nodeCount: 7, edgeCount: 5, canonicalSha256: "sha256:" + "2".repeat(64) },
  baseGraph: { snapshotId: 2, nodeCount: 6, edgeCount: 4, canonicalSha256: "sha256:" + "3".repeat(64) },
};

export const DETAIL = {
  ...RUN,
  events: [
    { stage: "build_graph", event: "finished", level: "info", at: RUN.createdAt, data: null },
    {
      stage: "base_revision",
      event: "base_graph_cache_hit",
      level: "info",
      at: RUN.createdAt,
      data: { revision: BASE, producedByRunId: "01OTHER" },
    },
  ],
  receipts: [
    {
      extractor: "cargo-metadata",
      extractorVersion: "cargo 1.94.1",
      exitCode: 0,
      configuration: { command: "cargo metadata --format-version 1 --locked" },
    },
  ],
};

export const OVERVIEW = {
  repositoryId: "local/kvstore",
  revision: HEAD,
  packages: [
    { name: "kvstore", version: "0.1.0", manifestPath: "kvstore/Cargo.toml", fileCount: 4, symbolCount: 28 },
  ],
  modules: [
    { key: "file:kvstore/src/cache.rs", path: "kvstore/src/cache.rs", package: "kvstore", fanIn: 3, fanOut: 0, level: 0, symbolCount: 12 },
    { key: "file:kvstore/src/api.rs", path: "kvstore/src/api.rs", package: "kvstore", fanIn: 1, fanOut: 1, level: 1, symbolCount: 8 },
  ],
  levels: [
    { level: 0, modules: ["kvstore/src/cache.rs"] },
    { level: 1, modules: ["kvstore/src/api.rs"] },
  ],
  cycles: [],
  hubs: {
    dependedOn: [
      { key: "file:kvstore/src/cache.rs", path: "kvstore/src/cache.rs", package: "kvstore", fanIn: 3, fanOut: 0, level: 0, symbolCount: 12 },
    ],
    dependsOn: [],
  },
  orphans: [],
  entryPoints: [{ key: "file:kvstore/src/lib.rs", path: "kvstore/src/lib.rs", reason: "library root (lib.rs)" }],
  startHere: [
    { key: "file:kvstore/src/cache.rs", path: "kvstore/src/cache.rs", reason: "3 module(s) depend on it; depends on nothing" },
  ],
  counts: { packages: 1, files: 4, symbols: 28, edges: 30 },
  notes: [],
};

export const VIEWS = {
  repositoryId: "local/kvstore",
  revision: HEAD,
  views: [
    {
      id: "packages",
      kind: "package-dependencies",
      title: "Packages",
      layout: "elk-layered",
      nodes: [
        { id: "pkg:kvstore", label: "kvstore", kind: "package", level: 0, fanIn: 1, fanOut: 0 },
        { id: "pkg:kvstore-cli", label: "kvstore-cli", kind: "package", level: 1, fanIn: 0, fanOut: 1 },
      ],
      edges: [
        { id: "pkgedge:cli", source: "pkg:kvstore-cli", target: "pkg:kvstore", kind: "depends-on", weight: 4 },
      ],
      suppressedEdges: 0,
      readability: { passed: true, checks: [{ name: "node-budget", passed: true, value: 2, limit: 25 }] },
      notes: ["open here: one box per package"],
    },
    {
      id: "matrix",
      kind: "matrix",
      title: "All modules (dependency matrix)",
      layout: "none",
      nodes: [
        { id: "file:kvstore/src/cache.rs", label: "kvstore/src/cache.rs", kind: "file", level: 0, path: "kvstore/src/cache.rs" },
        { id: "file:kvstore/src/api.rs", label: "kvstore/src/api.rs", kind: "file", level: 1, path: "kvstore/src/api.rs" },
      ],
      edges: [
        { id: "cell:1", source: "file:kvstore/src/api.rs", target: "file:kvstore/src/cache.rs", kind: "depends-on", weight: 2 },
      ],
      readability: { passed: true, checks: [] },
      notes: ["ordered by level"],
    },
  ],
  refused: [
    {
      id: "modules:kvstore",
      kind: "levelized-modules",
      failedCheck: "node-budget",
      reason: "node-budget 41 exceeds the limit of 25; this would be a hairball",
    },
  ],
  notes: ["1 view(s) were refused as unreadable"],
};

export const GRAPH = {
  revision: HEAD,
  repository: "local/kvstore",
  elements: {
    nodes: [
      { data: { id: "file:kvstore/src/cache.rs", label: "kvstore/src/cache.rs", kind: "file", path: "kvstore/src/cache.rs" } },
      { data: { id: "sym:evict", label: "evict_oldest", kind: "function", path: "kvstore/src/cache.rs", startLine: 41 } },
      { data: { id: "sym:put", label: "put", kind: "function", path: "kvstore/src/cache.rs", startLine: 23 } },
    ],
    edges: [
      { data: { id: "e1", source: "file:kvstore/src/cache.rs", target: "sym:evict", kind: "contains" } },
      { data: { id: "e2", source: "sym:put", target: "sym:evict", kind: "calls" } },
    ],
  },
};

export const DIFF = {
  baseRevision: BASE,
  headRevision: HEAD,
  nodes: {
    added: [{ stableKey: "sym:evict", id: "sym:evict", kind: "function", label: "evict", path: "kvstore/src/cache.rs", startLine: 41 }],
    removed: [{ stableKey: "sym:evict_oldest", id: "sym:evict_oldest", kind: "function", label: "evict_oldest", path: "kvstore/src/cache.rs", startLine: 41 }],
    moved: [],
    touched: [{ stableKey: "sym:put", id: "sym:put", kind: "function", label: "put", path: "kvstore/src/cache.rs", startLine: 23 }],
  },
  edges: {
    added: [],
    removed: [
      { id: "edge:gone", kind: "calls", sourceKey: "sym:put", targetKey: "sym:evict_oldest", sourceLabel: "put", targetLabel: "evict_oldest" },
    ],
  },
  packageVersionChanges: [{ name: "kvstore", before: "0.1.0", after: "0.2.0" }],
  likelyRenamed: [
    { beforeKey: "sym:evict_oldest", afterKey: "sym:evict", beforeLabel: "evict_oldest", afterLabel: "evict", path: "kvstore/src/cache.rs", confidence: 0.75, basis: "same file and overlapping source range" },
  ],
  unnormalizedIdentities: 0,
  summary: { nodesAdded: 1, nodesRemoved: 1, nodesMoved: 0, nodesTouched: 1, edgesAdded: 0, edgesRemoved: 1 },
};

export const API_CHANGE = {
  baseRevision: BASE,
  headRevision: HEAD,
  packages: [
    {
      name: "kvstore",
      added: ["pub fn kvstore::cache::Cache::evict(&mut self, usize) -> usize"],
      removed: ["pub fn kvstore::cache::Cache::evict_oldest(&mut self, usize)"],
      unchangedCount: 112,
      requiredBump: "major",
      lints: [
        { id: "inherent_method_missing", level: "major", summary: "pub method removed or renamed", locations: ["Cache::evict_oldest at kvstore/src/cache.rs:41"] },
      ],
    },
  ],
  skipped: [{ name: "kvstore-cli", reason: "no library target to expose an API" }],
  tools: { cargoPublicApi: "0.52.0", cargoSemverChecks: "0.50.0" },
};

export const IMPACT = {
  baseRevision: BASE,
  headRevision: HEAD,
  hops: 1,
  maxHops: 2,
  seeds: [{ stableKey: "sym:put", label: "put", path: "kvstore/src/cache.rs", reason: "touched" }],
  impacted: [
    {
      stableKey: "sym:handle_request",
      label: "handle_request",
      kind: "function",
      path: "kvstore/src/api.rs",
      startLine: 12,
      hop: 1,
      rank: "public-api",
      claimStrength: "could-be-affected",
      viaSeed: "sym:put",
      viaEdgeKind: "calls",
    },
  ],
  totalImpacted: 1,
  suppressed: 0,
  basis: "bounded reverse reachability over calls and imports",
  caveat: "Static change-impact analysis reports possibilities, not certainties.",
  notes: [],
};

export const EXPLANATION = {
  summary: "Replaces Cache::evict_oldest with Cache::evict, which reports how many entries it removed.",
  sections: [
    {
      id: "before",
      title: "What it did before",
      claims: [
        {
          text: "evict_oldest looped 0..=n, removing one entry more than asked for.",
          citations: [{ kind: "source", revision: "base", path: "kvstore/src/cache.rs", startLine: 41, endLine: 48 }],
        },
      ],
    },
    {
      id: "after",
      title: "What it does now",
      claims: [
        {
          text: "evict removes at most n entries and returns the count removed.",
          citations: [
            { kind: "source", revision: "head", path: "kvstore/src/cache.rs", startLine: 41, endLine: 55 },
            { kind: "api-item", item: "pub fn kvstore::cache::Cache::evict(&mut self, usize) -> usize" },
          ],
        },
      ],
    },
  ],
  sequenceDiagram: null,
  droppedClaims: [
    { sectionId: "risks", text: "The retry loop was removed.", reason: "scheduler.rs does not exist at the head revision" },
  ],
  notes: [],
};

export const FINDINGS = [
  {
    findingId: "F-0001",
    category: "correctness",
    severity: "high",
    confidence: 0.92,
    claim: "put() passes overflow + 1 and discards the returned count.",
    path: "kvstore/src/cache.rs",
    startLine: 23,
    endLine: 30,
    status: "validated",
    publicationEligible: true,
    introducedByChange: true,
    discoveredBySkill: "reviewer-correctness",
    validation: null,
  },
];

export const SOURCE = {
  revision: HEAD,
  path: "kvstore/src/cache.rs",
  startLine: 40,
  endLine: 44,
  lines: [
    "    /// Evict the `n` oldest entries.",
    "    pub fn evict(&mut self, n: usize) -> usize {",
    "        let mut removed = 0;",
    "        for _ in 0..n {",
    "            match self.order.pop_front() {",
  ],
};
