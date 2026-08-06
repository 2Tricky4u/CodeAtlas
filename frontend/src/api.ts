// Thin typed client over the read-only CodeAtlas API.
//
// Types here mirror the JSON Schemas in /schemas, which are the source of
// truth; the Python contract tests pin the wire shapes these assume.

export interface RunSummary {
  id: string;
  repositoryId: string;
  kind: string;
  status: string;
  headSha: string | null;
  baseSha: string | null;
  prNumber: number | null;
  createdAt: string;
  manifestSha256: string | null;
  graph: GraphMeta | null;
  baseGraph: GraphMeta | null;
}

export interface GraphMeta {
  snapshotId: number;
  nodeCount: number;
  edgeCount: number;
  canonicalSha256: string;
}

export interface RunEvent {
  stage: string;
  event: string;
  level: string;
  at: string;
  data: Record<string, unknown> | null;
}

export interface RunDetail extends RunSummary {
  events: RunEvent[];
  receipts: Record<string, unknown>[];
}

export interface CytoscapeElement {
  data: Record<string, unknown> & { id: string };
}

export interface GraphPayload {
  revision: string;
  repository: string;
  elements: { nodes: CytoscapeElement[]; edges: CytoscapeElement[] };
}

export interface SourceSlice {
  revision: string;
  path: string;
  startLine: number;
  endLine: number;
  lines: string[];
}

// --- project-overview.v1 ----------------------------------------------------

export interface OverviewSuggestion {
  key?: string | null;
  path: string;
  reason: string;
}

export interface ModuleSummary {
  key: string;
  path: string;
  package?: string | null;
  fanIn: number;
  fanOut: number;
  level: number;
  symbolCount: number;
}

export interface ProjectOverview {
  repositoryId: string;
  revision: string;
  packages: {
    name: string;
    version: string;
    manifestPath?: string;
    fileCount: number;
    symbolCount: number;
  }[];
  modules: ModuleSummary[];
  levels: { level: number; modules: string[] }[];
  cycles: { members: string[]; edges: { from: string; to: string }[] }[];
  hubs: { dependedOn: ModuleSummary[]; dependsOn: ModuleSummary[] };
  orphans: ModuleSummary[];
  entryPoints: OverviewSuggestion[];
  startHere: OverviewSuggestion[];
  counts: { packages: number; files: number; symbols: number; edges: number };
  notes: string[];
}

// --- graph-view.v1 ----------------------------------------------------------

export interface ViewNode {
  id: string;
  label: string;
  kind: string;
  parent?: string | null;
  level?: number | null;
  path?: string | null;
  fanIn?: number | null;
  fanOut?: number | null;
  inCycle?: boolean;
}

export interface ViewEdge {
  id: string;
  source: string;
  target: string;
  kind: string;
  weight?: number | null;
  violatesLevels?: boolean;
}

export interface ReadabilityCheck {
  name: string;
  passed: boolean;
  value: number;
  limit: number;
}

export interface GraphView {
  id: string;
  kind: "package-dependencies" | "levelized-modules" | "matrix" | "neighborhood";
  title: string;
  scope?: string | null;
  layout: string;
  nodes: ViewNode[];
  edges: ViewEdge[];
  suppressedEdges?: number;
  readability: { passed: boolean; checks: ReadabilityCheck[] };
  notes?: string[];
}

export interface GraphViews {
  repositoryId: string;
  revision: string;
  views: GraphView[];
  refused: { id: string; kind: string; failedCheck: string; reason: string }[];
  notes: string[];
}

// --- change artifacts -------------------------------------------------------

export interface DiffNode {
  stableKey: string;
  id: string;
  kind: string;
  label: string;
  path?: string;
  startLine?: number;
  endLine?: number;
}

export interface DiffEdge {
  id: string;
  kind: string;
  sourceKey: string;
  targetKey: string;
  sourceLabel: string;
  targetLabel: string;
  sourcePath?: string;
  targetPath?: string;
}

/** Only the labels the diff can prove; interpretation stays in the narrative. */
export interface ChangeLabel {
  name: string;
  basis: string;
}

export interface GraphDiff {
  baseRevision: string;
  headRevision: string;
  nodes: { added: DiffNode[]; removed: DiffNode[]; moved: MovedNode[]; touched: DiffNode[] };
  edges: { added: DiffEdge[]; removed: DiffEdge[] };
  packageVersionChanges: { name: string; before: string; after: string }[];
  likelyRenamed: RenameGuess[];
  labels?: ChangeLabel[];
  unnormalizedIdentities: number;
  summary: Record<string, number>;
}

