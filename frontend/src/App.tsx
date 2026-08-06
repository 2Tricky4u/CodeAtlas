import { useEffect, useState } from "react";
import {
  HashRouter,
  Navigate,
  NavLink,
  Outlet,
  Route,
  Routes,
  useParams,
} from "react-router-dom";
import { api, type RunSummary } from "./api";
import { Badge, ErrorBox, Loading, shortSha, STATUS_TONE } from "./ui";
import { AdrView } from "./views/AdrView";
import { ArchitectureView } from "./views/ArchitectureView";
import { ChangeView } from "./views/ChangeView";
import { DetailView } from "./views/DetailView";
import { FindingsView } from "./views/FindingsView";
import { MapView } from "./views/MapView";
import { ModuleView } from "./views/ModuleView";
import { OverviewView } from "./views/OverviewView";
import { ProtocolView } from "./views/ProtocolView";
import { ReviewView } from "./views/ReviewView";

export function App() {
  return (
    <HashRouter>
      <Routes>
        <Route element={<Shell />}>
          <Route index element={<Landing />} />
          <Route path="runs/:runId" element={<RunLayout />}>
            <Route index element={<Navigate to="overview" replace />} />
            <Route path="overview" element={<OverviewView />} />
            <Route path="map" element={<MapView />} />
            <Route path="architecture" element={<ArchitectureView />} />
            <Route path="adr" element={<AdrView />} />
            <Route path="protocol" element={<ProtocolView />} />
            <Route path="change" element={<ChangeView />} />
            <Route path="findings" element={<FindingsView />} />
            <Route path="review" element={<ReviewView />} />
            <Route path="detail" element={<DetailView />} />
            {/* Splat: module paths contain slashes. Not a tab — reached by
                clicking any module named anywhere in the app. */}
            <Route path="module/*" element={<ModuleView />} />
          </Route>
        </Route>
      </Routes>
    </HashRouter>
  );
}

function Shell() {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
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
          width: 300,
          flexShrink: 0,
          borderRight: "1px solid var(--border)",
          background: "var(--bg-1)",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <div
          style={{
            padding: "12px 14px",
            borderBottom: "1px solid var(--border)",
            display: "flex",
            alignItems: "baseline",
            gap: 8,
          }}
        >
          <NavLink to="/" style={{ color: "var(--fg-0)", fontWeight: 600 }}>
            code<span style={{ color: "var(--accent)" }}>atlas</span>
          </NavLink>
          <span className="microlabel">evidence-first</span>
        </div>
        <nav style={{ overflowY: "auto", padding: 8, flex: 1 }} data-testid="runs-list">
          {error && <ErrorBox error={error} />}
          {runs === null && !error && <Loading />}
          {runs?.length === 0 && <p className="empty-state">no runs yet</p>}
          {runs?.map((run) => (
            <NavLink
              key={run.id}
              to={`/runs/${run.id}`}
              className={({ isActive }) => `run-entry ${isActive ? "active" : ""}`}
            >
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>
                  {run.repositoryId}
                </span>
                {run.kind === "pr" && <Badge tone="accent">PR #{run.prNumber ?? "?"}</Badge>}
              </div>
              <div style={{ display: "flex", gap: 8, marginTop: 2, alignItems: "baseline" }}>
                <Badge tone={STATUS_TONE[run.status] ?? "plain"}>{run.status}</Badge>
                <span className="note mono-num">{shortSha(run.headSha)}</span>
                {run.graph && (
                  <span className="note mono-num">{run.graph.nodeCount}n</span>
                )}
              </div>
            </NavLink>
          ))}
        </nav>
      </aside>
      <main style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
        <Outlet />
      </main>
    </div>
  );
}

function Landing() {
  return (
    <div className="empty-state" style={{ marginTop: "20vh" }}>
      <div style={{ fontSize: 20, color: "var(--fg-1)" }}>
        code<span style={{ color: "var(--accent)" }}>atlas</span>
      </div>
      <p>select a run to explore its project map, change analysis and findings</p>
      <p className="note">
        every claim in here traces back to a pinned revision, an extractor receipt, or a
        validated finding — and anything that could not be verified says so
      </p>
    </div>
  );
}

// Reading order: what this project is, how it is laid out, how it is shaped,
// what a change did to it, what is wrong with it, how the run itself went.
const TABS = [
  { path: "overview", label: "overview" },
  { path: "map", label: "map" },
  { path: "architecture", label: "architecture" },
  { path: "adr", label: "decisions" },
  { path: "protocol", label: "protocol" },
  { path: "change", label: "change" },
  { path: "findings", label: "findings" },
  { path: "review", label: "review" },
  { path: "detail", label: "run detail" },
];

function RunLayout() {
  const { runId } = useParams();
  const [summary, setSummary] = useState<RunSummary | null>(null);

  useEffect(() => {
    if (!runId) return;
    setSummary(null);
    api
      .runDetail(runId)
      .then(setSummary)
      .catch(() => setSummary(null));
  }, [runId]);

  return (
    <>
      <header
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: "10px 16px 0",
        }}
      >
        <h1 style={{ fontSize: 14, margin: 0, fontWeight: 600 }}>
          {summary?.repositoryId ?? runId}
        </h1>
        {summary && (
          <>
            <Badge tone={STATUS_TONE[summary.status] ?? "plain"}>
              <span data-testid="run-status">{summary.status}</span>
            </Badge>
            <span className="note mono-num">
              {summary.baseSha ? `${shortSha(summary.baseSha)} → ` : ""}
              {shortSha(summary.headSha)}
            </span>
          </>
        )}
      </header>
      <nav className="tabs" style={{ marginTop: 8 }}>
        {TABS.map((tab) => (
          <NavLink
            key={tab.path}
            to={tab.path}
            className={({ isActive }) => (isActive ? "active" : "")}
          >
            {tab.label}
          </NavLink>
        ))}
      </nav>
      <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: 16 }}>
        <Outlet />
      </div>
    </>
  );
}
