# ADR-0005: Agent engine adapter — Claude Agent SDK on subscription auth

- Status: Accepted
- Date: 2026-08-05
- Supersedes: the initial OpenHands selection recorded during planning

## Context

The pipeline needs an execution engine for agent tasks (reviewers, validator,
intent reconstruction). OpenHands was selected first. Infrastructure research
then established two facts that changed the decision:

1. **Anthropic banned subscription OAuth in third-party tools (February 2026).**
   Only Claude Code and claude.ai may use Free/Pro/Max subscription auth, so
   OpenHands would require a separate pay-per-token API key.
2. The user explicitly wants the platform to run on their existing account
   rather than a new metered credential.

OpenHands additionally does not run natively on Windows (its CLI imports
Unix-only `fcntl`), so it would also require Docker Desktop + WSL2 on a Windows
10 Home machine at the minimum supported build.

## Decision

`AgentEngine` is a Protocol: `run(task, instructions) -> AgentResult`. The
pipeline imports the protocol, never a concrete engine.

- **`ClaudeAgentEngine` (primary)** — `claude-agent-sdk` driving the installed
  `claude` CLI on the user's subscription. Native Windows, no API key, no
  per-token billing. Budgets are therefore enforced in **tokens**, with
  `cost_usd` recorded when the SDK reports it and null otherwise.
- **`ReplayEngine`** — cassettes keyed by skill id + version + input hash. All
  CI and pipeline tests replay; re-recording is an explicit, reviewed act, and a
  skill version bump invalidates its cassettes on purpose.
- **`OpenHandsEngine` (future, optional)** — same protocol, Docker-sandboxed;
  addable unchanged if a metered key ever becomes available or untrusted-repo
  sandboxing demands container isolation.

## Enforcement (learned the hard way)

Permissions are enforced by a **PreToolUse hook**, not the `can_use_tool`
callback. The SDK auto-approves any tool listed in `allowed_tools` *before*
`can_use_tool` runs, which silently made the Bash command allowlist decorative;
the live validation suite surfaced the SDK's shadowing warning. Hooks observe
every tool call. Denials are returned in `AgentResult.permission_denials` (part
of the agent-result contract) so they are auditable evidence, not just log noise.

Other structural bounds: `cwd` is the pinned read-only checkout; network tools
are in `disallowed_tools` *and* denied by the hook; `setting_sources=[]` so user
and project settings cannot inject instructions; `max_turns` plus a wall-clock
timeout bound every task; output must validate against the task's JSON Schema or
the result is `schema_invalid`.

Amendment (X phase): the "one bounded repair turn" this ADR originally described
was never implemented inside the engine. It now exists at dispatch level —
`dispatch_with_retry` retries `schema_invalid` (quoting the validation errors
back) and `timeout` exactly once, on live engines only, with each attempt
recorded as its own invocation row. Replay never retries: a stale cassette must
fail loudly (ADR-0012).

## Consequences

- The whole pipeline is testable offline via replay; only the M8 adapter suite
  and a nightly canary consume real quota.
- Untrusted third-party repositories remain out of scope until the optional
  Docker sandbox phase lands: extraction runs `build.rs`/proc-macros, and the
  host-running SDK provides no container boundary. Analyzable origins are
  restricted to own/fixture/scratch repositories.
