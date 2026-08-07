# ADR-0011: Manual approval for every outward-facing write

- Status: Accepted
- Date: 2026-08-05

## Context

A review system that can post is a system that can be wrong in public. The
failure modes are asymmetric: a missed defect costs a defect, but a confidently
posted false finding costs trust, and a leaked secret in a review comment costs
far more. The research this project is built on recommends assisted publication
— the system prepares the exact comment, a human presses send — as the default
mature mode, with automatic publication reserved for teams with sustained
evaluation evidence.

## Decision

**Nothing reaches the outside world without a recorded human decision.**

- The pipeline builds the payload, stores it content-addressed, and opens an
  approval against that exact artifact. The run status becomes
  `paused_for_approval`.
- Approval and rejection happen **through the CLI only**. The dashboard is
  strictly GET-only, so the reviewing surface cannot become an acting surface.
  *(Amended by ADR-0014: the API remains free of external writes and approval
  decisions, but may perform local analysis — exactly one POST, `/ask`.)*
  A decision records who made it and when; a decided approval cannot be flipped.
- What is approved is what is posted: the payload is never regenerated between
  approval and publication, so review and publication cannot diverge.

`publish_approved` re-checks every precondition against the database and the
environment on every call, because reaching a code path is not evidence of
permission:

1. the approval exists and its recorded decision is `approved`;
2. publication is enabled in configuration;
3. `CODEATLAS_KILL_SWITCH` is unset — one switch that stops all publication;
4. the approved payload contains no secrets (an independent scan, because review
   text quotes source code);
5. no publication for this approval already succeeded — posting is exactly-once.

Read and write capability are separate types: `GitHubReader` has no method that
writes, and the analysis path only ever holds a reader. Reviews are always
posted with `event: "COMMENT"` — CodeAtlas never approves a pull request or
requests changes on one; those are human judgments.

A failed publication attempt is **committed** before the error propagates. A
rolled-back failure record would erase the evidence that an outward attempt was
made at all.

## Consequences

- Shadow mode is the same code path minus a writer: the dry-run payload is
  byte-identical to what would be posted.
- Every bypass has a test: pending approval, rejected approval, unknown
  approval, disabled config, kill switch, double publication, and a payload
  containing a token.
- Automatic publication remains possible later, but it would be a new decision
  requiring its own evaluation evidence — not a configuration change.
