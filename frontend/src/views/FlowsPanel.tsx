// The main flows through a project — or through one module — drawn from call
// edges. Refusal is a first-class outcome: a project whose calls stay inside
// one module has no flow to draw, and saying so beats inventing one, for the
// same reason the protocol modeler refuses batch tools.

import { useEffect, useMemo, useState } from "react";
import { api, type ProjectOverview } from "../api";
import { graphIndex, type GraphIndex } from "../graph";
import { Badge, Panel } from "../ui";
import { deriveFlows, flowToMermaid, type Flow } from "./flows";
import { Mermaid } from "./Mermaid";
import { ModuleLink } from "./links";

/** More than this and the page becomes a diagram dump; the rest are listed. */
const DRAWN_LIMIT = 2;

export function FlowsPanel({
  runId,
  throughModule,
}: {
  runId: string;
  /** When set, only flows passing through this module are shown. */
  throughModule?: string;
}) {
  const [index, setIndex] = useState<GraphIndex | null>(null);
  const [overview, setOverview] = useState<ProjectOverview | null>(null);
  const [drawn, setDrawn] = useState(DRAWN_LIMIT);

  useEffect(() => {
    graphIndex(runId).then(setIndex).catch(() => setIndex(null));
    api.overview(runId).then(setOverview).catch(() => setOverview(null));
  }, [runId]);

  const flows = useMemo(() => {
    if (!index || !overview) return null;
    const all = deriveFlows(index, overview.entryPoints);
    if (!throughModule) return all;
    return all.filter((flow) =>
      flow.entry === throughModule ||
      flow.steps.some((s) => s.fromModule === throughModule || s.toModule === throughModule),
    );
  }, [index, overview, throughModule]);

  if (flows === null) return null;

  if (flows.length === 0) {
    return (
      <Panel title={throughModule ? "flows through this module" : "the main flows"}>
        <p className="note" style={{ margin: 0 }} data-testid="no-flows">
          {throughModule
            ? "no cross-module flow from an entry point passes through here"
            : "no chain of calls from an entry point crosses enough modules to be worth " +
              "drawing — this project's calls stay close to home, which is a fact about " +
              "it, not a missing diagram"}
        </p>
      </Panel>
    );
  }

  return (
    <Panel
      title={throughModule ? "flows through this module" : "the main flows"}
      count={flows.length}
    >
      <p className="note" style={{ marginTop: 0 }}>
        derived from call edges: every arrow below is a dependency an extractor measured,
        labelled with the symbol it lands on · greedy main line only, side branches not shown
      </p>
      {flows.slice(0, drawn).map((flow) => (
        <FlowFigure key={flow.entry} flow={flow} />
      ))}
      {flows.length > drawn && (
        <button
          className="badge"
          style={{ cursor: "pointer" }}
          data-testid="more-flows"
          onClick={() => setDrawn(flows.length)}
        >
          draw the {flows.length - drawn} other flow(s)
        </button>
      )}
    </Panel>
  );
}

function FlowFigure({ flow }: { flow: Flow }) {
  return (
    <div style={{ marginBottom: 12 }} data-testid="flow">
      <div style={{ display: "flex", gap: 6, alignItems: "baseline", flexWrap: "wrap", marginBottom: 4 }}>
        <ModuleLink path={flow.entry} />
        <span className="note">{flow.reason}</span>
        <Badge>{flow.moduleCount} modules</Badge>
        <Badge>{flow.steps.length} hop(s)</Badge>
      </div>
      <Mermaid source={flowToMermaid(flow)} />
    </div>
  );
}
