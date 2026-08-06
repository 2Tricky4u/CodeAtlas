// What this project speaks — or, usually, that it speaks nothing.
//
// The refusal is the primary state of this page, not an error state. Most
// projects have no protocol: a batch tool reads input and writes output, a
// library exposes functions. A sequence diagram forced onto one of those is the
// most convincing wrong artifact this tool could produce, so when the model
// says `null` the page says so plainly and shows why.
//
// When there is a protocol, the diagrams are rendered *from the model that was
// validated*, never drawn separately — so a box or an arrow on them exists only
// because some line of source put it there, and that line is one click away.

import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import {
  api,
  type ProtocolEvidence,
  type ProtocolModel,
  type ProtocolParticipant,
} from "../api";
import { Badge, Empty, ErrorBox, Loading, Panel } from "../ui";
import { Mermaid } from "./Mermaid";
import { SourcePanel, type SourceRequest } from "./SourcePanel";

export function ProtocolView() {
  const { runId } = useParams();
  const [model, setModel] = useState<ProtocolModel | null | undefined>(undefined);
  const [sequence, setSequence] = useState<string | null>(null);
  const [state, setState] = useState<string | null>(null);
  const [revision, setRevision] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [source, setSource] = useState<SourceRequest | null>(null);

  useEffect(() => {
    if (!runId) return;
    setModel(undefined);
    api
      .protocolModel(runId)
      .then(setModel)
      .catch((e: Error) => setError(e.message));
    api.protocolDiagram(runId, "sequence").then(setSequence).catch(() => setSequence(null));
    api.protocolDiagram(runId, "state").then(setState).catch(() => setState(null));
    api
      .runDetail(runId)
      .then((detail) => setRevision(detail.headSha))
      .catch(() => setRevision(null));
  }, [runId]);

  if (error) return <ErrorBox error={error} />;
  if (model === undefined) return <Loading />;
  if (model === null) {
    return (
      <Empty>
        this run did not model a protocol — modelling runs with the project narrative
      </Empty>
    );
  }

  const open = (evidence: ProtocolEvidence) =>
    revision &&
    setSource({ revision, path: evidence.path, startLine: evidence.startLine });

  const protocol = model.protocol;

  return (
    <div data-testid="protocol-view" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {!protocol ? (
        <>
          <div className="caveat" data-testid="no-protocol">
            this project has no protocol to model
          </div>
          {model.notes?.map((note, index) => (
            <p key={index} style={{ margin: 0 }}>
              {note}
            </p>
          ))}
          <p className="note">
            a protocol here means an exchange between parties over time — a wire format, an
            RPC surface, a session state machine. Functions calling each other is the
            dependency graph, and the map already shows it.
          </p>
        </>
      ) : (
        <>
          <div style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
            <strong style={{ fontSize: 13 }}>{protocol.id}</strong>
            <Badge>v{protocol.version}</Badge>
            <Badge>{protocol.participants.length} participant(s)</Badge>
            <Badge>{protocol.messages.length} message(s)</Badge>
            {protocol.states.length === 0 && <Badge tone="info">stateless</Badge>}
          </div>

          <Panel title="how it is carried">
            <dl style={{ margin: 0, display: "grid", gridTemplateColumns: "auto 1fr", gap: "4px 12px" }}>
              <dt className="note">transport</dt>
              <dd style={{ margin: 0 }}>{protocol.transport}</dd>
              <dt className="note">framing</dt>
              <dd style={{ margin: 0 }}>{protocol.framing}</dd>
            </dl>
            <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginTop: 8 }}>
              {protocol.evidence.map((evidence, index) => (
                <EvidenceChip key={index} evidence={evidence} onOpen={open} />
              ))}
            </div>
          </Panel>

          {sequence && (
            <Panel title="the exchange">
              <Mermaid
                source={sequence}
                caption="derived from the model above — every arrow exists because a line of source put it there"
              />
            </Panel>
          )}

          <Panel title="participants" count={protocol.participants.length}>
            <ul style={{ margin: 0, paddingLeft: "1.2em" }} data-testid="participants">
              {protocol.participants.map((party) => (
                <li key={party.name} style={{ marginBottom: 6 }}>
                  <strong>{party.name}</strong>
                  {party.description && <span> — {party.description}</span>}{" "}
                  <EvidenceChip evidence={party.evidence} onOpen={open} />
                </li>
              ))}
            </ul>
          </Panel>

          <Panel title="messages" count={protocol.messages.length}>
            <table className="data" data-testid="messages">
              <thead>
                <tr>
                  <th>message</th>
                  <th>from</th>
                  <th>to</th>
                  <th>read at</th>
                </tr>
              </thead>
              <tbody>
                {protocol.messages.map((message) => (
                  <tr key={message.name}>
                    <td>{message.name}</td>
                    <td className="note">{message.producer}</td>
                    <td className="note">{message.consumer}</td>
                    <td>
                      <EvidenceChip evidence={message.evidence} onOpen={open} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>

          {state && (
            <Panel title="states">
              <Mermaid source={state} caption="states and the timeouts that move between them" />
            </Panel>
          )}
        </>
      )}

      {protocol && (model.notes?.length ?? 0) > 0 && (
        <Panel title="what was deliberately not modelled" count={model.notes!.length}>
          <ul style={{ margin: 0, paddingLeft: "1.2em" }} data-testid="protocol-notes">
            {model.notes!.map((note, index) => (
              <li key={index} style={{ marginBottom: 4 }}>
                {note}
              </li>
            ))}
          </ul>
        </Panel>
      )}

      {(model.droppedElements?.length ?? 0) > 0 && (
        <div className="caveat" data-testid="protocol-dropped">
          {model.droppedElements!.length} element(s) were removed because their evidence did
          not resolve against this revision
          <ul style={{ margin: "6px 0 0", paddingLeft: "1.2em" }}>
            {model.droppedElements!.map((dropped, index) => (
              <li key={index}>
                {dropped.kind} <strong>{dropped.name}</strong>: {dropped.reason}
              </li>
            ))}
          </ul>
        </div>
      )}

      <SourcePanel request={source} onClose={() => setSource(null)} />
    </div>
  );
}

function EvidenceChip({
  evidence,
  onOpen,
}: {
  evidence: ProtocolEvidence;
  onOpen: (evidence: ProtocolEvidence) => void;
}) {
  const where = evidence.startLine ? `:${evidence.startLine}` : "";
  return (
    <button
      onClick={() => onOpen(evidence)}
      className="badge accent"
      style={{ cursor: "pointer" }}
      title={evidence.path}
      data-testid="protocol-evidence"
    >
      {evidence.path.split("/").pop()}
      {where}
    </button>
  );
}

export type { ProtocolParticipant };