export interface MovedNode {
  stableKey: string;
  kind: string;
  label: string;
  beforePath: string;
  afterPath: string;
}

export interface RenameGuess {
  beforeKey: string;
  afterKey: string;
  beforeLabel: string;
  afterLabel: string;
  path?: string;
  confidence: number;
  basis: string;
}

export interface SemverLint {
  id: string;
  level: "major" | "minor";
  summary: string;
  locations?: string[];
}

export interface PackageApiDelta {
  name: string;
  added: string[];
  removed: string[];
  unchangedCount: number;
  requiredBump: "major" | "minor" | "none" | "unknown";
  bumpUnknownReason?: string | null;
  lints?: SemverLint[];
}

export interface ApiChange {
  baseRevision: string;
  headRevision: string;
  packages: PackageApiDelta[];
  skipped: { name: string; reason: string }[];
  tools: Record<string, string>;
}

export interface ImpactedSymbol {
  stableKey: string;
  label: string;
  kind: string;
  path?: string;
  startLine?: number;
  endLine?: number;
  hop: number;
  rank: "public-api" | "crate-crossing" | "internal" | "test-only";
  claimStrength: "referred-to-removed-symbol" | "could-be-affected";
  viaSeed: string;
  viaEdgeKind?: string;
}

export interface ChangeImpact {
  baseRevision: string;
  headRevision: string;
  hops: number;
  maxHops: number;
  seeds: { stableKey: string; label: string; path?: string; reason: "touched" | "removed" }[];
  impacted: ImpactedSymbol[];
  totalImpacted: number;
  suppressed: number;
  basis: string;
  caveat: string;
  notes: string[];
}

export type Citation =
  | { kind: "source"; revision: "base" | "head"; path: string; startLine?: number; endLine?: number }
  | { kind: "graph-edge"; edgeId: string }
  | { kind: "api-item"; item: string }
  | { kind: "impact"; stableKey: string };

export interface ExplanationClaim {
  text: string;
  citations: Citation[];
}

export interface ChangeExplanation {
  summary: string;
  sections: { id: string; title: string; claims: ExplanationClaim[] }[];
  sequenceDiagram?: string | null;
  droppedClaims?: { sectionId: string; text: string; reason: string }[];
  notes?: string[];
}

// --- architecture -----------------------------------------------------------

export interface ArchitectureContainer {
  key: string;
  name: string;
  description?: string;
  technology?: string;
  level?: number | null;
  fanIn?: number | null;
  fanOut?: number | null;
  /** The graph node this box was derived from — nothing is drawn without one. */
  evidenceNodeId: string;
  path?: string | null;
}

export interface ArchitectureRelationship {
  sourceKey: string;
  targetKey: string;
  description: string;
  evidenceEdgeId: string;
  weight?: number | null;
}

export interface Architecture {
  repositoryId: string;
  revision: string;
  systemName: string;
  containers: ArchitectureContainer[];
  relationships: ArchitectureRelationship[];
  readability?: { passed: boolean; checks: ReadabilityCheck[] } | null;
  notes?: string[];
}

// --- protocol ---------------------------------------------------------------

export interface ProtocolEvidence {
  path: string;
  symbol?: string;
  startLine?: number;
  endLine?: number;
}

export interface ProtocolParticipant {
  name: string;
  description?: string;
  evidence: ProtocolEvidence;
}

export interface ProtocolMessage {
  name: string;
  producer: string;
  consumer: string;
  schema?: string | null;
  evidence: ProtocolEvidence;
}

export interface ProtocolTimeout {
  state: string;
  duration: string;
  transition: string;
  evidence?: ProtocolEvidence;
}

export interface Protocol {
  id: string;
  version: string;
  transport: string;
  framing: string;
  participants: ProtocolParticipant[];
  states: string[];
  messages: ProtocolMessage[];
  timeouts: ProtocolTimeout[];
  evidence: ProtocolEvidence[];
}

export interface ProtocolModel {
  /** Absent when this project has no protocol — the common case. */
  protocol?: Protocol | null;
  droppedElements?: { kind: string; name: string; reason: string }[];
  notes?: string[];
}

