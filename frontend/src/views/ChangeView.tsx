// What this change did: narrative first, then the deterministic evidence it
// cites — public API delta, structural diff, bounded impact. Order matters: a
// reviewer needs to know what a change does before being told what to fear.

import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import {
  api,
  type ApiChange,
  type ChangeExplanation,
  type ChangeImpact,
  type Citation,
  type GraphDiff,
  type RunSummary,
} from "../api";
import { Badge, BUMP_TONE, Empty, KindDot, Loading, Panel, shortSha, type Tone } from "../ui";
import { Mermaid } from "./Mermaid";
import { SourcePanel, type SourceRequest } from "./SourcePanel";

const RANK_TONE: Record<string, Tone> = {
  "public-api": "bad",
  "crate-crossing": "warn",
  internal: "plain",
  "test-only": "info",
};

export function ChangeView() {
  const { runId } = useParams();
  const [run, setRun] = useState<RunSummary | null>(null);
  const [diff, setDiff] = useState<GraphDiff | null | undefined>(undefined);
  const [apiChange, setApiChange] = useState<ApiChange | null | undefined>(undefined);
  const [impact, setImpact] = useState<ChangeImpact | null | undefined>(undefined);
  const [explanation, setExplanation] = useState<ChangeExplanation | null | undefined>(undefined);
  const [source, setSource] = useState<SourceRequest | null>(null);

  useEffect(() => {
    if (!runId) return;
    setDiff(undefined);
    setApiChange(undefined);
    setImpact(undefined);
    setExplanation(undefined);
    api.runDetail(runId).then(setRun).catch(() => setRun(null));
    api.graphDiff(runId).then(setDiff).catch(() => setDiff(null));
    api.apiChange(runId).then(setApiChange).catch(() => setApiChange(null));
    api.impact(runId).then(setImpact).catch(() => setImpact(null));
    api.explanation(runId).then(setExplanation).catch(() => setExplanation(null));
  }, [runId]);

  if (diff === undefined) return <Loading />;

  if (diff === null) {
    return (
      <Empty>
        <p>this run analyzed a single revision — there is no change to explain</p>
        <p className="note">
          run <code>codeatlas review-pr owner/repo N</code> to analyze a pull request with
          base and head
        </p>
      </Empty>
    );
  }

  const openCitation = (citation: Citation) => {
    if (!run) return;
    if (citation.kind === "source") {
      const revision = citation.revision === "base" ? run.baseSha : run.headSha;
      if (revision) {
        setSource({
          revision,
          path: citation.path,
          startLine: citation.startLine,
          endLine: citation.endLine,
        });
      }
    }
  };

  return (
    <div data-testid="change-view" style={{ display: "grid", gap: 12 }}>
      {explanation && (
        <Panel title="what this change does">
          <p style={{ marginTop: 0, fontSize: 14 }}>{explanation.summary}</p>
          {explanation.sections.map((section) => (
            <div key={section.id} style={{ marginBottom: 10 }}>
              <div className="microlabel" style={{ marginBottom: 4 }}>
                {section.title}
              </div>
              <ul style={{ margin: 0, paddingLeft: "1.2em" }}>
                {section.claims.map((claim, index) => (
                  <li key={index} style={{ marginBottom: 4 }}>
                    {claim.text}{" "}
                    {claim.citations.map((citation, citationIndex) => (
                      <CitationChip
                        key={citationIndex}
                        citation={citation}
                        onOpen={() => openCitation(citation)}
                      />
                    ))}
                  </li>
                ))}
              </ul>
            </div>
          ))}
          {/* Present only when the change moved an interaction — the skill is
              told most changes should have `null` here. It has been produced
              and validated since P3 and never displayed until now. */}
          {explanation.sequenceDiagram && (
            <Mermaid
              source={explanation.sequenceDiagram}
              caption="how the components involved talk to each other after this change"
            />
          )}
          {(explanation.droppedClaims?.length ?? 0) > 0 && (
            <div className="caveat">
              {explanation.droppedClaims!.length} statement(s) were removed because their
              citations did not resolve against this run's evidence
            </div>
          )}
        </Panel>
      )}
      {explanation === null && (
        <p className="note">
          no narrative explanation was produced for this run (reviews disabled or the
          explainer did not complete) — the deterministic evidence below stands on its own
        </p>
      )}

      {apiChange && <ApiChangePanel change={apiChange} />}
      <StructuralPanel diff={diff} onOpen={(path, line) => {
        if (run?.headSha) setSource({ revision: run.headSha, path, startLine: line });
      }} />
      {impact && <ImpactPanel impact={impact} onOpen={(path, line) => {
        if (run?.headSha) setSource({ revision: run.headSha, path, startLine: line });
      }} />}

      <SourcePanel request={source} onClose={() => setSource(null)} />
    </div>
  );
}

