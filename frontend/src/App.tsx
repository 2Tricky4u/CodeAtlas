import { useEffect, useState } from "react";
import { api, type RunSummary } from "./api";
import { RunDetailView } from "./views/RunDetailView";

export function App() {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listRuns()
      .then(setRuns)
      .catch((e: Error) => setError(e.message));
  }, []);

  return (
    <div style={{ display: "flex", height: "100vh" }}>
      <aside
        style={{
          width: 320,
          borderRight: "1px solid #8884",
          overflowY: "auto",
          padding: "0.5rem",
        }}
      >
        <h1 style={{ fontSize: "1.1rem" }}>CodeAtlas runs</h1>
        {error && <p role="alert">{error}</p>}
        {runs === null && !error && <p>Loading…</p>}
        {runs?.length === 0 && <p>No runs yet.</p>}
        <ul style={{ listStyle: "none", padding: 0 }} data-testid="runs-list">
          {runs?.map((run) => (
            <li key={run.id}>
              <button
                onClick={() => setSelected(run.id)}
                style={{
                  width: "100%",
                  textAlign: "left",
                  padding: "0.4rem",
                  margin: "0.15rem 0",
                  fontWeight: run.id === selected ? "bold" : "normal",
                }}
              >
                <div>{run.repositoryId}</div>
                <small>
                  {run.status} · {run.headSha?.slice(0, 10)} ·{" "}
                  {run.graph ? `${run.graph.nodeCount} nodes` : "no graph"}
                </small>
              </button>
            </li>
          ))}
        </ul>
      </aside>
      <main style={{ flex: 1, overflow: "hidden" }}>
        {selected ? (
          <RunDetailView runId={selected} />
        ) : (
          <p style={{ padding: "1rem" }}>Select a run.</p>
        )}
      </main>
    </div>
  );
}
