# CodeAtlas — conventions for agent sessions

## Commands

- `uv run poe check` — ruff + mypy --strict + pytest (default tiers). Run before every commit.
- `uv run poe verify-env` — tool matrix: what is installed vs required per milestone.
- `uv run pytest -m subproc` / `-m pg` / `-m agent_live` / `-m network` — capability-gated tiers.
- `uv run poe ui` — dashboard: `tsc -b` + vitest. `poe ui-e2e` for Playwright.
- `codeatlas serve --workdir var --port N` + `CODEATLAS_API=http://127.0.0.1:N npm run preview`
  — the dashboard against real data. `CODEATLAS_RUN=<id> npm run e2e` then exercises
  `e2e/live.spec.ts`, the only suite that is not route-mocked.

## Hard rules

- **Schemas are the source of truth.** Pydantic models in `src/codeatlas/models/` must round-trip
  with `schemas/*.json`; the drift test enforces it. Change the JSON Schema first, then the model.
- **Evidence discipline.** An edge/claim labeled compiler-, language-server- or schema-derived must
  never originate from model inference. Every extractor invocation emits a receipt.
- **Determinism.** Canonical JSON = UTF-8, sorted keys, LF, forward-slash repo-relative paths,
  no timestamps in hashed payloads. Double runs at the same revision must hash identically.
- **No silent failure.** Nodes return typed errors; a degraded run says so in its report.
- **All external writes are approval-gated.** Publication code paths must re-check the approval
  row, config flag, and `CODEATLAS_KILL_SWITCH` — never rely on control flow alone.
- **TDD.** Failing test first, minimal implementation, green, refactor. No placeholders.

## Style

- Python 3.12, `ruff` + `mypy --strict` clean; typed interfaces everywhere (Pydantic v2 at
  boundaries, `Protocol` for adapters).
- Windows-first: use `pathlib`, never assume `/tmp`, never shell=True with untrusted input;
  repo-relative paths are always forward-slash.
- ADRs in `docs/adr/` (MADR format) for significant decisions; update the index.
