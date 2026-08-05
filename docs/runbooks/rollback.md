# Rollback and recovery runbook

Ordered from cheapest to most invasive. Prefer the smallest action that solves
the problem, and record what you did — this file is the audit trail's companion.

## 1. Stop all publication immediately (seconds)

```powershell
$env:CODEATLAS_KILL_SWITCH = "1"          # this shell
setx CODEATLAS_KILL_SWITCH 1              # persistent, new shells
```

`publish_approved` checks this on **every** call, after approval and after the
config flag, so an already-approved payload still will not post. Nothing else is
affected: analysis, validation and reporting continue.

Clear it with `Remove-Item Env:\CODEATLAS_KILL_SWITCH` / `setx CODEATLAS_KILL_SWITCH ""`.

## 2. Retract a published review (minutes)

CodeAtlas never deletes anything on GitHub. Find what was posted and act there:

```powershell
uv run python -c "from sqlalchemy.orm import Session; from codeatlas.db.session import app_engine; from codeatlas.db.tables import PublicationRow; from sqlalchemy import select; s=Session(app_engine()); [print(p.published_at, p.status, p.external_ref) for p in s.scalars(select(PublicationRow).order_by(PublicationRow.id.desc()).limit(10))]"
```

Every attempt is recorded, including failures — a failed publication is
committed before the error propagates, so the table shows attempts, not just
successes.

## 3. Reject a pending approval (seconds)

```powershell
uv run codeatlas reject <approval-id> --by "<you>" --note "why"
```

A decided approval cannot be flipped; a rejected payload can never publish.

## 4. Roll back a schema migration (minutes)

Migrations are tested down and up in CI, so downgrade is a supported path:

```powershell
uv run alembic downgrade -1        # one step
uv run alembic downgrade base      # everything (destroys all data)
uv run alembic current             # confirm where you are
```

Take a backup first (step 5) — `downgrade` drops tables.

## 5. Restore the database from backup

Backups run nightly at 02:30 via the scheduled task
`CodeAtlas nightly database backup`, and every dump is verified with
`pg_restore --list` at creation time; an unreadable dump is deleted rather than
kept as false comfort.

```powershell
# list what is available
Get-ChildItem C:\CodeAtlas\var\backups -Filter *.dump | Sort-Object LastWriteTime -Descending

# verify the dump you intend to use, before dropping anything
& "$env:ProgramFiles\PostgreSQL\17\bin\pg_restore.exe" --list <dump>

# restore into a fresh database, then switch over — never restore over a live one
$env:PGPASSWORD = (uv run python -c "import keyring; print(keyring.get_password('codeatlas/db','postgres_super'))")
& "$env:ProgramFiles\PostgreSQL\17\bin\createdb.exe" -U postgres -h 127.0.0.1 codeatlas_restored
& "$env:ProgramFiles\PostgreSQL\17\bin\pg_restore.exe" -U postgres -h 127.0.0.1 -d codeatlas_restored <dump>
```

Run the backup manually any time:
`powershell -File infra\backup\backup_database.ps1`

## 6. What is NOT lost in any of the above

Artifacts are content-addressed and immutable under `review-artifacts/objects/`
(or the configured workdir). Nothing overwrites an object, so graphs, payloads,
transcripts and manifests survive a database rollback. A restored database plus
the object store reconstructs full run history.

## 7. Reproduce a past run

```powershell
uv run codeatlas compare <run-a> <run-b>
```

Exits 0 when the two runs agree on graph hash, toolchain, finding set and
publishable set; nonzero with a specific list of differences otherwise. Token
usage differences are reported as notes and do not count against
reproducibility.
