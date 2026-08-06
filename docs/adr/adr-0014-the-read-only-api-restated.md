# ADR-0014: The read-only API, restated — no external writes, no approval decisions

- Status: Accepted
- Date: 2026-08-07
- Amends: ADR-0011

## Context

ADR-0011 made the dashboard's API "strictly GET-only, so the reviewing surface
cannot become an acting surface". That wording protected two properties at once
without distinguishing them:

1. **Nothing reaches the outside world without a recorded human decision** —
   the property that actually matters, and the reason the approval flow lives
   at the CLI.
2. **The API process never performs any write at all** — an implementation
   detail that happened to be a convenient way to get property 1.

Phase 3 adds "ask a question about this code": a reader on a module page asks
something, an agent answers from that module's graph slice and source, the
answer is citation-validated and cached as an artifact. Answering spends agent
quota and stores an artifact, so it cannot be a GET. Under ADR-0011's literal
wording the feature is impossible; under its intent it is unremarkable — an
answer artifact in the local store is not an outward-facing write any more than
the run pipeline's own artifacts are.

## Decision

The rule is restated as what it was protecting:

**The API performs no external writes and no approval decisions.**

- It may perform *local analysis*: work whose effects are confined to the
  content store and the database, of the same character as what the pipeline
  writes on every run.
- It may never publish, comment, push, or touch any remote system.
- It may never create, decide, or modify an approval. The approval flow remains
  CLI-only, exactly as ADR-0011 specifies.

`POST /api/runs/{id}/ask` is the first endpoint under this rule, and it is
governed like every other agent invocation:

- refused when `CODEATLAS_KILL_SWITCH` is set;
- refused when the server was started without an agent engine (asking is
  opt-in via `codeatlas serve --ask`, off by default);
- budgeted with the same `TokenBudget` machinery as pipeline agents;
- its answers validated by the same citation rule as the narratives — a
  sentence whose citation does not resolve is deleted and the removal
  disclosed;
- its answers cached content-addressed and keyed by (revision, scope,
  question), so a repeated question costs nothing and every answer is
  reproducible evidence like any other artifact.

Every mutation-capable method on every *other* route remains rejected, and the
security tests that pinned that continue to pass unchanged.

## Consequences

- The dashboard can host interactive analysis without becoming an acting
  surface; "acting" is now defined by effect (external write, approval), not by
  HTTP verb.
- A future endpoint wanting to write must argue it is local analysis under this
  rule — or it is prohibited. The default for anything touching the outside
  world is unchanged: CLI, human, recorded decision.
- The kill switch gains a second consumer, which is a feature: one switch
  stops every agent invocation in the system, wherever it is dispatched from.
