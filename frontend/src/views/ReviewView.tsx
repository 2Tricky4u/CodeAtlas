// How the review went, as opposed to what it found.
//
// Four things were computed on every reviewed run and displayed nowhere: what
// the reviewers were checking against, what they proposed before validation,
// the report that was rendered, and the payload the approval gate governs.
//
// The middle one is the point. This project's claim is that findings survive an
// adversarial check — but a table of survivors looks identical whether the
// check rejected eleven candidates or none. Showing what did not survive, and
// why, is the only way that claim is visible rather than asserted.

import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import {
  api,
  type Approval,
  type CandidateFindings,
  type Finding,
  type IntentPackage,
  type Publication,
  type ReviewPayload,
} from "../api";
import { Badge, Empty, ErrorBox, Loading, Panel, SEVERITY_TONE, shortSha } from "../ui";

export function ReviewView() {
  const { runId } = useParams();
  const [intent, setIntent] = useState<IntentPackage | null>(null);
  const [candidates, setCandidates] = useState<CandidateFindings | null>(null);
  const [validated, setValidated] = useState<Finding[] | null>(null);
  const [markdown, setMarkdown] = useState<string | null>(null);
  const [payload, setPayload] = useState<ReviewPayload | null>(null);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [publications, setPublications] = useState<Publication[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!runId) return;
    setLoaded(false);
    setError(null);
    // No inner catches: each helper already maps a 404 to null (absence is a
    // state), so anything that rejects here is a real failure and must land
    // in the error box, not render as "this run was not reviewed".
    Promise.all([
      api.intent(runId),
      api.candidateFindings(runId),
      api.findings(runId),
      api.reviewMarkdown(runId),
      api.reviewPayload(runId),
      api.approvals(runId),
      api.publications(runId),
    ])
      .then(([i, c, f, m, p, a, pubs]) => {
        setIntent(i);
        setCandidates(c);
        setValidated(f);
        setMarkdown(m);
        setPayload(p);
        setApprovals(a);
        setPublications(pubs);
        setLoaded(true);
      })
      .catch((e: Error) => setError(e.message));
  }, [runId]);

  if (error) return <ErrorBox error={error} />;
  if (!loaded) return <Loading />;

  const reviewed = intent !== null || candidates !== null;
  if (!reviewed) {
    return (
      <Empty>
        this run was not reviewed — the deterministic analysis stands on its own, and the
        map, architecture and decisions tabs are unaffected
      </Empty>
    );
  }

  return (
    <div data-testid="review-view" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <ApprovalPanel approvals={approvals} payload={payload} publications={publications} />
      {candidates && <FunnelPanel candidates={candidates} findings={validated ?? []} />}

      {intent && <IntentPanel intent={intent} />}

      {markdown && (
        <Panel title="the report as written">
          <p className="note" style={{ marginTop: 0 }}>
            what a reviewer would read · this is the text the payload above carries
          </p>
          <pre className="codeblock" data-testid="review-markdown" style={{ maxHeight: 420, overflow: "auto" }}>
            {markdown}
          </pre>
        </Panel>
      )}
    </div>
  );
}

// Why a candidate did not become a published finding. Each is a different
// answer and none of them is "the reviewer was wrong" — conflating them would
// make the validator look either infallible or useless.
const WHY: Record<string, string> = {
  validated: "reproduced from the evidence in a fresh context",
  rejected: "could not be reproduced and was refused",
  duplicate: "the same defect as another candidate",
  unresolved: "the validator could neither confirm nor refute it, which is not a pass",
  candidate: "never reached validation",
};

const STATUS_TONE: Record<string, "ok" | "warn" | "bad" | "info" | "plain"> = {
  validated: "ok",
  rejected: "bad",
  duplicate: "info",
  unresolved: "warn",
};

