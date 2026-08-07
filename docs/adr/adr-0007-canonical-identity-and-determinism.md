# ADR-0007: Canonical serialization, content-derived identity, determinism

- Status: Accepted
- Date: 2026-08-05 (recorded retroactively 2026-08-07 — cited by
  `core/canonical.py`, `core/ids.py`, `core/paths.py`, `change/graph.py` and
  the graph cache from the start, but the document was never written)

## Context

The product's claims rest on reproducibility: two runs at the same revision
with the same toolchain must produce byte-identical artifacts, and a diff
between two revisions must compare *identities*, not serialization accidents.

## Decision

Three rules, enforced in `codeatlas.core` and tested by the determinism
suite:

1. **Canonical JSON**: UTF-8, sorted keys, LF line endings, no NaN, no
   non-string keys, no timestamps inside hashed payloads. `canonical_sha256`
   over that form is the only content address in the system.
2. **Content-derived identity**: graph node and edge ids are deterministic
   functions of what they identify (symbol identity, endpoints + kind) —
   never sequence numbers — so the structural diff is a set operation and
   the graph cache key (revision + toolchain fingerprint) is honest.
   Runtime identities (runs, tasks) are ULIDs, deliberately excluded from
   hashed payloads.
3. **Forward-slash repo-relative paths** everywhere a path is data, on every
   platform. Windows-first development is exactly why: a backslash that
   leaks into a hashed artifact makes the same analysis hash differently by
   OS.

## Consequences

- Double runs at the same revision hash identically — pinned by
  `tests/integration/test_determinism.py` with two genuinely separate runs.
- Anything added to a hashed payload must itself be deterministic; the
  manifest keeps `runId` and cost out of the comparison for this reason.
- `run_compare` can state "REPRODUCIBLE" as a fact rather than a hope.
