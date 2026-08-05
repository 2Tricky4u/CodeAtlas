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
| M13 | Structurizr CLI (pinned zip; Java 17 already present), mmdc | validate/export; render + must-fail case |
| M17 | LLVM/clangd + CMake + Ninja | compile_commands generation; clangd --check |

## Secrets

Windows Credential Manager via `keyring` (`codeatlas/github`, `codeatlas/db`). `.env` holds
non-secrets only. Never commit credentials; gitleaks blocks staged secrets at commit time.
