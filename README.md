# CodeAtlas

Evidence-driven code review and project-visualization platform. Given a repository at a
pinned revision (or a GitHub pull request), a completed run produces:

- a **deterministic project graph** (packages, symbols, references, dependencies) with an
  extractor receipt for every fact — and for a pull request, **one graph per revision**, so
  the run can describe what the code did before as well as after;
- a **model-free before/after of a change**: the structural delta (symbols and edges added,
  removed, moved, touched) plus the public-API delta from `cargo public-api` and the
  breaking-change severity from `cargo-semver-checks`;
- a **narrative explanation of the change** — before, after, structure, impact, risks —
  in which every claim cites a pinned line, a graph edge, an API item or an impact entry,
  and any claim whose citation does not resolve is deleted rather than softened;
- **validated review findings** (correctness, security, architecture) — every finding is
  adversarially validated and only publication-eligible with deterministic evidence;
- **Structurizr C4** architecture views, **Mermaid** protocol/sequence/state diagrams, and a
  **Cytoscape.js** dependency graph;
- **ADR links and drift detection** against accepted architecture decisions;
- a **read-only dashboard** where every claim drills down to pinned source;
- **manual human approval gating every external write** (PR comments, ADR changes, fixes).

## Pipeline

```
source_lock -> extract -> build_graph -> base_revision -> graph_diff -> api_change
            -> change_impact -> export_cytoscape -> review -> finalize
```

`source_lock` pins the revisions under analysis and, in pull-request mode, resolves the base
and derives the changed-path and added-line sets from the mirror. `base_revision` analyzes
the revision the change is measured against; it is a no-op for a whole-repository run, and
reuses an already-analyzed base when the extractor toolchain that produced it still matches
(ADR-0013). Each graph is stored as a snapshot with an explicit `role` of `base` or `head` —
"the run's graph" is not a well-formed question once a run holds two.

`graph_diff` compares the two graphs: which symbols and which *relationships* the change
added, removed or moved. That is the signal a text diff cannot give — *storage now imports
api* appears in the diff of neither file. Comparison runs on identities with the package
version stripped out, because a symbol id embeds it and a release bump would otherwise read
as the whole crate being rewritten; the version change is reported as its own fact.

`api_change` answers "what did this crate expose before, and what does it expose now"
without a model: `cargo public-api` renders the public surface of each revision and the
difference is arithmetic, then `cargo-semver-checks` classifies the severity. A package that
could not be measured on both sides is listed in `skipped` with the reason, never reported as
unchanged — "no API change" and "nothing was measured" must not look alike.

`change_impact` walks the dependency edges backwards from the symbols the change modified or
removed. One hop by default and two at the most: static change-impact precision is around
38–50%, so an unbounded closure reaches nearly everything while being right about nearly
none of it. Results are ranked (public API, crate-crossing, internal, test-only), the surplus
past the report limit is counted rather than dropped, and the precision caveat is a field of
the artifact so nothing can render the list without it.

The `review` stage then explains the change before reviewing it, because a reviewer needs to
know what a change does before being told what might be wrong with it. The explanation is
the one artifact a model writes, and what makes it usable is not the model's care but the
validator behind it: each claim must cite something this run measured, and a claim whose
citations do not resolve is removed and listed in `droppedClaims`. A softened false claim is
still a false claim, and it keeps the authority of appearing in the report.

## Design principle

Normalized, schema-validated evidence artifacts are the interfaces between pipeline stages:
facts (extractor receipts) → agent inferences (candidate findings) → validated findings →
presentation artifacts. No stage may launder inference into fact — the JSON Schemas in
`schemas/` are the source of truth for every contract.

## Repository layout

| Path | Purpose |
|---|---|
| `schemas/` | Versioned JSON Schemas (Draft 2020-12) — canonical contracts |
| `src/codeatlas/` | Python backend (extractors, pipeline, validation, API, CLI) |
| `frontend/` | React read-only dashboard (Vite + TypeScript) |
| `.agents/skills/` | Trusted, pinned skill registry + skill definitions |
| `docs/adr/` | Architecture decision records (MADR) |
| `docs/runbooks/` | Setup, operations, rollback |
| `fixtures/` | Deliberately-flawed and clean Rust fixture crates for evaluation |
| `tests/` | unit / integration / e2e / security / regression + cassettes + golden files |
| `scripts/` | `verify_env.py` tool-matrix probe, live-integration validators, dev helpers |
| `infra/` | Install/validate scripts, receipts, DB init |

## Setup

```powershell
uv sync                    # install Python deps into .venv
uv run poe verify-env      # print the tool matrix (what's installed vs required per milestone)
uv run poe check           # ruff + mypy --strict + pytest
```

Toolchain beyond Python is installed and validated per milestone — see
`docs/runbooks/setup.md` and the plan in the repository history. Runtime data lives in
`review-artifacts/` and `var/` (both gitignored, never committed).

## Test tiers

Default `pytest` runs unit tests. Markers gate everything needing external capability:
`subproc` (git/cargo/rust-analyzer), `pg` (local PostgreSQL), `agent_live` (logged-in
claude CLI), `network` (GitHub), `e2e_ui` (Playwright).

External integrations are also validated directly against the live service before anything
depends on them, since a fixture cannot prove that authentication, ref fetching or caching
work against the real thing:

```powershell
uv run python scripts/validate_github.py             # GitHub read paths and refusals
uv run python scripts/validate_two_revisions.py owner/repo N   # both revisions, live PR
```
