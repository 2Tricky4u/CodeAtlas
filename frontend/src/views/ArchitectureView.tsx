// C4 Context + Container, derived from the graph rather than drawn by hand.
//
// The boxes are this repository's own packages — the crates a reader can
// actually change. Every box names the graph node it came from and every arrow
// names the graph edge, so this is the one architecture diagram in the tooling
// landscape you can interrogate: click a container and you are looking at its
// manifest at the pinned revision.
//
// Positions come from the levels the backend computed, the same way the map
// works, so two people looking at one run see the same picture.

import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import cytoscape from "cytoscape";
import { api, type Architecture, type ArchitectureContainer } from "../api";
import { Badge, Empty, ErrorBox, Loading, Panel } from "../ui";
import { positionsFromLevels, shortLabels } from "./layout";
import { SourcePanel, type SourceRequest } from "./SourcePanel";

export function ArchitectureView() {
  const { runId } = useParams();
  const [model, setModel] = useState<Architecture | null | undefined>(undefined);
  const [dsl, setDsl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [source, setSource] = useState<SourceRequest | null>(null);

  useEffect(() => {
    if (!runId) return;
    setModel(undefined);
    api
      .architecture(runId)
      .then(setModel)
      .catch((e: Error) => setError(e.message));
    api.structurizrDsl(runId).then(setDsl).catch(() => setDsl(null));
  }, [runId]);

  if (error) return <ErrorBox error={error} />;
  if (model === undefined) return <Loading />;
  if (model === null) {
    return <Empty>this run produced no architecture model</Empty>;
  }
  if (model.containers.length === 0) {
    return <Empty>{model.notes?.[0] ?? "nothing to draw"}</Empty>;
  }

  const open = (path: string) => setSource({ revision: model.revision, path });

  return (
    <div data-testid="architecture-view" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
        <strong style={{ fontSize: 13 }}>{model.systemName}</strong>
        <Badge>{model.containers.length} container(s)</Badge>
        <Badge>{model.relationships.length} relationship(s)</Badge>
        {model.readability && !model.readability.passed && (
          <Badge tone="warn">larger than a glance</Badge>
        )}
      </div>

      {(model.notes?.length ?? 0) > 0 && (
        <div className="caveat" data-testid="architecture-notes">
          {model.notes!.map((note, index) => (
            <div key={index}>{note}</div>
          ))}
        </div>
      )}

      <p className="note" style={{ margin: 0 }}>
        containers are this repository's own packages · a box opens the manifest it was
        derived from · dependencies resolved from the registry are not drawn
      </p>

      <ContainerGraph model={model} onOpen={open} />
      <ContainerTable model={model} onOpen={open} />
      {dsl && <DslPanel dsl={dsl} />}

      <SourcePanel request={source} onClose={() => setSource(null)} />
    </div>
  );
}

function ContainerGraph({
  model,
  onOpen,
}: {
  model: Architecture;
  onOpen: (path: string) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const nodes = model.containers.map((c) => ({
      id: c.key,
      label: c.name,
      level: c.level ?? 0,
    }));
    const edges = model.relationships.map((r) => ({
      source: r.sourceKey,
      target: r.targetKey,
    }));
    // Tighter than the map's step: containers are short wide boxes and there
    // are more levels of them, so the map's spacing makes the whole diagram
    // taller than the panel and `fit` shrinks the labels out of legibility.
    const positions = positionsFromLevels(nodes, edges, { spacingY: 95 });
    const maxFanIn = Math.max(1, ...model.containers.map((c) => c.fanIn ?? 0));

    const cy = cytoscape({
      container: containerRef.current,
      elements: [
        ...model.containers.map((c) => ({
          data: {
            id: c.key,
            label: c.name,
            path: c.path ?? undefined,
            fanIn: c.fanIn ?? 0,
            evidence: c.evidenceNodeId,
          },
          position: positions.get(c.key),
        })),
        ...model.relationships.map((r) => ({
          data: {
            id: `${r.sourceKey}->${r.targetKey}`,
            source: r.sourceKey,
            target: r.targetKey,
            label: r.description,
            evidence: r.evidenceEdgeId,
          },
        })),
      ],
      layout: { name: "preset" },
      style: [
        {
          selector: "node",
          style: {
            label: "data(label)",
            color: "#a8b0c2",
            "font-size": 11,
            "font-family": "ui-monospace, monospace",
            "text-valign": "center",
            "text-halign": "center",
            "text-outline-width": 2,
            "text-outline-color": "#0b0e14",
            shape: "round-rectangle",
            // A container is a box in C4, not a dot; size still carries fan-in
            // so the crate everything leans on reads as the load-bearing one.
            width: `mapData(fanIn, 0, ${maxFanIn}, 90, 150)`,
            height: 40,
            "background-color": "#1b2333",
            "border-width": 1,
            "border-color": "#7aa2f7",
          },
        },
        {
          selector: "edge",
          style: {
            width: 1,
            "curve-style": "bezier",
            "target-arrow-shape": "triangle",
            "arrow-scale": 0.7,
            "line-color": "#303952",
            "target-arrow-color": "#303952",
          },
        },
      ],
      wheelSensitivity: 0.2,
      maxZoom: 1.4,
      minZoom: 0.15,
    });
    cy.fit(undefined, 50);
    cy.on("tap", "node", (event) => {
      const path = event.target.data("path") as string | undefined;
      if (path) onOpen(path);
    });
    return () => cy.destroy();
  }, [model, onOpen]);

  return (
    <div
      ref={containerRef}
      className="graph-canvas panel"
      style={{ minHeight: 560 }}
      data-testid="architecture-graph"
    />
  );
}

