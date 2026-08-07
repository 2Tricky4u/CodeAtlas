// Route-mock payloads shaped exactly like the real API. The Python contract
// tests pin those shapes against schemas/*.json, so a drift there fails on the
// backend rather than silently passing here.

export const HEAD = "f".repeat(40);
const BASE = "e".repeat(40);
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
    // A resolved external dependency: cargo reports every crate in the build,
    // and fd's overview drowned one real package under 124 of these.
    { name: "serde", version: "1.0.210", manifestPath: "", fileCount: 0, symbolCount: 0 },
  ],
  modules: [
    // cache.rs carries the depth + churn metrics; api.rs deliberately omits
    // both (a run from before the metrics) so the absence paths stay covered.
    { key: "file:kvstore/src/cache.rs", path: "kvstore/src/cache.rs", package: "kvstore", fanIn: 3, fanOut: 0, level: 0, symbolCount: 12, publicCount: 5, churn: 21 },
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
    dependsOn: [
      { key: "file:kvstore/src/api.rs", path: "kvstore/src/api.rs", package: "kvstore", fanIn: 1, fanOut: 1, level: 1, symbolCount: 8 },
    ],
  },
  orphans: [],
  entryPoints: [
    { key: "file:kvstore/src/lib.rs", path: "kvstore/src/lib.rs", reason: "library root (lib.rs)" },
  ],
  startHere: [
    { key: "file:kvstore/src/lib.rs", path: "kvstore/src/lib.rs", reason: "library root (lib.rs)" },
    { key: "file:kvstore/src/cache.rs", path: "kvstore/src/cache.rs", reason: "most depended on" },
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
      // `public` is the measured visibility metric (W2): put is `pub`,
      // evict_oldest is not, and nodes without the key predate the metric.
      { data: { id: "sym:evict", label: "evict_oldest", kind: "function", path: "kvstore/src/cache.rs", startLine: 41, endLine: 48, producers: ["rust-analyzer"], public: false } },
      { data: { id: "sym:put", label: "put", kind: "function", path: "kvstore/src/cache.rs", startLine: 23, producers: ["rust-analyzer"], public: true } },
      // A second connected component, so "no path" stays expressible: handle
      // calls parse, and neither touches the cache symbols.
      { data: { id: "file:kvstore/src/api.rs", label: "kvstore/src/api.rs", kind: "file", path: "kvstore/src/api.rs", producers: ["rust-analyzer"] } },
      { data: { id: "sym:handle", label: "handle_request", kind: "function", path: "kvstore/src/api.rs", startLine: 15, producers: ["rust-analyzer"] } },
      { data: { id: "sym:parse", label: "parse", kind: "function", path: "kvstore/src/api.rs", startLine: 40, producers: ["rust-analyzer"] } },
      // The entry-point chain lib.rs -> api.rs -> fmt.rs: three modules, so
      // deriveFlows finally has a flow to draw under mock. It joins the api
      // component without touching the cache one — the no-path test depends
      // on handle never reaching evict.
      { data: { id: "file:kvstore/src/lib.rs", label: "kvstore/src/lib.rs", kind: "file", path: "kvstore/src/lib.rs", producers: ["rust-analyzer"] } },
      { data: { id: "sym:run", label: "run", kind: "function", path: "kvstore/src/lib.rs", startLine: 5, producers: ["rust-analyzer"] } },
      { data: { id: "file:kvstore/src/fmt.rs", label: "kvstore/src/fmt.rs", kind: "file", path: "kvstore/src/fmt.rs", producers: ["rust-analyzer"] } },
      { data: { id: "sym:render", label: "render", kind: "function", path: "kvstore/src/fmt.rs", startLine: 8, producers: ["rust-analyzer"] } },
    ],
    edges: [
      { data: { id: "e0", source: "pkg:kvstore", target: "file:kvstore/src/cache.rs", kind: "contains" } },
      { data: { id: "e1", source: "file:kvstore/src/cache.rs", target: "sym:evict", kind: "contains" } },
      { data: { id: "e1b", source: "file:kvstore/src/cache.rs", target: "sym:put", kind: "contains" } },
      { data: { id: "e2", source: "sym:put", target: "sym:evict", kind: "calls" } },
      { data: { id: "e3", source: "file:kvstore/src/api.rs", target: "sym:handle", kind: "contains" } },
      { data: { id: "e4", source: "file:kvstore/src/api.rs", target: "sym:parse", kind: "contains" } },
      { data: { id: "e5", source: "sym:handle", target: "sym:parse", kind: "calls" } },
      { data: { id: "e6", source: "file:kvstore/src/lib.rs", target: "sym:run", kind: "contains" } },
      { data: { id: "e7", source: "file:kvstore/src/fmt.rs", target: "sym:render", kind: "contains" } },
      { data: { id: "e8", source: "sym:run", target: "sym:handle", kind: "calls" } },
      { data: { id: "e9", source: "sym:handle", target: "sym:render", kind: "calls" } },
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
  // Non-zero on purpose: the diff's own honesty counter must render.
  unnormalizedIdentities: 2,
  summary: { nodesAdded: 1, nodesRemoved: 1, nodesMoved: 0, nodesTouched: 1, edgesAdded: 0, edgesRemoved: 1 },
};

