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
- **bounded graph views** — a package-level overview, per-package levelized module views
  drawing only the cycles, and a dependency matrix for the whole project — where a view
  that fails its readability checks is refused rather than rendered as a hairball;
- a **read-only dashboard** where every claim drills down to pinned source;
- **manual human approval gating every external write** (PR comments, ADR changes, fixes).

## Pipeline

```
source_lock -> extract -> build_graph -> base_revision -> api_change -> graph_diff
            -> change_impact -> project_overview -> architecture -> narrate
            -> export_cytoscape -> review -> finalize
```

(`api_change` runs before `graph_diff` on purpose: the diff's interface labels
need to know which symbols the public-API delta named, and "changed but not
exported" is only expressible once that delta exists. `project_overview`,
`architecture` and `narrate` are the deterministic half of the comprehension
features — the overview, map, architecture, decisions, protocol and flows tabs
all come from them.)

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
uv run poe check-all       # the release gate: both halves, Playwright e2e included
```

Toolchain beyond Python is installed and validated per milestone — see
`docs/runbooks/setup.md` and the plan in the repository history. Runtime data lives in
`review-artifacts/` and `var/` (both gitignored, never committed).

## Using it

```powershell
# Analyze a repository (local path or clone URL) at a pinned revision.
uv run codeatlas run --repo <path-or-url> --repository-id owner/name [--ref SHA]
#   --narrate        explain what the project is (agent quota; --no-review stays free of reviewers)
#   --review         run the reviewers too
#   --replay         answer from recorded cassettes instead of the live engine
#   --max-tokens N   run-wide agent token budget

# Review a GitHub pull request in shadow mode — analyzes both revisions, posts NOTHING.
uv run codeatlas review-pr owner/repo N

# Serve the dashboard's API (loopback by default; --ask enables POST /ask, ADR-0014).
uv run codeatlas serve --workdir var --port 8137 --ask
# then, in frontend/:  $env:CODEATLAS_API="http://127.0.0.1:8137"; npm run preview

# Run lifecycle and reproducibility.
uv run codeatlas status <run-id>
uv run codeatlas resume <run-id>
uv run codeatlas compare <run-id> <run-id>     # exits nonzero if not reproducible

# Publication — every external write is human-gated (ADR-0011/0015).
uv run codeatlas request-approval <run-id>
uv run codeatlas show-approval <approval-id>   # read the exact payload first
uv run codeatlas approve <approval-id> --by "<you>" [--note "..."] [--publish]
uv run codeatlas publish <approval-id>         # the second half of approve-now-publish-later
uv run codeatlas reject <approval-id> --by "<you>"
```

Publishing additionally requires `CODEATLAS_PUBLISH_ENABLED=1` in the environment
(default off — ADR-0015) and an unset `CODEATLAS_KILL_SWITCH`. Database access is
keyring-backed with `CODEATLAS_DB_URL` / `CODEATLAS_DB_HOST` / `CODEATLAS_DB_PORT`
(and `CODEATLAS_TEST_DB_URL` for the test database) as overrides.

## Test tiers

Default `pytest` runs unit tests. Markers gate everything needing external capability:
`subproc` (git/cargo/rust-analyzer), `pg` (local PostgreSQL), `agent_live` (logged-in
claude CLI). The Playwright suites run via `poe ui-e2e`; the live suite additionally
needs a served run (`CODEATLAS_RUN=<id> npm run e2e`).

External integrations are also validated directly against the live service before anything
depends on them, since a fixture cannot prove that authentication, ref fetching or caching
work against the real thing:

```powershell
uv run python scripts/validate_github.py             # GitHub read paths and refusals
uv run python scripts/validate_two_revisions.py owner/repo N   # both revisions, live PR
uv run python scripts/check_real_project.py --repo <url>       # every analysis, real crate
```

The last one is the important one for anything graph-shaped. The fixture crate has five
files; a levelization that collapses, an impact set that reaches everything, or a view that
is a hairball only show up at real size. It separates what it can verify itself from the
judgements only a reader of that codebase can make, and `scripts/show_overview.py` and
`scripts/show_views.py` print the results for a human to look at.
