// Thin typed client over the read-only CodeAtlas API.

export interface RunSummary {
  id: string;
  repositoryId: string;
  kind: string;
  status: string;
  headSha: string | null;
  createdAt: string;
  manifestSha256: string | null;
  graph: {
    snapshotId: number;
    nodeCount: number;
    edgeCount: number;
    canonicalSha256: string;
  } | null;
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

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`${url}: ${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

export const api = {
  listRuns: () => getJson<RunSummary[]>("/api/runs"),
  runDetail: (id: string) => getJson<RunDetail>(`/api/runs/${id}`),
  runGraph: (id: string) => getJson<GraphPayload>(`/api/runs/${id}/graph`),
  source: (revision: string, path: string, start?: number, end?: number) => {
    const params = new URLSearchParams({ path });
    if (start !== undefined) params.set("start", String(start));
    if (end !== undefined) params.set("end", String(end));
    return getJson<SourceSlice>(`/api/source/${revision}?${params}`);
  },
};
