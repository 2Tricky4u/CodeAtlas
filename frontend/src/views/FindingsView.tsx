// Findings, with the thing that makes them worth reading: whether they were
// validated, whether the change introduced them, and the source they point at.

import { Fragment, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, type AttackPath, type Finding, type RunSummary } from "../api";
import { Badge, Empty, ErrorBox, Loading, Panel, SEVERITY_TONE, type Tone } from "../ui";
import { ModuleLink } from "./links";
import { SourcePanel, type SourceRequest } from "./SourcePanel";

const STATUS_TONE: Record<string, Tone> = {
  validated: "ok",
  rejected: "plain",
  unresolved: "warn",
  duplicate: "plain",
  suppressed: "plain",
  candidate: "info",
};

export function FindingsView() {
  const { runId } = useParams();
  const [findings, setFindings] = useState<Finding[] | null>(null);
  const [run, setRun] = useState<RunSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [source, setSource] = useState<SourceRequest | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    if (!runId) return;
    setFindings(null);
    setError(null);
    api.runDetail(runId).then(setRun).catch(() => setRun(null));
    api
      .findings(runId)
      .then(setFindings)
      .catch((e: Error) => setError(e.message));
  }, [runId]);

  if (error) return <ErrorBox error={error} />;
  if (!findings) return <Loading />;
  if (findings.length === 0) {
    return (
      <Empty>
        <p>no findings recorded for this run</p>
        <p className="note">
          a run without the review stages produces evidence and no findings, which is a
          supported mode rather than a clean bill of health
        </p>
      </Empty>
    );
  }

  const publishable = findings.filter((finding) => finding.publicationEligible);

  return (
    <div data-testid="findings-view">
      <Panel
        title="findings"
        count={`${publishable.length} of ${findings.length} publication-eligible`}
      >
        <table className="data">
          <thead>
            <tr>
              <th>id</th>
              <th>severity</th>
              <th>status</th>
              <th>claim</th>
              <th>location</th>
              <th>scope</th>
            </tr>
          </thead>
          <tbody>
            {findings.map((finding) => (
              <Fragment key={finding.findingId}>
                <tr
                  className={finding.path ? "clickable" : ""}
                  onClick={() =>
                    run?.headSha &&
                    finding.path &&
                    setSource({
                      revision: run.headSha,
                      path: finding.path,
                      startLine: finding.startLine ?? undefined,
                      endLine: finding.endLine ?? undefined,
                    })
                  }
                >
                  <td className="mono-num">{finding.findingId}</td>
                  <td>
                    <Badge tone={SEVERITY_TONE[finding.severity] ?? "plain"}>
                      {finding.severity}
                    </Badge>
                  </td>
                  <td>
                    <Badge tone={STATUS_TONE[finding.status] ?? "plain"}>{finding.status}</Badge>
                    {finding.validation && (
                      <button
                        className="note"
                        style={{ cursor: "pointer", display: "block", padding: 0 }}
                        data-testid="validation-toggle"
                        onClick={(event) => {
                          event.stopPropagation();
                          setExpanded(
                            expanded === finding.findingId ? null : finding.findingId,
                          );
                        }}
                      >
                        {expanded === finding.findingId ? "hide the check" : "how checked?"}
                      </button>
                    )}
                  </td>
                  <td>
                    {finding.claim}
                    <div className="note">
                      {finding.category} · {finding.discoveredBySkill} ·{" "}
                      {Math.round(finding.confidence * 100)}% confidence
                    </div>
                  </td>
                  <td className="note" onClick={(event) => event.stopPropagation()}>
                    {/* Row click opens the pinned lines; this link explains the
                        whole module the finding lives in. */}
                    <ModuleLink path={finding.path} className="" style={{ color: "var(--fg-1)" }}>
                      {finding.path}
                    </ModuleLink>
                    {finding.startLine ? `:${finding.startLine}` : ""}
                  </td>
                  <td>
                    {finding.introducedByChange === true && <Badge tone="bad">introduced</Badge>}
                    {finding.introducedByChange === false && <Badge>pre-existing</Badge>}
                  </td>
                </tr>
                {expanded === finding.findingId && finding.validation && (
                  <tr>
                    <td colSpan={6}>
                      {/* The adversarial validator's own record for THIS
                          finding — the claim "findings survive a hostile
                          check" is only visible if the check itself is. */}
                      <div className="note" data-testid="validation-detail">
                        {typeof finding.validation.reason === "string" && (
                          <p style={{ margin: "2px 0" }}>{finding.validation.reason}</p>
                        )}
                        {Array.isArray(finding.validation.counterEvidenceChecked) && (
                          <p style={{ margin: "2px 0" }}>
                            counter-evidence checked:{" "}
                            {(finding.validation.counterEvidenceChecked as string[]).join(", ")}
                          </p>
                        )}
                        {typeof finding.validation.duplicateOf === "string" && (
                          <p style={{ margin: "2px 0" }}>
                            duplicate of {finding.validation.duplicateOf}
                          </p>
                        )}
                        {isAttackPath(finding.validation.attackPath) && (
                          <AttackPathBlock path={finding.validation.attackPath} />
                        )}
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </Panel>
      <SourcePanel request={source} onClose={() => setSource(null)} />
    </div>
  );
}

// The validation bag is an untyped JSONB column, so the attack path arrives as
// `unknown`; narrow it before rendering rather than trusting its shape.
function isAttackPath(value: unknown): value is AttackPath {
  if (typeof value !== "object" || value === null) return false;
  const path = value as Record<string, unknown>;
  return (
    typeof path.dataflow === "object" &&
    path.dataflow !== null &&
    typeof path.reachability === "object" &&
    path.reachability !== null
  );
}

function AttackPathBlock({ path }: { path: AttackPath }) {
  return (
    <div
      data-testid="attack-path"
      style={{ marginTop: 6, borderTop: "1px solid var(--border)", paddingTop: 6 }}
    >
      <div className="microlabel">attack path</div>
      <p style={{ margin: "2px 0" }}>
        <strong>{path.dataflow.source}</strong> → {path.dataflow.sink} → {path.dataflow.outcome}
      </p>
      <p style={{ margin: "2px 0" }}>
        reachable by {path.reachability.attacker} via {path.reachability.entrypoint}
        {(path.reachability.preconditions?.length ?? 0) > 0 &&
          ` (needs: ${path.reachability.preconditions!.join("; ")})`}
      </p>
      <p style={{ margin: "2px 0" }}>
        <Badge tone={SEVERITY_TONE[path.impact.level] ?? "plain"}>
          impact {path.impact.level}
        </Badge>{" "}
        {path.impact.why} · <Badge tone="info">likelihood {path.likelihood.level}</Badge>{" "}
        {path.likelihood.why}
      </p>
      {(path.limitations?.length ?? 0) > 0 && (
        <p className="note" style={{ margin: "2px 0" }}>
          not established: {path.limitations!.join("; ")}
        </p>
      )}
    </div>
  );
}
