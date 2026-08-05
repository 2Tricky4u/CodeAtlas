# ADR-0002: Evidence-first artifact interfaces between pipeline stages

- Status: Accepted
- Date: 2026-08-05
- Deciders: CodeAtlas maintainers

## Context and problem statement

Multi-agent review systems fail in a characteristic way: agents launder plausible inference
into "fact", downstream stages build on it, and the final report cannot be audited. The
research report this project is built from (`skills_deep_research.md`) concludes that the
decisive design choice is to make **normalized evidence artifacts the interfaces between
stages** — not shared prose, not a shared conversation, not one agent's summary of another.

## Decision

1. Every stage consumes and produces **schema-validated artifacts** (JSON Schema Draft
   2020-12, versioned in `schemas/`). A stage that cannot produce a valid artifact fails
   typed — it does not emit prose instead.
2. Four provenance strata are never mixed: **facts** (extractor output with receipts),
   **agent inferences** (candidate findings), **validated findings** (post adversarial
   validation), **presentation artifacts** (diagrams, reports). Each stratum records what it
   was derived from by content hash.
3. Every deterministic fact carries an **extractor receipt** (tool, runtime-resolved version,
   revision, configuration, timestamps, exit code, output hashes). An edge or claim labeled
   compiler-, language-server-, build-system- or schema-derived must never originate from
   model inference; the graph validator enforces this structurally.
4. Evidence kinds include `llm-inference` explicitly: inference is allowed, but it is
   *labeled* and can never satisfy a gate that requires deterministic evidence.
5. Agents in the first-pass review stage receive **evidence bundles only** (graph slice,
   pinned source, intent, diff) — never each other's conclusions.

## Consequences

- Every visual element, finding, and metric in the final report can be traced to pinned
  source and a receipt (dashboard drill-down requirement).
- Testing is tractable: contracts are golden-testable, stages are replayable, and
  double-runs must produce hash-identical facts.
- Cost: more schemas and more validation code up front; accepted as the core of the product.
