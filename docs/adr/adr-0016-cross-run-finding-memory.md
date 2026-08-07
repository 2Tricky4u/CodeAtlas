# ADR-0016: Cross-run finding memory

- Status: Accepted
- Date: 2026-08-07
- Relates to: ADR-0007 (determinism), ADR-0009 (finding lifecycle), ADR-0013 (cross-run reuse)

## Context

The validator closes every candidate finding with a reason — and then forgets.
Re-running on the same repository re-discovers, re-dispatches and re-pays for
every previously-rejected finding: the agent ledger prices each validation, and
repeat runs on the same repos are the normal way this tool is used. Three
unrelated skill ecosystems converged on the same missing primitive (a rejected
proposal recorded as an ADR so reviews stop re-suggesting it; a performance
attempt ledger including reverted experiments; per-occurrence reconciliation of
security findings across scans) — when independent authors all build negative-
result memory, it is load-bearing.

## Decision

A `finding_memory` table remembers **agent-produced rejections only**, keyed by
`(repository_id, fingerprint, file_blob_sha)`, append-only:

- **Fingerprint** = canonical hash of `{category, path, enclosingSymbol‖null}`.
  The enclosing symbol is the *smallest* measured definition span containing the
  finding's start line (ties broken by lexicographic node id). No line numbers
  and no claim text in the hash, so the identity survives code moving and the
  model rewording its claim.
- **The blob is in the key.** Suppression applies only while the file's
  `git_blob_sha` at the current revision equals the remembered one. Any edit to
  the file re-opens its rejections; the re-rejection then records a *new* row at
  the new blob. Same key ⟹ same decision by construction — which is why the
  rows are append-only and never overwritten (the `graph_cache` rule).
- **Spans must overlap.** The memory row stores the rejected finding's line
  span; a candidate suppresses only if its span overlaps it (the deduplication
  overlap rule). Identical blob means identical line numbers, so this is stable
  by construction, and it stops one rejection from silencing a *different*
  defect in the same function.
- **Suppression happens before dispatch** and costs nothing: the finding is
  persisted as `status="suppressed"` with a provenance record
  (`memoryFingerprint`, `decidedInRun`, the original `reason`) in its
  validation payload. The agent-output schema (`validation-result.v1`) is
  deliberately *not* extended with this status — an agent must never be able to
  emit "suppressed".
- **What is never remembered:** pre-dispatch rejections (dedup, dead locations —
  they cost no agent call), duplicates (canonical selection is per-run), and
  `unresolved` (a broken replay or exhausted quota would otherwise poison the
  whole repository's memory in one run).
- Any miss — unknown fingerprint, changed blob, no span overlap — fails open
  into normal validation. One wasted agent call is the price of a wrong
  suppression never hiding a real defect.

### Reproducibility

Run 2 at the same revision turns run 1's `rejected` into `suppressed`, which
`codeatlas compare` would read as non-reproducible — breaking ADR-0007's
promise by design. The run snapshot therefore folds `suppressed` into
`rejected` in its status counts and says so in a note: memory changes *how* a
verdict was reached, not *what* the verdict is.

## Consequences

- Every run makes the next one cheaper and quieter on the same code; the funnel
  shows "suppressed (remembered)" rows with the original run and reason, so the
  history is inspectable rather than silent.
- Honest limits, accepted: a rejection whose justification lives in *another*
  file ("the caller checks this") is not re-opened when that other file
  changes — scope may widen later (dependency-aware), never narrow. And
  fingerprints embed extractor-shaped node ids, so a toolchain or normalization
  bump silently drops the hit rate to zero — fail-open, visible in the funnel
  as re-validation.
- The validator's `reason` (required since W1) is now user-facing twice: in the
  funnel at decision time, and replayed by every later suppression. An empty or
  lazy reason would propagate across runs; the schema forbids the former and
  the skill prompt leans on the latter.
