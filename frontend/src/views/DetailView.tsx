// The run itself: stages, extractor receipts, and the manifest hash. This is
// the page you open when you want to know whether to believe the other pages.

import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, type RunDetail } from "../api";
import { Badge, ErrorBox, Loading, Panel, shortSha } from "../ui";

export function DetailView() {
  const { runId } = useParams();
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!runId) return;
    setDetail(null);
    api
      .runDetail(runId)
      .then(setDetail)
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
                <td className="note">
                  {event.data ? JSON.stringify(event.data) : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      <Panel title="extractor receipts" count={detail.receipts.length}>
        <p className="note" style={{ marginTop: 0 }}>
          one per deterministic tool invocation — this is what makes a fact a fact
        </p>
        <table className="data">
          <thead>
            <tr>
              <th>extractor</th>
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
