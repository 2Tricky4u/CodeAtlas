# Setup runbook

Reproducible setup for a fresh Windows 10/11 machine. Every install is scripted; every
integration has an independent smoke test that must pass before the pipeline may rely on it.
Install receipts land in `infra/receipts/` (committed) — tool, version, date, source.

## Phase 0 — bootstrap (required for everything)

```powershell
git config core.longpaths true            # set per-repo by scripts/dev.ps1
winget install --exact --id astral-sh.uv
winget install --exact --id Gitleaks.Gitleaks
uv sync                                   # Python deps into .venv from uv.lock
uv run pre-commit install                 # ruff + gitleaks commit gates
uv run poe check                          # ruff + mypy --strict + pytest must be green
uv run poe verify-env                     # tool matrix; --through M<N> gates milestones
```

NTFS long paths: `git config core.longpaths true` is set per-repo. The system-wide
`LongPathsEnabled` registry value requires elevation; enable it from an admin shell if deep
`target/` trees ever hit 260-char limits:

```powershell
Set-ItemProperty HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem -Name LongPathsEnabled -Value 1
```

## Later phases (installed at their milestone, each with its own smoke script)

| Milestone | Install | Smoke test |
|---|---|---|
| M4 | `rustup component add rust-analyzer` | `rust-analyzer --version`; SCIP double-run hash equality |
| M5 | PostgreSQL 17 (winget EDB, unattended `--override`) | service running; scram loopback-only; Alembic up/down |
| M8 | `claude-agent-sdk` (pinned, via uv) | echo-skill task: schema-valid output, permission denial, timeout |
| M12 | gh CLI + fine-grained PAT (Credential Manager) | rate limit, PR fetch by SHA, reproducible checkout |
| M13 | Structurizr CLI (pinned zip in `infra/tools/structurizr`; Java 17 already present), `npm i -g @mermaid-js/mermaid-cli` | validate/export; render + must-fail case |
| M17 | LLVM/clangd + CMake + Ninja | compile_commands generation; clangd --check |

## Diagram toolchain notes (learned the hard way)

- **Structurizr rejects a UTF-8 BOM** — it fails with `Unexpected tokens (expected:
  workspace) at line 1`. Write DSL with Python's `encoding="utf-8"` (no BOM);
  PowerShell's `-Encoding utf8` adds one. `write_dsl()` handles this, and a test
  proves a BOM-prefixed workspace is rejected.
- **Structurizr blocks must be multi-line.** `properties { "k" "v" }` and
  `systemContext sys { include * }` written on one line are parse errors.
- **Identifiers must be unique across scopes**: a container keyed the same as its
  software system is a parse error, so the generator namespaces system keys.
- **The Structurizr CLI cannot rasterize.** It validates and exports
  (mermaid/plantuml/dot/json); SVG comes from `mmdc`.
- **Kroki (remote rendering) is deliberately not implemented.** Diagram source
  carries repository structure; sending it to a third party is a data-governance
  decision, not a convenience.

## Secrets

Windows Credential Manager via `keyring` (`codeatlas/github`, `codeatlas/db`). `.env` holds
non-secrets only. Never commit credentials; gitleaks blocks staged secrets at commit time.