function CitationChip({ citation, onOpen }: { citation: Citation; onOpen: () => void }) {
  if (citation.kind === "source") {
    const where = citation.startLine ? `:${citation.startLine}` : "";
    return (
      <button
        onClick={onOpen}
        className="badge accent"
        style={{ marginLeft: 4, cursor: "pointer" }}
        title={`${citation.revision} revision`}
      >
        {citation.revision === "base" ? "before " : ""}
        {citation.path.split("/").pop()}
        {where}
      </button>
    );
  }
  const label =
    citation.kind === "graph-edge" ? "edge" : citation.kind === "api-item" ? "API" : "impact";
  return (
    <span className="badge" style={{ marginLeft: 4 }} title={JSON.stringify(citation)}>
      {label}
    </span>
  );
}

function ApiChangePanel({ change }: { change: ApiChange }) {
  const interesting = change.packages.filter(
    (p) => p.added.length || p.removed.length || p.requiredBump !== "none",
  );
  const untouched = change.packages.length - interesting.length;
  return (
    <Panel title="public API" count={`${change.packages.length} packages measured`}>
      {interesting.length === 0 && (
        <p className="note" style={{ margin: 0 }}>
          no package's public API changed — measured, not assumed
        </p>
      )}
      {interesting.map((pkg) => (
        <div key={pkg.name} style={{ marginBottom: 10 }} data-testid={`api-${pkg.name}`}>
          <div style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
            <strong>{pkg.name}</strong>
            <Badge tone={BUMP_TONE[pkg.requiredBump]}>bump: {pkg.requiredBump}</Badge>
            <span className="note mono-num">
              +{pkg.added.length} −{pkg.removed.length} · {pkg.unchangedCount} unchanged
            </span>
          </div>
          {pkg.bumpUnknownReason && <div className="caveat">{pkg.bumpUnknownReason}</div>}
          {pkg.removed.map((item) => (
            <div key={item} className="codeblock" style={{ padding: "2px 8px", marginTop: 4 }}>
              <span style={{ color: "var(--bad)" }}>− {item}</span>
            </div>
          ))}
          {pkg.added.map((item) => (
            <div key={item} className="codeblock" style={{ padding: "2px 8px", marginTop: 4 }}>
              <span style={{ color: "var(--ok)" }}>+ {item}</span>
            </div>
          ))}
          {(pkg.lints ?? []).map((lint) => (
            <div key={lint.id} className="note" style={{ marginTop: 4 }}>
              <Badge tone={lint.level === "major" ? "bad" : "warn"}>{lint.id}</Badge>{" "}
              {lint.summary}
              {(lint.locations ?? []).map((location) => (
                <span key={location}> · {location}</span>
              ))}
            </div>
          ))}
        </div>
      ))}
      {untouched > 0 && interesting.length > 0 && (
        <p className="note" style={{ margin: 0 }}>
          {untouched} other package(s) measured and unchanged
        </p>
      )}
      {change.skipped.length > 0 && (
        <p className="note" style={{ marginBottom: 0 }}>
          not measured: {change.skipped.map((s) => `${s.name} (${s.reason})`).join("; ")}
        </p>
      )}
    </Panel>
  );
}