// --- architecture decisions -------------------------------------------------

export type AuditResult =
  | "conformant"
  | "probable-drift"
  | "unverifiable"
  | "intentionally-superseded";

export interface AuditedDecision {
  adr: string;
  label: string;
  number?: number | null;
  title?: string | null;
  status: string;
  date?: string | null;
  supersededBy?: string | null;
  assertion: string;
  auditResult: AuditResult;
  confidence: number;
  requiresHumanDecision: boolean;
  affectedNodes?: string[];
  evidence?: Record<string, unknown>[];
  detail?: string;
}

export interface AdrAudit {
  revision: string;
  decisions: AuditedDecision[];
  notes?: string[];
}

// --- project narrative ------------------------------------------------------

/** One revision, so no `revision` field — see project-explanation.v1. */
export type ProjectCitation =
  | { kind: "source"; path: string; startLine?: number; endLine?: number }
  | { kind: "module"; key: string }
  | { kind: "package"; name: string }
  | { kind: "cycle"; members: string[] };

export interface ProjectClaim {
  text: string;
  citations: ProjectCitation[];
}

export interface ProjectExplanation {
  summary: string;
  sections: { id: string; title: string; claims: ProjectClaim[] }[];
  droppedClaims?: { sectionId: string; text: string; reason: string }[];
  notes?: string[];
}

export interface Finding {
  findingId: string;
  category: string;
  severity: string;
  confidence: number;
  claim: string;
  path: string;
  startLine: number | null;
  endLine: number | null;
  status: string;
  publicationEligible: boolean;
  introducedByChange: boolean | null;
  discoveredBySkill: string;
  validation: Record<string, unknown> | null;
}

// --- fetch ------------------------------------------------------------------

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`${url}: ${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

/** Text artifacts — the Structurizr DSL, the rendered review — are documents. */
async function getOptionalText(url: string): Promise<string | null> {
  const response = await fetch(url);
  if (!response.ok) return null;
  return await response.text();
}

/** Absence of an optional artifact is a state, not an error. */
async function getOptional<T>(url: string): Promise<T | null> {
  const response = await fetch(url);
  if (response.status === 404) return null;
  if (!response.ok) {
    throw new Error(`${url}: ${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

export const api = {
  listRuns: () => getJson<RunSummary[]>("/api/runs"),
  runDetail: (id: string) => getJson<RunDetail>(`/api/runs/${id}`),
  runGraph: (id: string) => getJson<GraphPayload>(`/api/runs/${id}/graph`),
  overview: (id: string) => getJson<ProjectOverview>(`/api/runs/${id}/overview`),
  views: (id: string) => getJson<GraphViews>(`/api/runs/${id}/views`),
  findings: (id: string) => getJson<Finding[]>(`/api/runs/${id}/findings`),
  graphDiff: (id: string) => getOptional<GraphDiff>(`/api/runs/${id}/artifact/graph-diff`),
  apiChange: (id: string) => getOptional<ApiChange>(`/api/runs/${id}/artifact/api-change`),
  impact: (id: string) => getOptional<ChangeImpact>(`/api/runs/${id}/artifact/change-impact`),
  explanation: (id: string) =>
    getOptional<ChangeExplanation>(`/api/runs/${id}/artifact/change-explanation`),
  projectExplanation: (id: string) =>
    getOptional<ProjectExplanation>(`/api/runs/${id}/artifact/project-explanation`),
  architecture: (id: string) =>
    getOptional<Architecture>(`/api/runs/${id}/artifact/architecture`),
  structurizrDsl: (id: string) => getOptionalText(`/api/runs/${id}/artifact/structurizr-dsl`),
  adrAudit: (id: string) => getOptional<AdrAudit>(`/api/runs/${id}/artifact/adr-audit`),
  protocolModel: (id: string) =>
    getOptional<ProtocolModel>(`/api/runs/${id}/artifact/protocol-model`),
  protocolDiagram: (id: string, kind: "sequence" | "state") =>
    getOptionalText(`/api/runs/${id}/artifact/protocol-${kind}`),
  source: (revision: string, path: string, start?: number, end?: number) => {
    const params = new URLSearchParams({ path });
    if (start !== undefined) params.set("start", String(start));
    if (end !== undefined) params.set("end", String(end));
    return getJson<SourceSlice>(`/api/source/${revision}?${params}`);
  },
};
