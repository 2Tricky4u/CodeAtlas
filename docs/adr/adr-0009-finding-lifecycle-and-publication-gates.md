# ADR-0009: Finding lifecycle and publication gates

- Status: Accepted
- Date: 2026-08-05

## Context

A reviewing model can be fluent, specific, and confident about a defect that
does not exist. Anthropic's own review tooling filters on a confidence score,
but confidence is correlated across agents that share a model and a view of the
repository — so a high score can mean "several agents made the same mistake"
rather than "this is real". A gate built on confidence is a gate that opens for
articulate errors.

## Decision

**Every candidate finding reaches exactly one terminal status**: `validated`,
`rejected`, `duplicate`, or `unresolved`. Nothing leaves the validation stage as
a candidate; the stage asserts this before returning.

The order is deterministic-first, because cheap certainty should not cost an
agent call:

1. **Deduplicate** on genuine span overlap. Two reviewers citing the same lines
   describe one defect; the highest-severity one is canonical (ties break on the
   lowest finding id). Neighbouring-but-non-overlapping spans stay separate —
   a wider window silently collapsed two distinct traversal defects in adjacent
   methods into one.
2. **Reject dead locations** — a citation to code that does not exist at the
   analyzed revision is refuted by the file table, with no agent involved.
3. **Attach tool evidence** at the finding's location (compiler and lint
   diagnostics) ourselves. This evidence is the pipeline's, not the agent's.
4. **Adversarially validate** each survivor in a fresh context. The validator
   receives the claim, its location, the source, and the verification index —
   **never the discovering agent's reasoning**. Its instructions direct it to
   look for the reason the finding is *wrong* first, and its
   `counterEvidenceChecked` list must be non-empty and specific.

**Publication eligibility is recomputed from evidence by `rules.py`, ignoring
both the validator's `confidence` and its own `publicationEligible` opinion.** A
finding is publishable only with at least one of: a failing test or command (a
zero exit code reproduced nothing), a static-analysis or compiler diagnostic, an
exactly violated stated rule, a concrete call path, or independent fresh-context
confirmation. `unresolved` is an honest, reportable outcome — it is never
publishable.

## Consequences

- An agent cannot argue a finding into publication. The only path is evidence
  that exists independently of it.
- Some real defects will be `unresolved` for lack of reproducible evidence.
  That is the intended trade: the report says so rather than guessing.
- Cross-category duplicates (the same `unwrap()` seen by correctness and
  security) collapse to one defect with the provenance of both preserved.
