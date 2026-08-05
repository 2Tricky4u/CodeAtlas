# ADR-0008: Trusted skill registry with pinned content hashes

- Status: Accepted
- Date: 2026-08-05

## Context

Agent skills are executable supply-chain dependencies even though their entry
point is Markdown: they steer an agent that can read a repository and run
commands. Published research (and the source research report for this project)
documents skill metadata and instructions being used to manipulate agent
behavior. A skill file edited after review is indistinguishable from a reviewed
one unless something checks.

## Decision

`.agents/skills/registry.yaml` pins every skill by:

- `content_sha256` — hash over **all** files in the skill directory (path +
  content), not just `SKILL.md`, so reference files and policies are covered;
- `version` — bumped on any change; cassette keys include it, so replayed
  results cannot outlive the instructions that produced them;
- `permissions` — declared allowed commands, network (always false), write paths;
- `trust` — `trusted` | `experimental` | `revoked`;
- `reviewed_by` / `reviewed_at` — provenance of the human review.

The loader **fails closed**: a hash mismatch, a missing directory, or a
non-`trusted` status raises `RegistryError` and the run does not start.
`allow_untrusted=True` exists for local development only and is never used by
the pipeline. The registry file's own hash goes into the run manifest, so a run
records exactly which instruction set produced its findings.

## Consequences

- Editing a skill without regenerating its hash breaks the build immediately —
  the intended behavior for an unreviewed instruction change.
- Skill permissions are data, consumed by the engine's enforcement hook; a skill
  cannot widen its own capabilities from inside its prompt.
