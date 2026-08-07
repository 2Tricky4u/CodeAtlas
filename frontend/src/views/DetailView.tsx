// The run itself: stages, receipts, the agent ledger, and the manifest — this
// is the page you open when you want to know whether to believe the other
// pages. The manifest used to render as a bare hash (the address of a report
// you could not open); the ledger and the run's own degradation notes were
// recorded and displayed nowhere.

import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, type AgentInvocation, type RunDetail, type RunManifest } from "../api";
import { Badge, ErrorBox, Loading, Panel, shortSha } from "../ui";

export function DetailView() {
  const { runId } = useParams();
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [manifest, setManifest] = useState<RunManifest | null>(null);
  const [invocations, setInvocations] = useState<AgentInvocation[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!runId) return;
    setDetail(null);
    setManifest(null);
    setInvocations([]);
    setError(null);
    api
      .runDetail(runId)
      .then(setDetail)
      .catch((e: Error) => setError(e.message));
    api
      .runManifest(runId)
      .then(setManifest)
      .catch((e: Error) => setError(e.message));
    api
      .invocations(runId)
      .then(setInvocations)
      .catch((e: Error) => setError(e.message));
  }, [runId]);

  if (error) return <ErrorBox error={error} />;
  if (!detail) return <Loading />;

  const stages = detail.events.filter((event) => event.event !== "started");

  return (
    <div style={{ display: "grid", gap: 12 }} data-testid="detail-view">
      <Panel title="identity">
        <table className="data">
          <tbody>
            <Row label="run id" value={detail.id} />
            <Row label="repository" value={detail.repositoryId} />
            <Row label="kind" value={detail.kind} />
            <Row label="head" value={detail.headSha ?? "—"} />
            {detail.baseSha && <Row label="base" value={detail.baseSha} />}
            <Row label="manifest" value={detail.manifestSha256 ?? "—"} />
            {detail.graph && (
              <Row
                label="head graph"
                value={`${detail.graph.nodeCount} nodes / ${detail.graph.edgeCount} edges · ${shortSha(detail.graph.canonicalSha256, 19)}`}
              />
            )}
            {detail.baseGraph && (
              <Row
                label="base graph"
                value={`${detail.baseGraph.nodeCount} nodes / ${detail.baseGraph.edgeCount} edges · ${shortSha(detail.baseGraph.canonicalSha256, 19)}`}
              />
            )}
          </tbody>
        </table>
      </Panel>

      {manifest && <ManifestPanel manifest={manifest} />}

      <Panel title="stages" count={stages.length}>
        <table className="data">
          <tbody>
            {stages.map((event, index) => (
              <tr key={index}>
                <td style={{ width: 160 }}>{event.stage}</td>
                <td style={{ width: 120 }}>
                  <Badge
                    tone={
                      event.level === "error" ? "bad" : event.level === "warning" ? "warn" : "ok"
                    }
                  >
                    {event.event}
                  </Badge>
                </td>
                <td className="note mono-num" style={{ width: 160 }}>
                  {event.at.slice(11, 19)}
                </td>
                <td className="note">{event.data ? JSON.stringify(event.data) : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      {invocations.length > 0 && (
        <Panel title="agent invocations" count={invocations.length}>
          <p className="note" style={{ marginTop: 0 }}>
            the ledger behind every agent-produced claim: who answered, with which model,
            at what cost — a cassette key means the answer was replayed, not generated
          </p>
          <table className="data" data-testid="invocations">
            <thead>
              <tr>
                <th>skill</th>
                <th>engine</th>
                <th>model</th>
                <th>status</th>
                <th>tokens</th>
                <th>cost</th>
                <th>wall</th>
              </tr>
            </thead>
            <tbody>
              {invocations.map((invocation, index) => (
                <tr key={index}>
                  <td>
                    {invocation.skillId}@{invocation.skillVersion}
                  </td>
                  <td className="note" title={invocation.cassetteKey ?? undefined}>
                    {invocation.engine}
                  </td>
                  <td className="note">{invocation.modelId ?? "—"}</td>
                  <td>
                    <Badge tone={invocation.status === "succeeded" ? "ok" : "bad"}>
                      {invocation.status}
                    </Badge>
                  </td>
                  <td className="note mono-num">
                    {invocation.promptTokens + invocation.completionTokens}
                  </td>
                  <td className="note mono-num">
                    {invocation.costUsd != null ? `$${invocation.costUsd.toFixed(4)}` : "—"}
                  </td>
                  <td className="note mono-num">{invocation.durationMs}ms</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      )}

      <Panel title="tool receipts" count={detail.receipts.length}>
        <p className="note" style={{ marginTop: 0 }}>
          one per deterministic tool invocation — extractors and the verification battery
          alike; this is what makes a fact a fact
        </p>
        <table className="data">
          <thead>
            <tr>
              <th>tool</th>
              <th>version</th>
              <th>exit</th>
              <th>configuration</th>
            </tr>
          </thead>
          <tbody>
            {detail.receipts.map((receipt, index) => (
              <tr key={index}>
                <td>{String(receipt.extractor ?? "")}</td>
                <td className="note">{String(receipt.extractorVersion ?? "")}</td>
                <td>
                  <Badge tone={Number(receipt.exitCode) === 0 ? "ok" : "warn"}>
                    {String(receipt.exitCode)}
                  </Badge>
                </td>
                <td className="note">
                  {JSON.stringify(receipt.configuration ?? {}).slice(0, 160)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}

function ManifestPanel({ manifest }: { manifest: RunManifest }) {
  const [opened, setOpened] = useState<{ role: string; body: unknown } | null>(null);

  const open = (role: string, sha: string) => {
    if (opened?.role === role) {
      setOpened(null);
      return;
    }
    api
      .artifactByRef(sha)
      .then((body) => setOpened({ role, body }))
      .catch((e: Error) => setOpened({ role, body: `could not load: ${e.message}` }));
  };

  return (
    <Panel title="manifest — the reproducibility contract">
      <div data-testid="manifest">
        {(manifest.notes?.length ?? 0) > 0 && (
          <div className="caveat" style={{ marginBottom: 8 }} data-testid="manifest-notes">
            {manifest.notes!.map((note, index) => (
              <div key={index}>{note}</div>
            ))}
          </div>
        )}
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 8 }}>
          {Object.entries(manifest.toolchain).map(([tool, version]) => (
            <Badge key={tool}>
              {tool} {version}
            </Badge>
          ))}
          {manifest.modelIds.map((model) => (
            <Badge key={model} tone="info">
              model {model}
            </Badge>
          ))}
          {manifest.cassetteIds.length > 0 && (
            <Badge tone="info">{manifest.cassetteIds.length} cassette(s)</Badge>
          )}
          <Badge>
            {manifest.cost.totalPromptTokens + manifest.cost.totalCompletionTokens} tokens
          </Badge>
        </div>
        <p className="note" style={{ margin: "0 0 4px" }}>
          every output this run owns, by role — click a row to open the artifact itself
        </p>
        <table className="data" data-testid="manifest-outputs">
          <tbody>
            {Object.entries(manifest.outputs).map(([role, sha]) => (
              <tr key={role} className="clickable" onClick={() => open(role, sha)}>
                <td style={{ width: 220 }}>{role}</td>
                <td className="note mono-num" title={sha}>
                  {shortSha(sha.replace("sha256:", ""), 19)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {opened && (
          <div style={{ marginTop: 8 }} data-testid="opened-artifact">
            <div className="microlabel">{opened.role}</div>
            <pre className="codeblock" style={{ maxHeight: 280, overflow: "auto" }}>
              {typeof opened.body === "string"
                ? opened.body
                : JSON.stringify(opened.body, null, 2).slice(0, 20000)}
            </pre>
          </div>
        )}
        {manifest.sourceLock.changedPaths.length > 0 && (
          <p className="note" data-testid="changed-paths">
            changed at head: {manifest.sourceLock.changedPaths.join(", ")}
          </p>
        )}
        {manifest.sourceLock.generatedPaths.length > 0 && (
          <p className="note" data-testid="generated-paths">
            excluded as generated: {manifest.sourceLock.generatedPaths.join(", ")} — why these
            files carry no findings
          </p>
        )}
      </div>
    </Panel>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <tr>
      <td style={{ width: 130 }} className="microlabel">
        {label}
      </td>
      <td className="mono-num">{value}</td>
    </tr>
  );
}
