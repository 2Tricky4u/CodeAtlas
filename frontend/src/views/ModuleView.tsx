// One file, explained: what it defines, who uses each definition, what it
// imports, where it sits — and, when this run analysed a change, what that
// change did to it.
//
// Everything measured, nothing recomputed. Structure comes from the graph index
// (one fetch per run, shared); level, fan-in and cycle membership come from the
// overview artifact; the change section reads the diff, findings, API delta and
// impact set the run already produced. When the run has no base revision the
// change section is absent, not empty — the same rule the change view follows.

import { useEffect, useMemo, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import {
  api,
  type ApiChange,
  type ChangeImpact,
  type Finding,
  type GraphDiff,
  type ProjectOverview,
  type RunSummary,
} from "../api";
import { graphIndex, type GraphIndex, type GraphNode } from "../graph";
import { Badge, Empty, ErrorBox, KindDot, Loading, Panel, SEVERITY_TONE } from "../ui";
import { AskPanel } from "./AskPanel";
import { FlowsPanel } from "./FlowsPanel";
import { ModuleLink } from "./links";
import { apiItemsFor, orderDefinitions } from "./moduleLogic";
import { SourcePanel, type SourceRequest } from "./SourcePanel";

export function ModuleView() {
  const { runId, "*": path = "" } = useParams();
  const [searchParams] = useSearchParams();
  const anchorSymbol = searchParams.get("symbol");

  const [index, setIndex] = useState<GraphIndex | null>(null);
  const [overview, setOverview] = useState<ProjectOverview | null>(null);
  const [run, setRun] = useState<RunSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [source, setSource] = useState<SourceRequest | null>(null);
  const [explainQuestion, setExplainQuestion] = useState<string | null>(null);

  useEffect(() => {
    if (!runId) return;
    setError(null);
    graphIndex(runId)
      .then(setIndex)
      .catch((e: Error) => setError(e.message));
    api.overview(runId).then(setOverview).catch(() => setOverview(null));
    api.runDetail(runId).then(setRun).catch(() => setRun(null));
  }, [runId]);

  if (error) return <ErrorBox error={error} />;
  if (!index) return <Loading />;

  const file = index.fileByPath(path);
  if (!file) {
    return (
      <Empty>
        {path} is not a module this run's graph contains — it may be generated, ignored, or
        from a different revision
      </Empty>
    );
  }

  const summary = overview?.modules.find((m) => m.path === path) ?? null;
  const cycle = overview?.cycles.find((c) => c.members.includes(path)) ?? null;
  const definitions = index.definitionsOf(file.id);
  const users = index.moduleUsers(file.id);
  const imports = index.moduleImports(file.id);

  const open = (startLine?: number) =>
    setSource({ revision: index.revision, path, startLine });

  return (
    <div data-testid="module-view" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <header style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
        <strong style={{ fontSize: 14 }}>{path}</strong>
        {summary && (
          <>
            <Badge>level {summary.level}</Badge>
            <Badge>fan-in {summary.fanIn}</Badge>
            <Badge>fan-out {summary.fanOut}</Badge>
            <Badge>{summary.symbolCount} symbol(s)</Badge>
          </>
        )}
        {cycle && (
          <Badge tone="warn">
            in a cycle of {cycle.members.length}
          </Badge>
        )}
        <button className="badge" style={{ cursor: "pointer" }} onClick={() => open()}>
          open source
        </button>
      </header>

      {overview && <ReadingOrder overview={overview} path={path} />}

      {cycle && (
        <div className="caveat" data-testid="cycle-note">
          this module cannot be read alone — it is mutually dependent with{" "}
          {cycle.members
            .filter((member) => member !== path)
            .map((member, i) => (
              <span key={member}>
                {i > 0 && " · "}
                <ModuleLink path={member} className="badge warn" />
              </span>
            ))}
        </div>
      )}

      {runId && run?.baseSha && <ChangeHere runId={runId} path={path} index={index} />}

      <Panel title="what it defines" count={definitions.length}>
        {definitions.length === 0 ? (
          <Empty>the graph records no symbols defined in this file</Empty>
        ) : (
          <DefinitionList
            definitions={definitions}
            index={index}
            anchorSymbol={anchorSymbol}
            onOpen={open}
            onExplain={(label) => setExplainQuestion(`What does \`${label}\` do?`)}
          />
        )}
      </Panel>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <Panel title="used by" count={users.length}>
          <p className="note" style={{ marginTop: 0 }}>
            modules that depend on something defined here
          </p>
          {users.length === 0 ? (
            <Empty>nothing outside this file uses its definitions</Empty>
          ) : (
            <ul style={{ margin: 0, paddingLeft: "1.2em" }} data-testid="module-users">
              {users.map(([userFile, symbols]) => (
                <li key={userFile.id} style={{ marginBottom: 6 }}>
                  {userFile.path ? (
                    <ModuleLink path={userFile.path} />
                  ) : (
                    <span className="badge">{userFile.label}</span>
                  )}{" "}
                  <span className="note">
                    via {symbols.map((s) => s.label).join(", ")}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel title="imports" count={imports.length}>
          <p className="note" style={{ marginTop: 0 }}>
            what this module's definitions reach for
          </p>
          {imports.length === 0 ? (
            <Empty>this module depends on nothing else in the project</Empty>
          ) : (
            <ul style={{ margin: 0, paddingLeft: "1.2em" }} data-testid="module-imports">
              {imports.map(([targetFile, symbols]) => (
                <li key={targetFile.id} style={{ marginBottom: 6 }}>
                  {targetFile.path ? (
                    <ModuleLink path={targetFile.path} />
                  ) : (
                    <span className="badge">{targetFile.label}</span>
                  )}{" "}
                  <span className="note">for {symbols.map((s) => s.label).join(", ")}</span>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      {runId && <FlowsPanel runId={runId} throughModule={path} />}

      {runId && (
        <AskPanel
          runId={runId}
          scope={path}
          onOpenSource={(citedPath, startLine) =>
            setSource({ revision: index.revision, path: citedPath, startLine })
          }
          queuedQuestion={explainQuestion}
          onQueuedConsumed={() => setExplainQuestion(null)}
        />
      )}

      <SourcePanel request={source} onClose={() => setSource(null)} />
    </div>
  );
}

/** "Start here" as a walk rather than a list: when this module is one of the
 *  overview's ranked entry points, say which step it is and where the walk
 *  goes next — so "where do I begin" keeps answering past the first click.
 *  Derived from the overview already on the page; nothing new is fetched. */
function ReadingOrder({ overview, path }: { overview: ProjectOverview; path: string }) {
  // startHere, not entryPoints: the walk is the *ranked* list with a reason
  // per step, the same one the overview page numbers. entryPoints is the raw
  // set of roots, and live it begins at an auxiliary crate's lib.rs.
  const order = overview.startHere;
  const position = order.findIndex((entry) => entry.path === path);
  if (position === -1) return null;
  const entry = order[position]!;
  const previous = order[position - 1];
  const next = order[position + 1];
  return (
    <div
      className="panel"
      style={{ padding: "8px 12px", display: "flex", gap: 10, alignItems: "baseline", flexWrap: "wrap" }}
      data-testid="reading-order"
    >
      <Badge tone="info">
        reading order · {position + 1} of {order.length}
      </Badge>
      <span className="note">{entry.reason}</span>
      <span style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
        {previous && (
          <ModuleLink path={previous.path} title={previous.reason}>
            <span data-testid="reading-prev">← {previous.path.split("/").pop()}</span>
          </ModuleLink>
        )}
        {next && (
          <ModuleLink path={next.path} title={next.reason}>
            <span data-testid="reading-next">{next.path.split("/").pop()} →</span>
          </ModuleLink>
        )}
      </span>
    </div>
  );
}

/** Past this, a kind group collapses to its most-used members. */
const GROUP_LIMIT = 12;

function DefinitionList({
  definitions,
  index,
  anchorSymbol,
  onOpen,
  onExplain,
}: {
  definitions: GraphNode[];
  index: GraphIndex;
  anchorSymbol: string | null;
  onOpen: (startLine?: number) => void;
  onExplain: (label: string) => void;
}) {
  const [expanded, setExpanded] = useState<string | null>(anchorSymbol);
  const [showAll, setShowAll] = useState<Set<string>>(new Set());
  useEffect(() => setExpanded(anchorSymbol), [anchorSymbol]);

  const byKind = useMemo(() => orderDefinitions(definitions, index), [definitions, index]);

  return (
    <div data-testid="definitions">
      {byKind.map(([kind, fullList]) => {
        // A deep link expands the group holding its symbol — not every group;
        // arriving at walk.rs via ?symbol= must not unfold all 148 functions.
        const open =
          showAll.has(kind) ||
          (anchorSymbol !== null && fullList.some((d) => d.id === anchorSymbol));
        const list = open ? fullList : fullList.slice(0, GROUP_LIMIT);
        const hidden = fullList.length - list.length;
        return (
        <div key={kind} style={{ marginBottom: 8 }}>
          <div className="microlabel" style={{ marginBottom: 4 }}>
            <KindDot kind={kind} /> {kind} · {fullList.length}
          </div>
          <ul style={{ margin: 0, paddingLeft: "1.2em", listStyle: "none" }}>
            {list.map((definition) => {
              const callers = index.usedBy(definition.id);
              const isOpen = expanded === definition.id;
              return (
                <li key={definition.id} style={{ marginBottom: 4 }}>
                  <button
                    style={{
                      color: isOpen ? "var(--accent)" : "var(--fg-0)",
                      cursor: "pointer",
                    }}
                    data-testid="definition"
                    onClick={() => setExpanded(isOpen ? null : definition.id)}
                    title={definition.id}
                  >
                    {definition.label}
                  </button>{" "}
                  <span className="note mono-num">
                    {callers.length > 0 ? `← ${callers.length}` : "unused here"}
                  </span>
                  {definition.startLine && (
                    <button
                      className="note"
                      style={{ cursor: "pointer", marginLeft: 6 }}
                      onClick={() => onOpen(definition.startLine)}
                    >
                      :{definition.startLine}
                    </button>
                  )}
                  <button
                    className="note"
                    style={{ cursor: "pointer", marginLeft: 6 }}
                    data-testid="explain-symbol"
                    title="ask the agent, cited and cached (spends quota once per symbol)"
                    onClick={() => onExplain(definition.label)}
                  >
                    explain?
                  </button>
                  {isOpen && <Callers callers={callers} index={index} />}
                </li>
              );
            })}
          </ul>
          {hidden > 0 && (
            <button
              className="badge"
              style={{ cursor: "pointer", marginLeft: "1.2em" }}
              data-testid="show-all-definitions"
              onClick={() => setShowAll(new Set([...showAll, kind]))}
            >
              show the {hidden} less-used {kind}(s)
            </button>
          )}
        </div>
        );
      })}
    </div>
  );
}

function Callers({ callers, index }: { callers: GraphNode[]; index: GraphIndex }) {
  if (callers.length === 0) {
    return (
      <p className="note" style={{ margin: "2px 0 6px 1em" }}>
        no measured dependency reaches this symbol from outside its own expressions
      </p>
    );
  }
  // Group by the caller's module, so "who uses this" reads at the level a
  // person navigates at.
  const grouped = new Map<string, { file: GraphNode | undefined; symbols: GraphNode[] }>();
  for (const caller of callers) {
    const file = index.fileOf(caller.id);
    const key = file?.id ?? "?";
    const entry = grouped.get(key) ?? { file, symbols: [] };
    entry.symbols.push(caller);
    grouped.set(key, entry);
  }
  return (
    <ul style={{ margin: "2px 0 6px", paddingLeft: "1.4em" }} data-testid="callers">
      {[...grouped.values()]
        .sort((a, b) => (a.file?.label ?? "").localeCompare(b.file?.label ?? ""))
        .map(({ file, symbols }) => (
          <li key={file?.id ?? "?"} className="note" style={{ marginBottom: 2 }}>
            {file?.path ? <ModuleLink path={file.path} /> : (file?.label ?? "unknown")}{" "}
            {symbols.map((s) => s.label).join(", ")}
          </li>
        ))}
    </ul>
  );
}

// --- the change, where you are looking (H2) ----------------------------------

function ChangeHere({
  runId,
  path,
  index,
}: {
  runId: string;
  path: string;
  index: GraphIndex;
}) {
  const [diff, setDiff] = useState<GraphDiff | null>(null);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [apiChange, setApiChange] = useState<ApiChange | null>(null);
  const [impact, setImpact] = useState<ChangeImpact | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    setLoaded(false);
    Promise.all([
      api.graphDiff(runId).catch(() => null),
      api.findings(runId).catch(() => [] as Finding[]),
      api.apiChange(runId).catch(() => null),
      api.impact(runId).catch(() => null),
    ]).then(([d, f, a, i]) => {
      setDiff(d);
      setFindings(f);
      setApiChange(a);
      setImpact(i);
      setLoaded(true);
    });
  }, [runId]);

  if (!loaded) return null;

  const touched = [
    ...(diff?.nodes.added.filter((n) => n.path === path).map((n) => ({ ...n, what: "added" })) ??
      []),
    ...(diff?.nodes.removed
      .filter((n) => n.path === path)
      .map((n) => ({ ...n, what: "removed" })) ?? []),
    ...(diff?.nodes.touched
      .filter((n) => n.path === path)
      .map((n) => ({ ...n, what: "edited" })) ?? []),
  ];
  const movedIn = diff?.nodes.moved.filter((m) => m.afterPath === path) ?? [];
  const movedOut = diff?.nodes.moved.filter((m) => m.beforePath === path) ?? [];
  const foundHere = findings.filter((f) => f.path === path);

  // The definitions of this file that the API delta names.
  const definitionLabels = new Set(
    index.definitionsOf(index.fileByPath(path)?.id ?? "").map((d) => d.label),
  );
  const apiItems = apiItemsFor(apiChange, definitionLabels);
  const impacted =
    impact?.impacted.filter((entry) => entry.path === path) ?? [];

  const anything =
    touched.length || movedIn.length || movedOut.length || foundHere.length || apiItems.length || impacted.length;

  return (
    <Panel title="what this change did here" count={touched.length + movedIn.length + movedOut.length}>
      {!anything ? (
        <Empty>this change did not touch this module, and nothing here was flagged</Empty>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }} data-testid="change-here">
          {touched.length > 0 && (
            <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
              {touched.map((node) => (
                <span
                  key={`${node.what}:${node.stableKey}`}
                  className="badge"
                  data-testid="changed-symbol"
                >
                  <KindDot kind={node.kind} /> {node.label}{" "}
                  <span
                    style={{
                      color:
                        node.what === "added"
                          ? "var(--ok)"
                          : node.what === "removed"
                            ? "var(--bad)"
                            : "var(--warn)",
                    }}
                  >
                    {node.what}
                  </span>
                </span>
              ))}
            </div>
          )}
          {movedIn.map((m) => (
            <p key={m.stableKey} style={{ margin: 0 }}>
              <strong>{m.label}</strong> moved here from <ModuleLink path={m.beforePath} />
            </p>
          ))}
          {movedOut.map((m) => (
            <p key={m.stableKey} style={{ margin: 0 }}>
              <strong>{m.label}</strong> moved out, to <ModuleLink path={m.afterPath} />
            </p>
          ))}

          {foundHere.length > 0 && (
            <div data-testid="findings-here">
              <div className="microlabel">found in this file</div>
              <ul style={{ margin: "4px 0 0", paddingLeft: "1.2em" }}>
                {foundHere.map((finding) => (
                  <li key={finding.findingId} style={{ marginBottom: 4 }}>
                    <Badge tone={SEVERITY_TONE[finding.severity] ?? "plain"}>
                      {finding.severity}
                    </Badge>{" "}
                    <Badge>{finding.status}</Badge> {finding.claim}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {apiItems.length > 0 && (
            <div data-testid="api-here">
              <div className="microlabel">on the public surface</div>
              <ul style={{ margin: "4px 0 0", paddingLeft: "1.2em" }}>
                {apiItems.map(({ item, what }) => (
                  <li key={item} className="note">
                    <span style={{ color: what === "added" ? "var(--ok)" : "var(--bad)" }}>
                      {what}
                    </span>{" "}
                    <code>{item}</code>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {impacted.length > 0 && (
            <div className="caveat" data-testid="impact-here">
              {impacted.length} symbol(s) here could be affected by this change — could, not
              known to be: {impact?.caveat}
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}
