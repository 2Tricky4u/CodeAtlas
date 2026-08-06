// The project narrative: the one thing on the overview page a model wrote.
//
// It is deliberately rendered *after* the deterministic counts, cycles and
// "start here" list, and every claim carries its citations as controls, because
// the reader needs to be able to tell at a glance which half of this page is
// measured and which half is narrated — and to check the narrated half against
// the measured one without leaving the page.

import { useEffect, useMemo, useState } from "react";
import { api, type ProjectCitation, type ProjectExplanation } from "../api";
import { Panel } from "../ui";
import { shortLabels } from "./layout";

/** Past this many claims the sections start collapsed. */
const COLLAPSE_ABOVE = 8;

/** Module keys are graph node ids (`file:kvstore/src/lib.rs`); the path is the
 *  part a reader recognises, and it is what `source` citations already use. */
const modulePath = (key: string) => key.replace(/^[a-z-]+:/, "");

export function NarrativePanel({
  runId,
  onOpenSource,
  onShowModule,
}: {
  runId: string;
  onOpenSource: (path: string, startLine?: number) => void;
  onShowModule?: (key: string) => void;
}) {
  const [explanation, setExplanation] = useState<ProjectExplanation | null | undefined>(undefined);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    setExplanation(undefined);
    setExpanded(false);
    api
      .projectExplanation(runId)
      .then(setExplanation)
      .catch(() => setExplanation(null));
  }, [runId]);

  // Two files both called `Cargo.toml` produce two chips a reader cannot tell
  // apart; disambiguate across the whole narrative, not per claim.
  const short = useMemo(() => {
    const paths = (explanation?.sections ?? []).flatMap((section) =>
      section.claims.flatMap((claim) =>
        claim.citations.flatMap((citation) =>
          citation.kind === "source"
            ? [citation.path]
            : citation.kind === "module"
              ? [modulePath(citation.key)]
              : [],
        ),
      ),
    );
    return shortLabels(paths);
  }, [explanation]);

  if (explanation === undefined) return null;

  if (explanation === null) {
    return (
      <p className="note" data-testid="no-narrative">
        no narrative was produced for this run (reviews disabled, or the explainer did
        not complete) — everything above is measured and stands on its own
      </p>
    );
  }

  const dropped = explanation.droppedClaims?.length ?? 0;
  const claimCount = explanation.sections.reduce((n, s) => n + s.claims.length, 0);
  // A real narrative runs to dozens of claims, which would push every measured
  // panel off the page — and the measurements are the part that is checkable.
  // The summary always shows; the detail is one click away.
  const collapsible = claimCount > COLLAPSE_ABOVE;
  const showSections = expanded || !collapsible;

  return (
    <Panel title="what this project is" count={claimCount}>
      <p data-testid="narrative-summary" style={{ marginTop: 0 }}>
        {explanation.summary}
      </p>
      {collapsible && (
        <button
          className="badge"
          style={{ cursor: "pointer", marginBottom: showSections ? 10 : 0 }}
          onClick={() => setExpanded(!expanded)}
          data-testid="narrative-toggle"
        >
          {showSections
            ? "hide the detail"
            : `${claimCount} cited statement(s) across ${explanation.sections.length} section(s) — read them`}
        </button>
      )}
      {showSections &&
        explanation.sections.map((section) => (
          <div key={section.id} style={{ marginBottom: 12 }} data-testid={`narrative-${section.id}`}>
            <h4 style={{ margin: "0 0 4px", fontSize: 12, color: "var(--fg-2)" }}>
              {section.title}
            </h4>
            <ul style={{ margin: 0, paddingLeft: "1.2em" }}>
              {section.claims.map((claim, claimIndex) => (
                <li key={claimIndex} style={{ marginBottom: 5 }}>
                  {claim.text}{" "}
                  {claim.citations.map((citation, citationIndex) => (
                    <ProjectCitationChip
                      key={citationIndex}
                      citation={citation}
                      short={short}
                      onOpenSource={onOpenSource}
                      onShowModule={onShowModule}
                    />
                  ))}
                </li>
              ))}
            </ul>
          </div>
        ))}
      {explanation.notes?.map((note, index) => (
        <p key={index} className="note">
          {note}
        </p>
      ))}
      {dropped > 0 && (
        <div className="caveat" data-testid="narrative-dropped">
          {dropped} statement(s) were removed because their citations did not resolve
          against the deterministic overview
        </div>
      )}
    </Panel>
  );
}

function ProjectCitationChip({
  citation,
  short,
  onOpenSource,
  onShowModule,
}: {
  citation: ProjectCitation;
  short: Map<string, string>;
  onOpenSource: (path: string, startLine?: number) => void;
  onShowModule?: (key: string) => void;
}) {
  if (citation.kind === "source") {
    return (
      <button
        onClick={() => onOpenSource(citation.path, citation.startLine)}
        className="badge accent"
        style={{ marginLeft: 4, cursor: "pointer" }}
        title={citation.path}
        data-testid="narrative-citation"
      >
        {short.get(citation.path) ?? citation.path}
        {citation.startLine ? `:${citation.startLine}` : ""}
      </button>
    );
  }
  if (citation.kind === "module") {
    // Prefixed because a module and a file at the same path are different
    // things being cited: one is a node the graph measured, the other is text.
    return (
      <button
        onClick={() =>
          onShowModule ? onShowModule(citation.key) : onOpenSource(modulePath(citation.key))
        }
        className="badge accent"
        style={{ marginLeft: 4, cursor: "pointer" }}
        title={citation.key}
        data-testid="narrative-citation"
      >
        mod {short.get(modulePath(citation.key)) ?? modulePath(citation.key)}
      </button>
    );
  }
  if (citation.kind === "package") {
    return (
      <span className="badge" style={{ marginLeft: 4 }} data-testid="narrative-citation">
        crate {citation.name}
      </span>
    );
  }
  // A cycle citation names its exact members, which is what made it checkable;
  // showing the count with the members on hover keeps that visible.
  return (
    <span
      className="badge warn"
      style={{ marginLeft: 4 }}
      title={citation.members.join(" ⇄ ")}
      data-testid="narrative-citation"
    >
      cycle of {citation.members.length}
    </span>
  );
}
