// What an attacker could do here — boundaries, assets, abuse paths — and what
// they provably cannot. This is a model of the system, not of any one change,
// so it is cached per repository and reused across runs; when the run's own
// revision is not the one it was modeled at, the page says so.
//
// The refusal is a first-class state: a repository with no meaningful attack
// surface returns no threats and says why. The non-capabilities matter as much
// as the capabilities — they are what keep severity honest — so they get equal
// space, side by side.

import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import {
  api,
  type ThreatEvidence,
  type ThreatModel,
} from "../api";
import { Badge, Empty, ErrorBox, Loading, Panel, SEVERITY_TONE, shortSha } from "../ui";
import { ModuleLink } from "./links";
import { SourcePanel, type SourceRequest } from "./SourcePanel";

export function ThreatsView() {
  const { runId } = useParams();
  const [model, setModel] = useState<ThreatModel | null | undefined>(undefined);
  const [revision, setRevision] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [source, setSource] = useState<SourceRequest | null>(null);

  useEffect(() => {
    if (!runId) return;
    setModel(undefined);
    setError(null);
    setRevision(null);
    api
      .threatModel(runId)
      .then(setModel)
      .catch((e: Error) => setError(e.message));
    api
      .runDetail(runId)
      .then((detail) => setRevision(detail.headSha))
      .catch(() => setRevision(null));
  }, [runId]);

  if (error) return <ErrorBox error={error} />;
  if (model === undefined) return <Loading />;
  if (model === null) {
    return <Empty>this run carried no threat model — it runs with the review half</Empty>;
  }

  const open = (evidence: ThreatEvidence) =>
    revision && setSource({ revision, path: evidence.path, startLine: evidence.startLine });

  // The model may have been built at an earlier revision and reused here.
  const reused = revision !== null && model.modeledAtRevision !== revision;
  const noThreats = (model.threats?.length ?? 0) === 0;

  return (
    <div data-testid="threats-view" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
        <Badge>{model.threats?.length ?? 0} threat(s)</Badge>
        <Badge>{model.boundaries?.length ?? 0} boundary(ies)</Badge>
        <Badge>{model.assets?.length ?? 0} asset(s)</Badge>
        <Badge>{model.focusPaths?.length ?? 0} focus path(s)</Badge>
      </div>

      {reused && (
        <div className="caveat" data-testid="threat-reused">
          reused from an earlier run — modeled at{" "}
          <span className="mono-num">{shortSha(model.modeledAtRevision)}</span>, not this run's
          revision. A threat model describes what the system is, which changes more slowly than
          its code; rebuild it with <code>--refresh-threat-model</code>.
        </div>
      )}

      <p style={{ margin: 0 }}>{model.summary}</p>

      {noThreats ? (
        <div className="caveat" data-testid="no-threats">
          no meaningful attack surface was found for this repository
        </div>
      ) : (
        <>
          {(model.boundaries?.length ?? 0) > 0 && (
            <Panel title="trust boundaries" count={model.boundaries!.length}>
              <table className="data" data-testid="threat-boundaries">
                <thead>
                  <tr>
                    <th>boundary</th>
                    <th>between</th>
                    <th>channel</th>
                    <th>guarantees</th>
                    <th>validation</th>
                    <th>read at</th>
                  </tr>
                </thead>
                <tbody>
                  {model.boundaries!.map((boundary) => (
                    <tr key={boundary.name}>
                      <td>{boundary.name}</td>
                      <td className="note">{boundary.between.join(" ↔ ")}</td>
                      <td className="note">{boundary.dataCrossing.channel}</td>
                      <td>{boundary.dataCrossing.guarantees}</td>
                      <td>{boundary.dataCrossing.validation}</td>
                      <td>
                        {boundary.evidence.map((evidence, index) => (
                          <EvidenceChip key={index} evidence={evidence} onOpen={open} />
                        ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
          )}

          {(model.assets?.length ?? 0) > 0 && (
            <Panel title="assets" count={model.assets!.length}>
              <ul style={{ margin: 0, paddingLeft: "1.2em" }} data-testid="threat-assets">
                {model.assets!.map((asset) => (
                  <li key={asset.name} style={{ marginBottom: 6 }}>
                    <strong>{asset.name}</strong> — {asset.whyItMatters}{" "}
                    {asset.cia.map((property) => (
                      <Badge key={property} tone="info">
                        {property.charAt(0).toUpperCase()}
                      </Badge>
                    ))}
                  </li>
                ))}
              </ul>
            </Panel>
          )}

          {model.attacker && (
            <Panel title="the attacker">
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr",
                  gap: 16,
                }}
                data-testid="threat-attacker"
              >
                <div>
                  <div className="microlabel">can</div>
                  <ul style={{ margin: "4px 0 0", paddingLeft: "1.2em" }}>
                    {model.attacker.capabilities.map((capability, index) => (
                      <li key={index}>{capability}</li>
                    ))}
                  </ul>
                </div>
                <div>
                  <div className="microlabel">cannot — what keeps severity honest</div>
                  <ul
                    style={{ margin: "4px 0 0", paddingLeft: "1.2em" }}
                    data-testid="threat-non-capabilities"
                  >
                    {model.attacker.nonCapabilities.map((limit, index) => (
                      <li key={index}>{limit}</li>
                    ))}
                  </ul>
                </div>
              </div>
            </Panel>
          )}

          <Panel title="abuse paths" count={model.threats!.length}>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }} data-testid="threats">
              {model.threats!.map((threat) => (
                <div
                  key={threat.id}
                  className="panel-body"
                  style={{ border: "1px solid var(--border)", borderRadius: 6, padding: 10 }}
                  data-testid="threat-card"
                >
                  <div style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
                    <span className="mono-num">{threat.id}</span>
                    <strong>{threat.title}</strong>
                    <Badge tone={SEVERITY_TONE[threat.severity] ?? "plain"}>
                      {threat.severity}
                    </Badge>
                    <Badge tone="info">likelihood {threat.likelihood}</Badge>
                  </div>
                  <p style={{ margin: "6px 0 0" }}>
                    <span className="note">{threat.source}</span> → {threat.action} →{" "}
                    {threat.impact}
                  </p>
                  {(threat.prerequisites?.length ?? 0) > 0 && (
                    <p className="note" style={{ margin: "4px 0 0" }}>
                      needs: {threat.prerequisites!.join("; ")}
                    </p>
                  )}
                  {(threat.existingControls?.length ?? 0) > 0 && (
                    <div style={{ marginTop: 6 }}>
                      <div className="microlabel">existing controls</div>
                      <ul style={{ margin: "2px 0 0", paddingLeft: "1.2em" }}>
                        {threat.existingControls!.map((control, index) => (
                          <li key={index}>
                            {control.description}{" "}
                            {control.verified ? (
                              <Badge tone="ok">verified</Badge>
                            ) : (
                              <Badge tone="warn">unverified</Badge>
                            )}{" "}
                            {control.evidence && (
                              <EvidenceChip evidence={control.evidence} onOpen={open} />
                            )}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {(threat.gaps?.length ?? 0) > 0 && (
                    <p className="note" style={{ margin: "4px 0 0", color: "var(--warn)" }}>
                      gaps: {threat.gaps!.join("; ")}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </Panel>

          {model.criticality && (
            <Panel title="what severity means here">
              <dl
                style={{ margin: 0, display: "grid", gridTemplateColumns: "auto 1fr", gap: "4px 12px" }}
                data-testid="threat-criticality"
              >
                {(["critical", "high", "medium", "low"] as const).map((level) => (
                  <div key={level} style={{ display: "contents" }}>
                    <dt>
                      <Badge tone={SEVERITY_TONE[level] ?? "plain"}>{level}</Badge>
                    </dt>
                    <dd style={{ margin: 0 }}>{model.criticality![level]}</dd>
                  </div>
                ))}
              </dl>
            </Panel>
          )}

          {(model.focusPaths?.length ?? 0) > 0 && (
            <Panel title="where the reviewers were aimed" count={model.focusPaths!.length}>
              <ul style={{ margin: 0, paddingLeft: "1.2em" }} data-testid="threat-focus-paths">
                {model.focusPaths!.map((focus) => (
                  <li key={focus.path} style={{ marginBottom: 6 }}>
                    <ModuleLink path={focus.path}>{focus.path}</ModuleLink> — {focus.reason}
                    {(focus.threatIds?.length ?? 0) > 0 && (
                      <span className="note"> ({focus.threatIds!.join(", ")})</span>
                    )}
                  </li>
                ))}
              </ul>
            </Panel>
          )}
        </>
      )}

      {(model.notes?.length ?? 0) > 0 && (
        <Panel title="notes" count={model.notes!.length}>
          <ul style={{ margin: 0, paddingLeft: "1.2em" }} data-testid="threat-notes">
            {model.notes!.map((note, index) => (
              <li key={index} style={{ marginBottom: 4 }}>
                {note}
              </li>
            ))}
          </ul>
        </Panel>
      )}

      {(model.droppedElements?.length ?? 0) > 0 && (
        <div className="caveat" data-testid="threat-dropped">
          {model.droppedElements!.length} element(s) were removed because their evidence did not
          resolve against this revision
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
  evidence: ThreatEvidence;
  onOpen: (evidence: ThreatEvidence) => void;
}) {
  const where = evidence.startLine ? `:${evidence.startLine}` : "";
  return (
    <button
      onClick={() => onOpen(evidence)}
      className="badge accent"
      style={{ cursor: "pointer" }}
      title={evidence.path}
      data-testid="threat-evidence"
    >
      {evidence.path.split("/").pop()}
      {where}
    </button>
  );
}
