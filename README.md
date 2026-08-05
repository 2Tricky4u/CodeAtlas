# CodeAtlas

Evidence-driven code review and project-visualization platform. Given a repository at a
pinned revision (or a GitHub pull request), a completed run produces:

- a **deterministic project graph** (packages, symbols, references, dependencies) with an
  extractor receipt for every fact;
- **validated review findings** (correctness, security, architecture) — every finding is
  adversarially validated and only publication-eligible with deterministic evidence;
- **Structurizr C4** architecture views, **Mermaid** protocol/sequence/state diagrams, and a
  **Cytoscape.js** dependency graph;
- **ADR links and drift detection** against accepted architecture decisions;
- a **read-only dashboard** where every claim drills down to pinned source;
- **manual human approval gating every external write** (PR comments, ADR changes, fixes).

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
| `scripts/` | `verify_env.py` tool-matrix probe, dev helpers |
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