export const API_CHANGE = {
  baseRevision: BASE,
  headRevision: HEAD,
  packages: [
    {
      name: "kvstore",
      added: [
        "pub fn kvstore::cache::Cache::evict(&mut self, usize) -> usize",
        // `compute_output` contains `put` as a substring; the module page must
        // not attribute this item to cache.rs's `put`.
        "pub fn kvstore::api::compute_output(&self) -> usize",
      ],
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
      acceptanceCriteria: ["a put at capacity evicts exactly one entry"],
    },
    {
      id: "REQ-002",
      sourceKind: "spec",
      sourceRef: "docs/SPEC.md",
      text: "Requests arrive untrusted; a malformed request must produce an error, never terminate the process.",
      acceptanceCriteria: [],
    },
  ],
  nonGoals: ["distributed operation"],
  compatibilityObligations: ["the public put/evict signatures"],
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
    {
      findingId: "F-0012",
      category: "correctness",
      severity: "low",
      claim: "get() clones the value on every hit.",
      discoveredBySkill: "reviewer-correctness",
      location: { path: "kvstore/src/cache.rs", startLine: 33 },
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

// A *decided* approval — the CLI stores exactly "approved"/"rejected"
// (publication/gate.py). No fixture ever carried a decision before, which is
// how a wrong string comparison rendered approved runs as rejected.
export const APPROVALS_DECIDED = [
  {
    ...APPROVALS[0]!,
    decidedAt: "2026-08-06T13:00:00+00:00",
    decidedBy: "xaga",
    decision: "approved",
    decisionNote: "matches what I read in the diff",
  },
];

// The git tree at the revision — including files the graph has no node for,
// which is what makes the explorer more than a list of modules.
export const FILES = [
  { path: "Cargo.toml", language: null, isGenerated: false },
  { path: "README.md", language: null, isGenerated: false },
  { path: "kvstore/Cargo.toml", language: null, isGenerated: false },
  { path: "kvstore/src/api.rs", language: "rust", isGenerated: false },
  { path: "kvstore/src/cache.rs", language: "rust", isGenerated: false },
  { path: "kvstore/src/fmt.rs", language: "rust", isGenerated: false },
  { path: "kvstore/src/gen.rs", language: "rust", isGenerated: true },
  { path: "kvstore/src/lib.rs", language: "rust", isGenerated: false },
];

export const MANIFEST = {
  runId: RUN_ID,
  kind: "pr",
  sourceLock: {
    repositoryId: "local/kvstore",
    headSha: HEAD,
    baseSha: BASE,
    mergeBaseSha: BASE,
    changedPaths: ["kvstore/src/cache.rs"],
    generatedPaths: ["kvstore/src/gen.rs"],
  },
  toolchain: { "cargo-metadata": "cargo 1.94.1", "rust-analyzer-scip": "0.3.2199" },
  skillRegistrySha256: "sha256:" + "a".repeat(64),
  configSha256: "sha256:" + "b".repeat(64),
  modelIds: ["claude-sonnet-5"],
  cassetteIds: [],
  outputs: {
    projectGraph: "sha256:" + "2".repeat(64),
    cytoscape: "sha256:" + "6".repeat(64),
  },
  cost: { totalPromptTokens: 41000, totalCompletionTokens: 9000, totalCostUsd: null },
  notes: ["verification tools unavailable: cargo-clippy"],
};

export const INVOCATIONS = [
  {
    skillId: "intent-reconstructor",
    skillVersion: "1.0.0",
    engine: "replay",
    modelId: "claude-sonnet-5",
    cassetteKey: "intent-reconstructor-1.0.0-fixture000000001",
    status: "succeeded",
    promptTokens: 18000,
    completionTokens: 3000,
    costUsd: null,
    durationMs: 900,
  },
  {
    skillId: "reviewer-correctness",
    skillVersion: "1.0.0",
    engine: "replay",
    modelId: "claude-sonnet-5",
    cassetteKey: "reviewer-correctness-1.0.0-fixture000000002",
    status: "succeeded",
    promptTokens: 23000,
    completionTokens: 6000,
    costUsd: null,
    durationMs: 1400,
  },
];

export const API_SURFACE = {
  revision: HEAD,
  tool: "cargo-public-api 0.52.0",
  packages: [
    {
      name: "kvstore",
      version: "0.2.0",
      manifestPath: "kvstore/Cargo.toml",
      items: [
        "pub fn kvstore::cache::Cache::evict(&mut self, usize) -> usize",
        "pub struct kvstore::cache::Cache",
      ],
    },
  ],
  skipped: [{ name: "kvstore-cli", reason: "no library target to expose an API" }],
};

export const PUBLICATION_PUBLISHED = [
  {
    id: 1,
    approvalId: 1,
    targetKind: "github_pr_review",
    status: "published",
    externalRef: "https://github.com/o/r/pull/7#pullrequestreview-9",
    publishedAt: "2026-08-06T13:05:00+00:00",
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
    // The adversarial validator's own record — the product's differentiator,
    // previously fetched and rendered nowhere.
    validation: {
      reason: "reproduced: evict(overflow + 1) removes one entry more than capacity requires",
      counterEvidenceChecked: ["callers of put", "existing eviction tests"],
      evidence: [{ kind: "call-path", command: "put -> evict" }],
      duplicateOf: null,
    },
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
  // Suppressed by cross-run memory (ADR-0016): no validator ran this run —
  // the record is the earlier run's rejection, replayed with its provenance.
  {
    findingId: "F-0012",
    category: "correctness",
    severity: "low",
    confidence: 0.6,
    claim: "get() clones the value on every hit.",
    path: "kvstore/src/cache.rs",
    startLine: 33,
    endLine: 35,
    status: "suppressed",
    publicationEligible: false,
    introducedByChange: null,
    discoveredBySkill: "reviewer-correctness",
    validation: {
      status: "suppressed",
      memoryFingerprint: "sha256:" + "7".repeat(64),
      decidedInRun: "01J4QDGJ4W8Z9X7C5V3B2N1M0Z",
      reason: "the clone is required by the wire format; returning a reference cannot cross the response boundary",
      rememberedBlobSha: "9".repeat(40),
    },
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

// --- a second run: repository kind, at a size the first fixture stays too ----
// --- small to exercise -------------------------------------------------------
//
// Serves two purposes: run-switch scenarios (stale state must not leak from
// one run to the next), and a module big enough to trigger the definition
// collapse, the focus neighbour cap and the flow-walk truncation.

const HEAD2 = "d".repeat(40);
export const RUN_ID_2 = "01J4QDGJ4W8Z9X7C5V3B2N1M0R";

export const RUN2 = {
  id: RUN_ID_2,
  repositoryId: "local/bigmod",
  kind: "repository",
  status: "succeeded",
  headSha: HEAD2,
  baseSha: null,
  prNumber: null,
  createdAt: "2026-08-07T09:00:00+00:00",
  manifestSha256: "sha256:" + "4".repeat(64),
  graph: { snapshotId: 3, nodeCount: 81, edgeCount: 95, canonicalSha256: "sha256:" + "5".repeat(64) },
  baseGraph: null,
};

export const DETAIL2 = { ...RUN2, events: [], receipts: [] };

const pad = (n: number) => String(n).padStart(2, "0");

const bigElements = (() => {
  const nodes: { data: Record<string, unknown> }[] = [
    { data: { id: "file2:big/src/lib.rs", label: "big/src/lib.rs", kind: "file", path: "big/src/lib.rs", producers: ["rust-analyzer"] } },
  ];
  const edges: { data: Record<string, unknown> }[] = [];
  const define = (id: string, label: string, kind: string, startLine: number) => {
    nodes.push({ data: { id, label, kind, path: "big/src/lib.rs", startLine, producers: ["rust-analyzer"] } });
    edges.push({ data: { id: `c:${id}`, source: "file2:big/src/lib.rs", target: id, kind: "contains" } });
  };

  // Four types with descending fan-in: Alpha 26, Beta 2, Gamma 1, Delta 0.
  define("sym2:Alpha", "Alpha", "type", 3);
  define("sym2:Beta", "Beta", "type", 9);
  define("sym2:Gamma", "Gamma", "type", 15);
  define("sym2:Delta", "Delta", "type", 21);
  // Thirteen constants: one past GROUP_LIMIT, so this group collapses — and
  // must stay collapsed when a *function* is deep-linked.
  for (let i = 0; i < 13; i += 1) define(`sym2:K${pad(i)}`, `K${pad(i)}`, "constant", 30 + i);
  // Twenty-six functions, every one reading Alpha — the focus hub past the
  // 24-neighbour cap. f13 is called by three siblings, so fan-in ranking must
  // lift it above the alphabet.
  for (let i = 0; i < 26; i += 1) {
    const id = `sym2:f${pad(i)}`;
    define(id, `f${pad(i)}`, "function", 60 + i * 4);
    edges.push({ data: { id: `r:${id}`, source: id, target: "sym2:Alpha", kind: "reads" } });
  }
  for (const caller of ["f00", "f01", "f02"]) {
    edges.push({ data: { id: `call:${caller}`, source: `sym2:${caller}`, target: "sym2:f13", kind: "calls" } });
  }
  edges.push({ data: { id: "rb:0", source: "sym2:f00", target: "sym2:Beta", kind: "reads" } });
  edges.push({ data: { id: "rb:1", source: "sym2:f01", target: "sym2:Beta", kind: "reads" } });
  edges.push({ data: { id: "rg:0", source: "sym2:f00", target: "sym2:Gamma", kind: "reads" } });

  // A 17-module call chain: the flow walk must hit its 14-step cap and state
  // the remainder instead of silently ending the story.
  for (let i = 0; i < 17; i += 1) {
    const path = `big/src/c${pad(i)}.rs`;
    const file = `file2:${path}`;
    const fn = `sym2:g${pad(i)}`;
    nodes.push({ data: { id: file, label: path, kind: "file", path, producers: ["rust-analyzer"] } });
    nodes.push({ data: { id: fn, label: `g${pad(i)}`, kind: "function", path, startLine: 1, producers: ["rust-analyzer"] } });
    edges.push({ data: { id: `cc:${i}`, source: file, target: fn, kind: "contains" } });
    if (i > 0) {
      edges.push({ data: { id: `gc:${i}`, source: `sym2:g${pad(i - 1)}`, target: fn, kind: "calls" } });
    }
  }
  return { nodes, edges };
})();

export const GRAPH2 = { revision: HEAD2, repository: "local/bigmod", elements: bigElements };

export const OVERVIEW2 = {
  repositoryId: "local/bigmod",
  revision: HEAD2,
  packages: [
    { name: "big", version: "0.1.0", manifestPath: "big/Cargo.toml", fileCount: 18, symbolCount: 60 },
  ],
  modules: [
    { key: "file2:big/src/lib.rs", path: "big/src/lib.rs", package: "big", fanIn: 0, fanOut: 0, level: 0, symbolCount: 43 },
    { key: "file2:big/src/c00.rs", path: "big/src/c00.rs", package: "big", fanIn: 0, fanOut: 1, level: 1, symbolCount: 1 },
  ],
  levels: [{ level: 0, modules: ["big/src/lib.rs"] }],
  cycles: [],
  hubs: { dependedOn: [], dependsOn: [] },
  orphans: [],
  entryPoints: [{ key: "file2:big/src/c00.rs", path: "big/src/c00.rs", reason: "binary root" }],
  startHere: [],
  counts: { packages: 1, files: 18, symbols: 60, edges: 95 },
  notes: [],
};

export const VIEWS2 = {
  repositoryId: "local/bigmod",
  revision: HEAD2,
  views: [
    {
      id: "packages",
      kind: "package-dependencies",
      title: "Packages",
      layout: "elk-layered",
      nodes: [{ id: "pkg:big", label: "big", kind: "package", level: 0, fanIn: 0, fanOut: 0 }],
      edges: [],
      suppressedEdges: 0,
      readability: { passed: true, checks: [] },
      notes: [],
    },
  ],
  refused: [],
  notes: [],
};
