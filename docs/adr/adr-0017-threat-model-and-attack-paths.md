# ADR-0017: Repository threat model, cached and feeding the reviewers

- Status: Accepted
- Date: 2026-08-08
- Relates to: ADR-0007 (determinism), ADR-0012 (record/replay), ADR-0013 (cross-run reuse), ADR-0016 (finding memory)

## Context

The reviewers were aimed by nothing. Every file in scope was reviewed with equal
weight, and severity was calibrated to a generic scale — "high" meant the same
in a formatting library and a network-facing store. The skills research
converged on the missing primitive from two directions: a repo-wide threat model
(trust boundaries, assets, an attacker with explicit non-capabilities, abuse
paths) that a review reads *before* it starts, and per-finding attack-path
records that turn a validated security verdict into a receipt an engineer can
act on. Both are expensive to produce and change slowly, which is the whole
argument for building them once and reusing them.

## Decision

**A `threat-model.v1` artifact** describes the repository: components,
boundaries with what crosses them and what is guaranteed, assets with per-
property CIA, an attacker whose `nonCapabilities` are as required as their
capabilities, `TM-nnn` abuse paths, a per-repo criticality calibration, and 2–30
focus paths. A repository with no meaningful attack surface returns `threats: []`
with a written reason — the protocol model's honest-refusal design (ADR-0002's
"a degraded run says so"), because inventing a boundary to fill the form is the
exact confident-but-wrong artifact this tool exists to avoid. Threats are
hypotheses and carry no evidence; control claims are checked, and a control whose
evidence does not resolve keeps its text but is marked unverified.

**It is cached per repository, and the cache is replaceable.** This is the
deliberate opposite of `graph_cache` (ADR-0013). A graph is a deterministic
function of its named producers, so same-key rows are append-only and never
overwritten. A threat model is the *current understanding* of what a system is;
a refresh legitimately replaces it. `threat_model_cache` therefore holds one row
per repository, and `--refresh-threat-model` UPDATEs it, logging the superseded
sha in a `threat_model_refreshed` run event. Honesty comes from the audit trail,
not from immutability. Reuse adopts the stored artifact into the consuming run
(the first genuine cross-run use of `adopt_artifact`) and records a
`threat_model_cache_hit` event naming the run that actually paid for it; the
artifact states the revision it was modeled at, so a consumer at a later
revision knows how stale its picture is.

**The model aims the reviewers.** The stage runs first inside the review node,
because its focus paths are a reviewer input — computed after the reviewers, it
would aim nobody. When the model found threats, the reviewer bundle gains a
`threatFocus` key (focus paths, the attacker's non-capabilities, the criticality
calibration); when it found none, the key is absent, so the bundle — and its
replay cassettes — is byte-identical to a pre-threat-model run. The reviewers
weight the focus paths and respect the calibration: a threat the attacker model
says cannot happen is not high.

**Validated security findings — and only those — get an attack-path receipt.**
An `attack-path.v1` (dataflow, reachability, impact and likelihood each with a
required why, and `limitations` so the analysis admits its gaps) is produced by a
separate skill after validation and rides in the finding's `validation` JSONB
bag, which is not schema-gated (the ADR-0016 suppression-record precedent). The
scope is narrow on purpose: a receipt is one agent call and is only meaningful
where the actor is an attacker. Rejected candidates getting receipts too is
deferred as a cost decision.

**Everything fails open.** A modeler that does not complete leaves a note and the
reviewers run unaimed, exactly as before this stage existed; an attack-path
analysis that fails leaves the finding's verdict untouched. The receipt and the
aim enrich; they never gate.

## Consequences

- The second run on a repository reviews for free what the first run paid to
  model, and the reviewers spend their attention where an attack is most likely
  to land. The cost is one model build per fresh repository (~$1–2 on a small
  crate), amortized across every later review.
- A new failure surface, handled: a threat model reused at a later revision can
  point its focus paths at code that moved. Validation drops focus paths that no
  longer name a file at the run's revision, but a *stale* model reused wholesale
  is only as good as its age — which is why the artifact and the tab both state
  the revision it was modeled at, and `--refresh-threat-model` exists.
- Two new skills need live cassette recordings; the reviewer bundle change forces
  a consolidated re-record of the reviewers and the validator (ADR-0012). The
  recall gate was re-validated after: threat focus must sharpen the reviewers
  without making them aggressive, and the decoy suite still draws zero findings.
- The attacker's non-capabilities are now load-bearing for severity, both in the
  model (a threat the attacker cannot mount is not high) and in the reviewers
  (which are told the same). An empty or dishonest non-capability list would
  inflate severity across the whole review; the skill prompt treats "the attacker
  is not creative" as a non-answer.
