// Architecture decisions, in the order they were taken, each checked against
// the graph.
//
// Four outcomes and only four. `unverifiable` is the one that earns the page:
// when there is no evidence to check a decision against, saying so is the
// honest answer, and it must not be allowed to look like conformance. The audit
// proposes and never supersedes — a decision's lifecycle is a human act, so
// `requiresHumanDecision` is rendered as a call for one, not as a verdict.

import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, type AdrAudit, type AuditedDecision, type AuditResult } from "../api";
import { Badge, Empty, ErrorBox, Loading, Panel } from "../ui";
import { SourcePanel, type SourceRequest } from "./SourcePanel";

const TONE: Record<AuditResult, "ok" | "warn" | "bad" | "info"> = {
  conformant: "ok",
  "probable-drift": "bad",
  // Not a failure and not a pass. It is the absence of evidence, and it gets
  // its own colour so it cannot be mistaken for either.
  unverifiable: "warn",
  "intentionally-superseded": "info",
};

const EXPLANATION: Record<AuditResult, string> = {
  conformant: "the code still does what was decided",
  "probable-drift": "the code contradicts this decision",
  unverifiable: "no evidence in the graph could check this either way",
  "intentionally-superseded": "replaced by a later decision",
};

export function AdrView() {
  const { runId } = useParams();
  const [audit, setAudit] = useState<AdrAudit | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [source, setSource] = useState<SourceRequest | null>(null);

  useEffect(() => {
    if (!runId) return;
    setAudit(undefined);
    api
      .adrAudit(runId)
      .then(setAudit)
      .catch((e: Error) => setError(e.message));
  }, [runId]);

  if (error) return <ErrorBox error={error} />;
  if (audit === undefined) return <Loading />;
  if (audit === null) {
    return (
      <Empty>
        this run did not audit architecture decisions — the audit runs with the review
      </Empty>
    );
  }

  const open = (path: string) => setSource({ revision: audit.revision, path });
  const drifting = audit.decisions.filter((d) => d.auditResult === "probable-drift");

  return (
    <div data-testid="adr-view" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
        <Badge>{audit.decisions.length} decision(s)</Badge>
        {drifting.length > 0 && <Badge tone="bad">{drifting.length} drifting</Badge>}
      </div>

      {(audit.notes?.length ?? 0) > 0 && (
        <div className="caveat" data-testid="adr-notes">
          {audit.notes!.map((note, index) => (
            <div key={index}>{note}</div>
          ))}
        </div>
      )}

      {audit.decisions.length === 0 ? (
        <Empty>
          this project records no architecture decisions, so there was nothing to check the
          code against
        </Empty>
      ) : (
        <ol
          style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 10 }}
          data-testid="adr-timeline"
        >
          {audit.decisions.map((decision) => (
            <DecisionCard key={decision.adr} decision={decision} onOpen={open} />
          ))}
        </ol>
      )}

      <SourcePanel request={source} onClose={() => setSource(null)} />
    </div>
  );
}

function DecisionCard({
  decision,
  onOpen,
}: {
  decision: AuditedDecision;
  onOpen: (path: string) => void;
}) {
  return (
    <li>
      <Panel
        title={decision.label}
        actions={
          <span style={{ display: "flex", gap: 6, alignItems: "center" }}>
            {decision.date && <span className="note">{decision.date}</span>}
            <Badge tone={TONE[decision.auditResult]}>{decision.auditResult}</Badge>
          </span>
        }
      >
        <div style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
          <button
            onClick={() => onOpen(decision.adr)}
            style={{ color: "var(--accent)" }}
            title={decision.adr}
          >
            {decision.title ?? decision.adr}
          </button>
          <span className="badge">{decision.status}</span>
          {decision.supersededBy && (
            <span className="badge" data-testid="superseded-by">
              superseded by {decision.supersededBy}
            </span>
          )}
        </div>

        <p style={{ margin: "8px 0 4px" }}>{decision.assertion}</p>
        <p className="note" style={{ marginTop: 0 }}>
          {EXPLANATION[decision.auditResult]} · confidence{" "}
          {decision.confidence.toFixed(2)}
        </p>

        {decision.detail && <p style={{ marginBottom: 4 }}>{decision.detail}</p>}

        {(decision.affectedNodes?.length ?? 0) > 0 && (
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginTop: 6 }}>
            {decision.affectedNodes!.map((node) => (
              <span key={node} className="badge" title={node} data-testid="affected-node">
                {node.split("/").pop()}
              </span>
            ))}
          </div>
        )}

        {decision.requiresHumanDecision && (
          <div className="caveat" data-testid="needs-human" style={{ marginTop: 8 }}>
            this needs a person: either the code should change or the decision should be
            superseded, and the audit is not allowed to choose
          </div>
        )}
      </Panel>
    </li>
  );
}
