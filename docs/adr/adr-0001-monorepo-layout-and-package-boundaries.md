# ADR-0001: Monorepo layout and package boundaries

- Status: Accepted
- Date: 2026-08-05
- Deciders: CodeAtlas maintainers

## Context and problem statement

CodeAtlas spans a Python analysis backend, a TypeScript dashboard, versioned JSON Schema
contracts, agent skill definitions, fixture repositories, and operational scripts. These parts
must evolve together (a schema change touches backend, frontend, and skills in one change),
be reviewable in one place, and stay reproducible from a single lockfile set.

## Decision

One monorepo at the repository root:

- `src/codeatlas/` — a single installable Python package (uv-managed, hatchling build), with
  internal module boundaries (`core`, `models`, `db`, `vcs`, `extractors`, `graph`, `agents`,
  `pipeline`, `review`, `validation`, `verify`, `artifacts`, `adr`, `api`, `cli`).
- `frontend/` — Vite + React + TypeScript app with its own `package.json`; talks to the backend
  only through the generated OpenAPI client.
- `schemas/` — versioned JSON Schemas (Draft 2020-12). **These are the canonical contracts**;
  Python/TypeScript types must conform to them, never the reverse.
- `.agents/skills/` — trusted skill registry (`registry.yaml`) and skill definitions,
  content-hash pinned.
- `docs/adr/`, `docs/runbooks/`, `docs/architecture/` — decisions, operations, dogfooded
  architecture model.
- `fixtures/`, `tests/`, `scripts/`, `infra/` — evaluation fixtures, test suites, dev/ops
  scripts, install + receipt infrastructure.
- Runtime data (`review-artifacts/`, `var/`) is machine-local and gitignored.

## Considered alternatives

- **Multiple repositories** (backend / frontend / schemas): rejected — cross-cutting contract
  changes would need coordinated multi-repo releases; overkill for a single-team product.
- **Python namespace packages per subsystem**: rejected — no independent release cadence
  exists; module boundaries inside one package with import-linting suffice.

## Consequences

- One `uv.lock` + one `package-lock.json` pin the whole build.
- Contract drift is caught by an in-repo test (schema ↔ Pydantic model round-trip).
- CI and the quality gates (`ruff`, `mypy --strict`, `pytest`) run from the repository root.
