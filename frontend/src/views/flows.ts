// Flows: the interaction diagrams this project can draw honestly.
//
// A flow is a real chain of dependency edges starting at an entry point,
// projected onto modules. Every arrow corresponds to an edge an extractor
// produced, so a flow cannot invent an interaction — which is what separates
// it from an authored sequence diagram, and why the agent-authored protocol
// model handles the cases that genuinely need reading code.
//
// "Worth drawing" is mechanical, in the spirit of the map's readability gate:
// a flow must cross at least MIN_MODULES distinct modules. A chain inside one
// module is that module's control flow, and the source is the place to read it.

import type { GraphIndex, GraphNode } from "../graph";
import { shortLabels } from "./layout";

export interface FlowStep {
  fromModule: string;
  toModule: string;
  /** The callee whose use created this arrow. */
  viaLabel: string;
  viaKind: string;
}

export interface Flow {
  entry: string;
  reason: string;
  steps: FlowStep[];
  moduleCount: number;
}

const MIN_MODULES = 3;
/** Flows longer than this are truncated with a stated remainder — the Mermaid
 *  component refuses past ~120 lines anyway; better to bound at the source. */
const MAX_STEPS = 14;

interface EntryPoint {
  path: string;
  reason: string;
}

export function deriveFlows(
  index: GraphIndex,
  entryPoints: readonly EntryPoint[],
  options: { minModules?: number } = {},
): Flow[] {
  const minModules = options.minModules ?? MIN_MODULES;
  const flows: Flow[] = [];

  for (const entry of entryPoints) {
    const file = index.fileByPath(entry.path);
    if (!file) continue;

    // Walk greedily from the entry's definitions, always stepping to the
    // dependency that leaves the current module and reaches the widest-used
    // target. Deterministic: ties break on label.
    const steps: FlowStep[] = [];
    const visitedModules = new Set<string>([entry.path]);
    let frontier = index.definitionsOf(file.id);

    while (steps.length < MAX_STEPS) {
      const currentModule = steps.length === 0 ? entry.path : steps[steps.length - 1]!.toModule;
      const hop = bestCrossModuleHop(index, frontier, currentModule, visitedModules);
      if (!hop) break;
      steps.push(hop.step);
      visitedModules.add(hop.step.toModule);
      frontier = [hop.target];
    }

    const modules = new Set([entry.path, ...steps.map((s) => s.toModule)]);
    if (modules.size >= minModules && steps.length > 0) {
      flows.push({
        entry: entry.path,
        reason: entry.reason,
        steps,
        moduleCount: modules.size,
      });
    }
  }

  // Longest, most-crossing flows first; the caller decides how many to show.
  return flows.sort(
    (a, b) =>
      b.moduleCount - a.moduleCount ||
      b.steps.length - a.steps.length ||
      a.entry.localeCompare(b.entry),
  );
}

function bestCrossModuleHop(
  index: GraphIndex,
  frontier: GraphNode[],
  currentModule: string,
  visited: Set<string>,
): { step: FlowStep; target: GraphNode } | null {
  let best: { step: FlowStep; target: GraphNode; score: number } | null = null;

  for (const symbol of frontier) {
    for (const target of index.uses(symbol.id)) {
      const targetFile = index.fileOf(target.id);
      const targetModule = targetFile?.path;
      if (!targetModule || targetModule === currentModule || visited.has(targetModule)) {
        continue;
      }
      // Prefer the arrow whose target keeps going. Scoring by fan-in looked
      // right and was wrong at real size: high-fan-in symbols are often leaf
      // utilities, so main.rs's flow died after one hop into a getter while an
      // example file produced the only drawable chain. A flow is a story; the
      // next step is the one with somewhere to go.
      const score = index.uses(target.id).length * 100 + index.usedBy(target.id).length;
      const step: FlowStep = {
        fromModule: currentModule,
        toModule: targetModule,
        viaLabel: target.label,
        viaKind: index.edgeKind(symbol.id, target.id) ?? "depends-on",
      };
      if (
        !best ||
        score > best.score ||
        (score === best.score && step.viaLabel.localeCompare(best.step.viaLabel) < 0)
      ) {
        best = { step, target, score };
      }
    }
  }
  return best;
}

// --- rendering ---------------------------------------------------------------

function alias(module: string, index: number): string {
  const cleaned = module.replace(/[^0-9a-zA-Z]/g, "");
  return cleaned || `M${index}`;
}

/** One Mermaid sequenceDiagram per flow: participants are modules, every arrow
 *  is a measured edge, labelled with the symbol it lands on. */
export function flowToMermaid(flow: Flow): string {
  const modules: string[] = [];
  for (const step of flow.steps) {
    if (!modules.includes(step.fromModule)) modules.push(step.fromModule);
    if (!modules.includes(step.toModule)) modules.push(step.toModule);
  }
  const aliases = new Map(modules.map((module, i) => [module, alias(module, i)]));
  // Disambiguated the same way the map's labels are: ripgrep's pipeline passes
  // through two different mod.rs files, and two boxes with one name is a
  // diagram of something that does not exist.
  const short = shortLabels(modules);

  const lines = ["sequenceDiagram"];
  for (const module of modules) {
    lines.push(`    participant ${aliases.get(module)} as ${short.get(module) ?? module}`);
  }
  for (const step of flow.steps) {
    lines.push(
      `    ${aliases.get(step.fromModule)}->>${aliases.get(step.toModule)}: ${step.viaLabel}`,
    );
  }
  return lines.join("\n") + "\n";
}