function FunnelPanel({
  candidates,
  findings,
}: {
  candidates: CandidateFindings;
  findings: Finding[];
}) {
  // Every candidate is persisted with the verdict it received, so the funnel
  // reads off the findings rows rather than off set subtraction — which is
  // what made an earlier version report "0 rejected of 12" on a run where
  // nothing was validated at all.
  const byId = new Map(findings.map((f) => [f.findingId, f]));
  const proposed = candidates.findings.length;
  const publishable = findings.filter((f) => f.publicationEligible).length;

  const counts = new Map<string, number>();
  for (const candidate of candidates.findings) {
    const status = byId.get(candidate.findingId)?.status ?? "candidate";
    counts.set(status, (counts.get(status) ?? 0) + 1);
  }
  const unpublished = candidates.findings
    .map((c) => ({ candidate: c, status: byId.get(c.findingId)?.status ?? "candidate" }))
    .filter((entry) => entry.status !== "validated");

  return (
    <Panel title="what survived validation" count={`${publishable} of ${proposed}`}>
      <p className="note" style={{ marginTop: 0 }}>
        each candidate was re-examined in a fresh context by a validator that had not seen it
        proposed · a finding reaches the findings tab only if it was reproduced there, and is
        publishable only if something deterministic backs it
      </p>

      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10 }} data-testid="funnel">
        <Badge>{proposed} proposed</Badge>
        {[...counts.entries()]
          .sort()
          .map(([status, count]) => (
            <Badge key={status} tone={STATUS_TONE[status] ?? "plain"} >
              {count} {status}
            </Badge>
          ))}
        <Badge tone={publishable ? "ok" : "plain"}>{publishable} publishable</Badge>
      </div>

      {unpublished.length === 0 ? (
        <Empty>every candidate was validated</Empty>
      ) : (
        <table className="data" data-testid="not-validated">
          <thead>
            <tr>
              <th>finding</th>
              <th>proposed by</th>
              <th>severity</th>
              <th>verdict</th>
              <th>claim</th>
            </tr>
          </thead>
          <tbody>
            {unpublished.map(({ candidate, status }) => (
              <tr key={candidate.findingId}>
                <td className="note">{candidate.findingId}</td>
                <td className="note">
                  {candidate.discoveredBySkill?.replace("reviewer-", "") ?? "—"}
                </td>
                <td>
                  <Badge tone={SEVERITY_TONE[candidate.severity] ?? "plain"}>
                    {candidate.severity}
                  </Badge>
                </td>
                <td title={WHY[status]}>
                  <Badge tone={STATUS_TONE[status] ?? "plain"}>{status}</Badge>
                </td>
                <td>{candidate.claim}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <ul className="note" style={{ margin: "8px 0 0", paddingLeft: "1.2em" }} data-testid="verdict-key">
        {[...counts.keys()].sort().map((status) => (
          <li key={status}>
            <strong>{status}</strong> — {WHY[status] ?? "unknown verdict"}
          </li>
        ))}
      </ul>
    </Panel>
  );
}

function ApprovalPanel({
  approvals,
  payload,
  publications,
}: {
  approvals: Approval[];
  payload: ReviewPayload | null;
  publications: Publication[];
}) {
  if (!payload && approvals.length === 0) {
    return (
      <div className="caveat" data-testid="no-publication">
        nothing was prepared for publication — this run has no pull request to comment on
      </div>
    );
  }

  const pending = approvals.filter((a) => a.decision === null);
  const published = publications.filter((p) => p.status === "published");
  const failed = publications.filter((p) => p.status === "failed");
  return (
    <Panel
      title={published.length > 0 ? "what was posted" : "what would be posted"}
      actions={
        published.length > 0 ? (
          <Badge tone="ok">published</Badge>
        ) : pending.length > 0 ? (
          <Badge tone="warn">awaiting a human decision</Badge>
        ) : approvals.some((a) => a.decision === "approved") ? (
          <Badge tone="ok">approved</Badge>
        ) : approvals.length > 0 ? (
          <Badge tone="bad">rejected</Badge>
        ) : (
          <Badge>not requested</Badge>
        )
      }
    >
      {published.length > 0 ? (
        // Read from the publication ledger, never asserted: the shadow-mode
        // sentence below becomes false the moment `codeatlas publish` runs.
        <p className="note" style={{ marginTop: 0 }} data-testid="publication-status">
          published to GitHub:{" "}
          {published.map((publication) => (
            <a
              key={publication.id}
              href={publication.externalRef ?? undefined}
              target="_blank"
              rel="noreferrer"
            >
              {publication.externalRef}
            </a>
          ))}{" "}
          · {published[0]!.publishedAt?.slice(0, 19).replace("T", " ")}
        </p>
      ) : (
        <p className="note" style={{ marginTop: 0 }} data-testid="approval-note">
          shadow mode: this payload was built and nothing was sent · publishing is a separate,
          explicit act at the CLI, and the gate re-checks this row every time
        </p>
      )}
      {failed.length > 0 && (
        <div className="caveat" data-testid="publication-failed">
          {failed.length} publication attempt(s) failed and left their record — nothing
          reached GitHub from those attempts
        </div>
      )}

      {approvals.length > 0 && (
        <table className="data" data-testid="approvals">
          <thead>
            <tr>
              <th>action</th>
              <th>requested</th>
              <th>decision</th>
              <th>by</th>
              <th>payload</th>
            </tr>
          </thead>
          <tbody>
            {approvals.map((approval) => (
              <tr key={approval.id}>
                <td>{approval.actionKind}</td>
                <td className="note">{approval.requestedAt.slice(0, 19).replace("T", " ")}</td>
                <td>
                  {approval.decision === null ? (
                    <Badge tone="warn">undecided</Badge>
                  ) : (
                    <Badge tone={approval.decision === "approved" ? "ok" : "bad"}>
                      {approval.decision}
                    </Badge>
                  )}
                </td>
                <td className="note">
                  {approval.decidedBy ?? "—"}
                  {approval.decisionNote && (
                    <div data-testid="decision-note">“{approval.decisionNote}”</div>
                  )}
                </td>
                <td className="note" title={approval.payloadSha256}>
                  {shortSha(approval.payloadSha256.replace("sha256:", ""))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {payload && (
        <div style={{ marginTop: 10 }}>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 6 }}>
            <Badge>
              {payload.owner}/{payload.repo} #{payload.prNumber}
            </Badge>
            <Badge>{payload.comments.length} inline comment(s)</Badge>
            {/* Never REQUEST_CHANGES or APPROVE: a human decides that. */}
            <Badge tone="info">event {payload.event}</Badge>
          </div>
          <pre className="codeblock" data-testid="payload-body" style={{ maxHeight: 260, overflow: "auto" }}>
            {payload.body}
          </pre>
          {/* The inline comments ARE the payload — a count alone hides what
              would actually land on someone's diff. */}
          {payload.comments.map((comment, index) => (
            <div key={index} style={{ marginTop: 6 }} data-testid="payload-comment">
              <div className="microlabel">
                {comment.path}:{comment.line}
              </div>
              <pre className="codeblock" style={{ maxHeight: 160, overflow: "auto" }}>
                {comment.body}
              </pre>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}

function IntentPanel({ intent }: { intent: IntentPackage }) {
  return (
    <Panel title="what it was checked against" count={intent.requirements.length}>
      <p className="note" style={{ marginTop: 0 }}>
        reconstructed from this repository's own specs, ADRs and rules before any reviewer
        ran · a finding is a contradiction with one of these, not with a general opinion
      </p>
      <ul style={{ margin: 0, paddingLeft: "1.2em" }} data-testid="requirements">
        {intent.requirements.map((requirement) => (
          <li key={requirement.id} style={{ marginBottom: 6 }}>
            <span className="badge">{requirement.sourceKind}</span>{" "}
            <strong>{requirement.id}</strong> {requirement.text}
            {requirement.sourceRef && (
              <span className="note"> — {requirement.sourceRef}</span>
            )}
            {(requirement.acceptanceCriteria?.length ?? 0) > 0 && (
              <div className="note">
                accepted when: {requirement.acceptanceCriteria!.join("; ")}
              </div>
            )}
          </li>
        ))}
      </ul>
      {/* Non-goals and obligations shape what a reviewer must NOT flag —
          reconstructed on every reviewed run, rendered nowhere until now. */}
      {intent.nonGoals.length > 0 && (
        <p className="note" style={{ marginBottom: 0 }} data-testid="non-goals">
          explicitly not goals: {intent.nonGoals.join(" · ")}
        </p>
      )}
      {intent.compatibilityObligations.length > 0 && (
        <p className="note" style={{ marginBottom: 0 }} data-testid="compat-obligations">
          must stay compatible: {intent.compatibilityObligations.join(" · ")}
        </p>
      )}
      {intent.unresolvedQuestions.length > 0 && (
        <div className="caveat" style={{ marginTop: 8 }} data-testid="unresolved">
          {intent.unresolvedQuestions.length} question(s) the specs left open:{" "}
          {intent.unresolvedQuestions.join(" · ")}
        </div>
      )}
    </Panel>
  );
}
