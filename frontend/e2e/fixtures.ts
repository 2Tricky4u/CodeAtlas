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
    // `producers` is on every node in the real payload — `artifacts/cytoscape.py`
    // has carried it since M6 so the dashboard could filter on evidence type.
    nodes: [
      { data: { id: "pkg:kvstore", label: "kvstore 0.1.0", kind: "package", producers: ["cargo"] } },
      { data: { id: "file:kvstore/src/cache.rs", label: "kvstore/src/cache.rs", kind: "file", path: "kvstore/src/cache.rs", producers: ["rust-analyzer"] } },
      { data: { id: "sym:evict", label: "evict_oldest", kind: "function", path: "kvstore/src/cache.rs", startLine: 41, producers: ["rust-analyzer"] } },
      { data: { id: "sym:put", label: "put", kind: "function", path: "kvstore/src/cache.rs", startLine: 23, producers: ["rust-analyzer"] } },
      // A second connected component, so "no path" stays expressible: handle
      // calls parse, and neither touches the cache symbols.
      { data: { id: "file:kvstore/src/api.rs", label: "kvstore/src/api.rs", kind: "file", path: "kvstore/src/api.rs", producers: ["rust-analyzer"] } },
      { data: { id: "sym:handle", label: "handle_request", kind: "function", path: "kvstore/src/api.rs", startLine: 15, producers: ["rust-analyzer"] } },
      { data: { id: "sym:parse", label: "parse", kind: "function", path: "kvstore/src/api.rs", startLine: 40, producers: ["rust-analyzer"] } },
    ],
    edges: [
      { data: { id: "e0", source: "pkg:kvstore", target: "file:kvstore/src/cache.rs", kind: "contains" } },
      { data: { id: "e1", source: "file:kvstore/src/cache.rs", target: "sym:evict", kind: "contains" } },
      { data: { id: "e1b", source: "file:kvstore/src/cache.rs", target: "sym:put", kind: "contains" } },
      { data: { id: "e2", source: "sym:put", target: "sym:evict", kind: "calls" } },
      { data: { id: "e3", source: "file:kvstore/src/api.rs", target: "sym:handle", kind: "contains" } },
      { data: { id: "e4", source: "file:kvstore/src/api.rs", target: "sym:parse", kind: "contains" } },
      { data: { id: "e5", source: "sym:handle", target: "sym:parse", kind: "calls" } },
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
  labels: [
    {
      name: "rename",
      basis: "evict_oldest appears to have become evict (overlapping range, confidence 0.86)",
    },
    { name: "internal-interface", basis: "3 symbol(s) changed and none appear in the public API delta" },
  ],
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

export const ARCHITECTURE = {
  repositoryId: "local/kvstore",
  revision: HEAD,
  systemName: "kvstore",
  containers: [
    {
      key: "kvstore",
      name: "kvstore",
      description: "kvstore 0.1.0",
      technology: "rust",
      level: 0,
      fanIn: 1,
      fanOut: 0,
      evidenceNodeId: "pkg:cargo/kvstore@0.1.0",
      path: "kvstore/Cargo.toml",
    },
    {
      key: "kvstore_cli",
      name: "kvstore-cli",
      description: "kvstore-cli 0.1.0",
      technology: "rust",
      level: 1,
      fanIn: 0,
      fanOut: 1,
      evidenceNodeId: "pkg:cargo/kvstore-cli@0.1.0",
      path: "kvstore-cli/Cargo.toml",
    },
  ],
  relationships: [
    {
      sourceKey: "kvstore_cli",
      targetKey: "kvstore",
      description: "depends-on",
      evidenceEdgeId: "edge:9f2c1b7a4d8e",
    },
  ],
  readability: {
    passed: true,
    checks: [{ name: "node-budget", passed: true, value: 2, limit: 25 }],
  },
  notes: ["3 package(s) resolved by the build but not present in this repository are not drawn: they are dependencies, not containers"],
};

export const INTENT = {
  requirements: [
    {
      id: "REQ-001",
      sourceKind: "spec",
      sourceRef: "docs/SPEC.md",
      text: "The cache holds at most max_entries entries; a write past the bound evicts only as many as necessary.",
      acceptanceCriteria: [],
    },
    {
      id: "REQ-002",
      sourceKind: "spec",
      sourceRef: "docs/SPEC.md",
      text: "Requests arrive untrusted; a malformed request must produce an error, never terminate the process.",
      acceptanceCriteria: [],
    },
  ],
  nonGoals: [],
  compatibilityObligations: [],
  unresolvedQuestions: ["whether eviction should be LRU or insertion-ordered"],
};

/** Two candidates. F-0001 validated and publishable; F-0009 unresolved — the
 *  verdict that is neither a pass nor a rejection, and the one most easily
 *  mistaken for either. */
export const CANDIDATE_FINDINGS = {
  findings: [
    {
      findingId: "F-0001",
      category: "correctness",
      severity: "high",
      claim: "put() passes overflow + 1 and discards the returned count.",
      discoveredBySkill: "reviewer-correctness",
      location: { path: "kvstore/src/cache.rs", startLine: 23 },
    },
    {
      findingId: "F-0009",
      category: "security",
      severity: "medium",
      claim: "The cache is shared across threads without synchronisation.",
      discoveredBySkill: "reviewer-security",
      location: { path: "kvstore/src/cache.rs", startLine: 12 },
    },
  ],
};

export const REVIEW_MARKDOWN = `# CodeAtlas review

1 finding survived validation of 2 candidates.

## kvstore/src/cache.rs:23 — high
put() passes overflow + 1 and discards the returned count.
`;

export const REVIEW_PAYLOAD = {
  owner: "local",
  repo: "kvstore",
  prNumber: 7,
  commitSha: HEAD,
  body: "CodeAtlas found 1 issue introduced by this change.",
  comments: [{ path: "kvstore/src/cache.rs", line: 23, body: "off-by-one in eviction" }],
  event: "COMMENT",
};

export const APPROVALS = [
  {
    id: 1,
    actionKind: "pr-review-comment",
    payloadSha256: "sha256:" + "9".repeat(64),
    requestedAt: "2026-08-06T12:05:00+00:00",
    decidedAt: null,
    decidedBy: null,
    decision: null,
  },
];

export const PROTOCOL_MODEL = {
  protocol: {
    id: "kvstore-wire",
    version: "1",
    transport: "in-process call from the CLI binary",
    framing: "colon-separated fields (`verb:arg[:arg]`)",
    participants: [
      {
        name: "client",
        description: "Sends one colon-separated command per argument.",
        evidence: { path: "kvstore-cli/src/main.rs", startLine: 5, endLine: 12 },
      },
      {
        name: "store",
        description: "Parses the command and answers from the cache.",
        evidence: { path: "kvstore/src/api.rs", startLine: 15, endLine: 33 },
      },
    ],
    states: [],
    messages: [
      {
        name: "get",
        producer: "client",
        consumer: "store",
        schema: "get:<key>",
        evidence: { path: "kvstore/src/api.rs", startLine: 18, endLine: 24 },
      },
      {
        name: "Response::Value | Response::Error",
        producer: "store",
        consumer: "client",
        evidence: { path: "kvstore/src/api.rs", startLine: 5, endLine: 10 },
      },
    ],
    timeouts: [],
    evidence: [{ path: "kvstore/src/api.rs", startLine: 12, endLine: 14 }],
  },
  droppedElements: [
    {
      kind: "message",
      name: "Subscribe",
      reason: "kvstore/src/pubsub.rs does not exist at this revision",
    },
  ],
  notes: [
    "The exchange is stateless: each request is dispatched independently and no session state is carried between requests.",
  ],
};

/** The common case. ripgrep, a compiler, a linter — none of them speak one. */
export const PROTOCOL_NONE = {
  notes: [
    "This project is a batch search tool: it walks directories, matches lines against a regex and writes results to stdout. Nothing is exchanged with another party over time, so there is no protocol to model.",
  ],
};

export const PROTOCOL_SEQUENCE = `sequenceDiagram
    autonumber
    participant client as client
    participant store as store
    client->>store: get
    store->>client: Response::Value | Response::Error
`;

export const ADR_AUDIT = {
  revision: HEAD,
  decisions: [
    {
      adr: "docs/adr/adr-0001-layering.md",
      label: "ADR-0001",
      number: 1,
      title: "Layering",
      status: "accepted",
      date: "2026-01-15",
      supersededBy: null,
      assertion: "Dependencies flow downward through api -> cache -> storage.",
      auditResult: "probable-drift",
      confidence: 0.85,
      requiresHumanDecision: true,
      affectedNodes: ["file:kvstore/src/storage.rs"],
      evidence: [{ edge: "edge:70615f911899" }],
      detail: "storage.rs imports crate::api::Response, which the decision prohibits.",
    },
    {
      adr: "docs/adr/adr-0002-cache.md",
      label: "ADR-0002",
      number: 2,
      title: "Bounded cache",
      status: "superseded",
      date: "2026-02-02",
      supersededBy: "ADR-0005",
      assertion: "The cache is bounded by entry count.",
      auditResult: "intentionally-superseded",
      confidence: 1,
      requiresHumanDecision: false,
      affectedNodes: [],
      evidence: [],
      detail: "",
    },
    {
      adr: "docs/adr/adr-0003-protocol.md",
      label: "ADR-0003",
      number: 3,
      title: "Wire protocol",
      status: "accepted",
      date: "2026-03-09",
      supersededBy: null,
      assertion: "Requests are colon-separated verb forms.",
      auditResult: "unverifiable",
      confidence: 0.2,
      requiresHumanDecision: false,
      affectedNodes: [],
      evidence: [],
      detail: "",
    },
  ],
  notes: [
    "1 decision(s) show probable drift from the code",
    "1 decision(s) could not be checked: there was no evidence in the graph to check them against, which is not the same as conformance",
  ],
};

export const STRUCTURIZR_DSL = `workspace "kvstore" "Architecture derived from the CodeAtlas project graph" {
    model {
        sys_kvstore = softwareSystem "kvstore" {
            kvstore = container "kvstore" "kvstore 0.1.0" "rust"
        }
    }
}
`;

// Independent of the change: "what is this project" is answerable for a
// repository run that has no diff at all.
export const PROJECT_EXPLANATION = {
  summary:
    "kvstore is a single-crate in-process key-value store with an HTTP front end, bounded by an LRU cache.",
  sections: [
    {
      id: "entry",
      title: "Where to start reading",
      claims: [
        {
          text: "main.rs binds the listener and constructs the store the rest of the code shares.",
          citations: [
            { kind: "module", key: "kvstore/src/main.rs" },
            { kind: "source", path: "kvstore/src/main.rs", startLine: 1, endLine: 24 },
          ],
        },
      ],
    },
    {
      id: "caution",
      title: "What will surprise you",
      claims: [
        {
          text: "api.rs and storage.rs depend on each other, so neither can be read alone.",
          citations: [
            { kind: "cycle", members: ["kvstore/src/api.rs", "kvstore/src/storage.rs"] },
          ],
        },
      ],
    },
  ],
  droppedClaims: [
    {
      sectionId: "hotspots",
      text: "The scheduler is the busiest module.",
      reason: "kvstore/src/scheduler.rs is not a module this overview measured",
    },
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
  // Persisted like every candidate, with the verdict it received. `unresolved`
  // is not a pass: the validator could neither confirm nor refute it.
  {
    findingId: "F-0009",
    category: "security",
    severity: "medium",
    confidence: 0.4,
    claim: "The cache is shared across threads without synchronisation.",
    path: "kvstore/src/cache.rs",
    startLine: 12,
    endLine: 18,
    status: "unresolved",
    publicationEligible: false,
    introducedByChange: false,
    discoveredBySkill: "reviewer-security",
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
