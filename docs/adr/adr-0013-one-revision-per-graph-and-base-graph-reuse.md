# ADR-0013: One revision per graph, and reuse of already-analyzed base graphs

- Status: Accepted
- Date: 2026-08-06

## Context

Reviewing a pull request means answering "what did this code do before, and what
does it do now". Until this change the pipeline pinned the base SHA in the source
lock and then never looked at it: only the head revision was extracted, so
nothing downstream could describe the *before* half of that question, and there
was no second graph to diff against.

Analyzing two revisions raises two questions that had to be settled together.

**Does a graph know about the other revision?** `project-graph.v1` has a
`revision.base` slot, unused since it was defined. Filling it in for the head
graph of a pull-request run is tempting and wrong.

**What does two revisions cost?** rust-analyzer indexing the workspace is by far
the most expensive stage of a run, and this change doubles it. On a repository
where several pull requests target the same branch, the same base commit gets
re-extracted for every one of them.

## Decision

**A project graph describes exactly one revision.** `revision.base` stays null.
The pairing of two revisions lives on the `run` row (`base_revision_id`,
`head_revision_id`) and, from P2b onward, in the graph-diff artifact — both of
which are *about* a comparison, which a graph is not.

The reason is not tidiness. By ADR-0007 an artifact's canonical hash is a
function of its content, and determinism is checked by re-running and comparing
hashes. If the head graph embedded the base SHA, the same head analyzed against
two different bases would produce two different hashes for identical code, and
the graph would stop being addressable by what it actually describes. The cache
below depends directly on that property.

**Graph snapshots carry an explicit `role`** (`base` or `head`), with a unique
constraint on `(run_id, role)`. Every reader names the role it means. There is no
"the run's graph" any more, because a pull-request run has two.

**The base graph is served from a cache keyed by (revision, toolchain
fingerprint).** The fingerprint covers the extractor versions *and* a declared
`GRAPH_PIPELINE_VERSION` for our own normalization code — the three inputs a
graph is a deterministic function of. When the key matches, the stored graph is
by construction the graph re-extraction would produce.

**Only the base is cached; the head is always extracted.** The head is the
subject of the review, and a run that claims to have reviewed code should hold
its own receipts for that code rather than inherit someone else's. A cache entry
records `produced_by_run_id`, so a reused base graph still leads back to the run
whose receipts witness it, and a hit is written to the run's event log
(`base_graph_cache_hit`) rather than happening silently.

## Consequences

- A pull-request run costs two extractions the first time a base commit is seen
  and one thereafter. Repeated reviews of pull requests against the same branch
  converge on the cost of the old single-revision pipeline.
- Reproducibility is unaffected and now checked in both directions: two runs of
  the same pull request must produce identical head and base hashes, one of them
  from the cache. A cache that changed results would fail that test rather than
  quietly succeed.
- `codeatlas compare` reads the head snapshot by role. Ordering by insertion
  would have handed it whichever snapshot was written last — for a pull-request
  run, the base — and reported a genuinely changed run as reproducible. A false
  all-clear is worse than no answer, so this is asserted directly in
  `tests/integration/test_two_revisions.py`.
- Migration `1713be53b2bc` backfills `role='head'` for existing snapshots, which
  is what they all are. Snapshots duplicated by the pre-constraint resume path
  are renamed `stale-<id>` rather than deleted: they are evidence, and the row
  kept as `head` is the one the old reader would have returned.
- Bumping `GRAPH_PIPELINE_VERSION` when graph construction changes is now a
  release obligation. Forgetting it serves graphs built by older code under a
  key that claims otherwise — the failure mode the key exists to prevent.