function StructuralPanel({
  diff,
  onOpen,
}: {
  diff: GraphDiff;
  onOpen: (path: string, line?: number) => void;
}) {
  return (
    <Panel
      title="structure"
      count={`${shortSha(diff.baseRevision)} → ${shortSha(diff.headRevision)}`}
    >
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
        <Badge tone="ok">+{diff.nodes.added.length} symbols</Badge>
        <Badge tone="bad">−{diff.nodes.removed.length} symbols</Badge>
        <Badge>{diff.nodes.touched.length} edited</Badge>
        <Badge tone="ok">+{diff.edges.added.length} edges</Badge>
        <Badge tone="bad">−{diff.edges.removed.length} edges</Badge>
        {diff.nodes.moved.length > 0 && <Badge tone="warn">{diff.nodes.moved.length} moved</Badge>}
      </div>

      {/* Only what the diff can prove. Each label hovers to the evidence that
          decided it; the interpretive labels live in the narrative above,
          where a claim without a citation is deleted. */}
      {(diff.labels?.length ?? 0) > 0 && (
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginBottom: 10 }}>
          <span className="microlabel" style={{ alignSelf: "center" }}>
            kind of change
          </span>
          {diff.labels!.map((label) => (
            <span
              key={label.name}
              className="badge accent"
              title={label.basis}
              data-testid="change-label"
            >
              {label.name}
            </span>
          ))}
        </div>
      )}

      {diff.edges.removed.length > 0 && (
        <>
          <div className="microlabel">relationships that no longer exist</div>
          <ul style={{ margin: "4px 0 10px", paddingLeft: "1.2em" }}>
            {diff.edges.removed.slice(0, 12).map((edge) => (
              <li key={edge.id}>
                <code>{edge.sourceLabel}</code>{" "}
                <span style={{ color: "var(--bad)" }}>—{edge.kind}→</span>{" "}
                <code>{edge.targetLabel}</code>
              </li>
            ))}
            {diff.edges.removed.length > 12 && (
              <li className="note">+{diff.edges.removed.length - 12} more</li>
            )}
          </ul>
        </>
      )}

      {diff.likelyRenamed.length > 0 && (
        <>
          <div className="microlabel">likely renamed (inference, not fact)</div>
          <ul style={{ margin: "4px 0 10px", paddingLeft: "1.2em" }}>
            {diff.likelyRenamed.map((guess) => (
              <li key={guess.beforeKey}>
                <code>{guess.beforeLabel}</code> → <code>{guess.afterLabel}</code>{" "}
                <span className="note">
                  ({Math.round(guess.confidence * 100)}% — {guess.basis})
                </span>
              </li>
            ))}
          </ul>
        </>
      )}

      <div className="microlabel">symbols this change edited</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 4 }}>
        {diff.nodes.touched.slice(0, 30).map((node) => (
          <button
            key={node.stableKey}
            className="badge"
            onClick={() => node.path && onOpen(node.path, node.startLine)}
            title={node.path ?? ""}
            style={{ cursor: node.path ? "pointer" : "default" }}
          >
            <KindDot kind={node.kind} />
            {node.label}
          </button>
        ))}
        {diff.nodes.touched.length > 30 && (
          <span className="note">+{diff.nodes.touched.length - 30} more</span>
        )}
      </div>

      {diff.packageVersionChanges.length > 0 && (
        <p className="note" style={{ marginBottom: 0 }}>
          version bumps (excluded from the structural comparison):{" "}
          {diff.packageVersionChanges
            .map((change) => `${change.name} ${change.before}→${change.after}`)
            .join(", ")}
        </p>
      )}
    </Panel>
  );
}

function ImpactPanel({
  impact,
  onOpen,
}: {
  impact: ChangeImpact;
  onOpen: (path: string, line?: number) => void;
}) {
  return (
    <Panel
      title="what else could be affected"
      count={`${impact.totalImpacted} within ${impact.hops} hop(s)`}
    >
      <table className="data">
        <thead>
          <tr>
            <th>rank</th>
            <th>symbol</th>
            <th>via</th>
            <th>claim</th>
          </tr>
        </thead>
        <tbody>
          {impact.impacted.map((item) => (
            <tr
              key={item.stableKey}
              className={item.path ? "clickable" : ""}
              onClick={() => item.path && onOpen(item.path, item.startLine)}
            >
              <td>
                <Badge tone={RANK_TONE[item.rank]}>{item.rank}</Badge>
              </td>
              <td>
                <KindDot kind={item.kind} />
                {item.label}
                {item.path && <div className="note">{item.path}</div>}
              </td>
              <td className="note">
                {item.viaEdgeKind} · hop {item.hop}
              </td>
              <td className="note">
                {item.claimStrength === "referred-to-removed-symbol"
                  ? "referred to a removed symbol"
                  : "could be affected"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {impact.suppressed > 0 && (
        <p className="note">+{impact.suppressed} more found but not listed</p>
      )}
      <div className="caveat" style={{ marginTop: 8 }}>
        {impact.caveat}
      </div>
    </Panel>
  );
}
