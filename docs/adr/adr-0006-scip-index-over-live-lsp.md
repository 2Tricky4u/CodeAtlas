# ADR-0006: SCIP index over a live language-server session

- Status: Accepted
- Date: 2026-08-05 (recorded retroactively 2026-08-07 — the decision was
  cited by `extractors/rust/ra_scip.py` from the start, but the document was
  never written)

## Context

Symbol-level facts (definitions, references, the `contains` relation) need a
language-aware source. Two ways to get them from rust-analyzer: hold a live
LSP session and interrogate it, or run `rust-analyzer scip` once and parse
the emitted index.

## Decision

Batch SCIP indexing, not live LSP.

- One subprocess invocation per revision → **one extractor receipt** per
  fact source, which is what the evidence discipline requires. A long-lived
  LSP session has no natural receipt boundary.
- The index is a file: hashable, cacheable by revision + toolchain
  fingerprint (ADR-0013's graph cache depends on this), and re-parseable
  without re-running the extractor.
- Determinism: a batch index at a pinned revision is a pure function of
  (source, toolchain); a live session's answers can depend on request
  ordering and incremental state.

The index is parsed with generated protobuf bindings
(`scripts/gen_scip_pb.py`); anything the index cannot express is simply not
claimed.

## Consequences

- Extraction cost is paid per revision, not amortized across queries — the
  graph cache (ADR-0013) exists to pay it once.
- Facts are as fresh as the index; there is no incremental update path, by
  design — a new revision is a new index.
