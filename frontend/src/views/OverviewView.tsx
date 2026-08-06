// What this project is: the deterministic overview, rendered.
// Everything on this page is computed from the graph — no model wrote any of it.

import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, type ProjectOverview } from "../api";
import { Badge, Empty, ErrorBox, Loading, Panel } from "../ui";
import { ModuleLink } from "./links";
import { NarrativePanel } from "./NarrativePanel";
import { SourcePanel, type SourceRequest } from "./SourcePanel";

export function OverviewView() {
  const { runId } = useParams();
  const [overview, setOverview] = useState<ProjectOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [source, setSource] = useState<SourceRequest | null>(null);

  useEffect(() => {
    if (!runId) return;
    setOverview(null);
    setError(null);
    api
      .overview(runId)
      .then(setOverview)
      .catch((e: Error) => setError(e.message));
  }, [runId]);

  if (error) return <ErrorBox error={error} />;
  if (!overview) return <Loading />;

  const open = (path: string, startLine?: number) =>
    setSource({ revision: overview.revision, path, startLine });

  return (
    <div data-testid="overview-view">
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
          gap: 12,
          marginBottom: 12,
        }}
      >
        <Stat label="packages" value={overview.counts.packages} />
        <Stat label="modules" value={overview.counts.files} />
        <Stat label="symbols" value={overview.counts.symbols} />
        <Stat label="edges" value={overview.counts.edges} />
        <Stat label="levels" value={overview.levels.length} />
        <Stat
          label="cycles"
          value={overview.cycles.length}
          tone={overview.cycles.length ? "warn" : "ok"}
        />
      </div>

      {/* Measured facts first, narration after: the reader should meet the
          numbers before the prose that interprets them. */}
      <div style={{ marginBottom: 12 }}>
        <NarrativePanel runId={runId!} onOpenSource={open} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <Panel title="start here" count={overview.startHere.length}>
          {overview.startHere.length === 0 && <Empty>nothing to suggest</Empty>}
          <ol style={{ margin: 0, paddingLeft: "1.4em" }} data-testid="start-here">
            {overview.startHere.map((entry) => (
              <li key={entry.path} style={{ marginBottom: 6 }}>
                <ModuleLink
                  path={entry.path}
                  className=""
                  style={{ color: "var(--accent)" }}
                  title="explain this module"
                >
                  {entry.path}
                </ModuleLink>
                <div className="note">{entry.reason}</div>
              </li>
            ))}
          </ol>
        </Panel>

        <Panel title="most depended on" count={overview.hubs.dependedOn.length}>
          <table className="data">
            <thead>
              <tr>
                <th>module</th>
                <th>fan-in</th>
                <th>level</th>
              </tr>
            </thead>
            <tbody>
              {overview.hubs.dependedOn.map((module) => (
                <tr key={module.path}>
                  <td>
                    <ModuleLink path={module.path} className="" style={{ color: "var(--fg-0)" }}>
                      {module.path}
                    </ModuleLink>
                  </td>
                  <td className="mono-num">{module.fanIn}</td>
                  <td className="mono-num">{module.level}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>

        <Panel title="cycles" count={overview.cycles.length}>
          {overview.cycles.length === 0 && (
            <p className="note">
              none — every dependency points downward, which is the best possible answer
            </p>
          )}
          {overview.cycles.map((cycle, index) => (
            <div key={index} style={{ marginBottom: 8 }}>
              <Badge tone="warn">{cycle.members.length} modules</Badge>
              <div className="note" style={{ marginTop: 3 }}>
                {cycle.members.map((member, i) => (
                  <span key={member}>
                    {i > 0 && " ⇄ "}
                    <ModuleLink path={member} className="" style={{ color: "var(--fg-1)" }}>
                      {member}
                    </ModuleLink>
                  </span>
                ))}
              </div>
            </div>
          ))}
        </Panel>

        <Panel title="orphans" count={overview.orphans.length}>
          {overview.orphans.length === 0 && <p className="note">every module is connected</p>}
          {overview.orphans.length > 0 && (
            <>
              <p className="note" style={{ marginTop: 0 }}>
                no dependency edges in either direction — build scripts and test roots are
                expected here; anything substantive is worth a look
              </p>
              <ul style={{ margin: 0, paddingLeft: "1.2em" }}>
                {overview.orphans.map((orphan) => (
                  <li key={orphan.path}>
                    <ModuleLink path={orphan.path} className="" style={{ color: "var(--fg-1)" }}>
                      {orphan.path}
                    </ModuleLink>
                  </li>
                ))}
              </ul>
            </>
          )}
        </Panel>
      </div>

      {overview.notes.length > 0 && (
        <div style={{ marginTop: 12 }}>
          {overview.notes.map((note, index) => (
            <p key={index} className="note">
              {note}
            </p>
          ))}
        </div>
      )}

      <SourcePanel request={source} onClose={() => setSource(null)} />
    </div>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | string;
  tone?: "ok" | "warn";
}) {
  return (
    <div className="panel stat" style={{ padding: "10px 14px" }}>
      <div className="microlabel">{label}</div>
      <div
        className="mono-num"
        style={{
          fontSize: 22,
          color: tone === "warn" ? "var(--warn)" : tone === "ok" ? "var(--ok)" : "var(--fg-0)",
        }}
      >
        {value}
      </div>
    </div>
  );
}