function ContainerTable({
  model,
  onOpen,
}: {
  model: Architecture;
  onOpen: (path: string) => void;
}) {
  // The evidence node ids are long and share a prefix; shortening them keeps
  // the column readable without hiding which node each box came from.
  const short = useMemo(
    () => shortLabels(model.containers.map((c) => c.evidenceNodeId)),
    [model],
  );

  return (
    <Panel title="containers" count={model.containers.length}>
      <table className="data" data-testid="architecture-table">
        <thead>
          <tr>
            <th>container</th>
            <th>technology</th>
            <th style={{ textAlign: "right" }}>level</th>
            <th style={{ textAlign: "right" }}>fan-in</th>
            <th>derived from</th>
          </tr>
        </thead>
        <tbody>
          {[...model.containers]
            .sort((a, b) => (b.fanIn ?? 0) - (a.fanIn ?? 0) || a.name.localeCompare(b.name))
            .map((container) => (
              <tr key={container.key}>
                <td>
                  <ContainerName container={container} onOpen={onOpen} />
                </td>
                <td className="note">{container.technology || "—"}</td>
                <td style={{ textAlign: "right" }}>{container.level ?? "—"}</td>
                <td style={{ textAlign: "right" }}>{container.fanIn ?? 0}</td>
                <td className="note" title={container.evidenceNodeId}>
                  {short.get(container.evidenceNodeId)}
                </td>
              </tr>
            ))}
        </tbody>
      </table>
    </Panel>
  );
}

function ContainerName({
  container,
  onOpen,
}: {
  container: ArchitectureContainer;
  onOpen: (path: string) => void;
}) {
  if (!container.path) return <span>{container.name}</span>;
  return (
    <button
      onClick={() => onOpen(container.path!)}
      style={{ color: "var(--accent)" }}
      title={container.path}
    >
      {container.name}
    </button>
  );
}

function DslPanel({ dsl }: { dsl: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Panel title="structurizr workspace">
      <p className="note" style={{ marginTop: 0 }}>
        the interchange format · describes every container the build resolved, not only the
        drawn ones · open it in Structurizr for the standard C4 rendering
      </p>
      <button
        className="badge"
        style={{ cursor: "pointer", marginBottom: 8 }}
        data-testid="copy-dsl"
        onClick={() => {
          void navigator.clipboard?.writeText(dsl);
          setCopied(true);
        }}
      >
        {copied ? "copied" : "copy workspace.dsl"}
      </button>
      <pre className="codeblock" data-testid="dsl" style={{ maxHeight: 320, overflow: "auto" }}>
        {dsl}
      </pre>
    </Panel>
  );
}
