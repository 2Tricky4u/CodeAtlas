# ADR-0015: Publication is enabled by environment, default off

- Status: Accepted
- Date: 2026-08-07
- Amends: ADR-0011

## Context

The publication gate has always re-checked three things at post time: the
approval row, a configuration flag, and `CODEATLAS_KILL_SWITCH` — "never rely
on control flow alone". The gate function takes `enabled: bool` and refuses
when it is false, and the security suite exercises that refusal thoroughly.

A full-project test audit found the hole: the **only production call site**
(`codeatlas approve --publish`) passed `enabled=True` as a literal. Every
gate-level test supplied `enabled=` by hand, so the suite proved the gate
*could* refuse while the shipped path could not be refused by configuration.
The config flag existed as a parameter, not as configuration.

## Decision

The flag becomes real:

- **`CODEATLAS_PUBLISH_ENABLED`** is the configuration gate. It is **off by
  default** and enables publication only when set to the literal `"1"` —
  fail closed and unambiguous (`"true"` or `"yes"` silently enabling
  publication is how a copy-pasted environment block posts to GitHub by
  accident).
- The CLI resolves it via `publication_enabled()` in `publication/gate.py`,
  next to `KILL_SWITCH_ENV`; no caller passes a literal.
- `codeatlas publish <approval-id>` exists as a command — the two-step flow
  (`approve` now, `publish` later) that the CLI's own hint always advertised.
- Order inside the gate: kill switch first, before even the idempotent
  already-published return; then exactly-once (under a row lock on the
  approval, with a partial unique index as the database-level backstop); then
  decision, configuration, secret scan.

Publishing therefore requires, simultaneously: an approved row, the
environment saying `CODEATLAS_PUBLISH_ENABLED=1`, an unset kill switch, a
clean secret scan, and no prior publication — each re-checked at post time.

## Consequences

- A machine that has never set the variable cannot post to GitHub, whatever
  the CLI is asked to do. Enabling publication is now an explicit act on the
  machine, symmetrical with the kill switch being an explicit stop.
- The live posting test (M12's one outstanding item) must set the variable —
  which is the point: the test then exercises the same gate production uses.
  It exists as `tests/integration/test_publication_live.py` (`github_live`
  marker) and **first passed live on 2026-08-08**: one review posted through
  the full gate, read back with the provenance marker at the diff-anchored
  line, and published twice to prove exactly-once against the real API.
- CLI-level tests drive `approve --publish` and `publish` with a recording
  writer, so the shipped path — not just the gate function — is pinned.

Amendment (Y phase): `approve` additionally requires `--payload` carrying the
first 12 characters of the payload sha — a value that only exists in
`show-approval` output or the dashboard, so approving proves the payload was
at least fetched. The gate also verifies the AI-provenance marker the payload
builder always adds; a markerless (hand-built or tampered) payload is blocked
after the secret scan. Both checks are verifications of the approved bytes,
never edits — what was approved is byte-for-byte what posts.
