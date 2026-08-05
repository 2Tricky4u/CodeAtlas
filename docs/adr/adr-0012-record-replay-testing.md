# ADR-0012: Record/replay testing of agent-dependent stages

- Status: Accepted
- Date: 2026-08-05

## Context

Every agent-dependent stage (intent reconstruction, specialist review, finding
validation) produces different text on every run. Testing such stages against a
live model would make the suite slow, non-deterministic, quota-consuming, and
unable to run in CI — while testing them not at all would leave the majority of
the pipeline unverified.

## Decision

Three complementary layers:

1. **Contract tests.** Agent output is validated against a versioned JSON Schema
   at the adapter boundary. An engine can only return data the contract permits;
   anything else is a typed `schema_invalid` result, not a crash.
2. **Record/replay.** `ReplayEngine` serves recorded `AgentResult`s from
   `tests/cassettes/`, keyed by `(skill_id, skill_version, skill_content_sha256,
   output_schema_id, inputs, revision_sha)`. All pipeline tests replay, so they
   are deterministic, offline, and free. Recording is an explicit act
   (`scripts/record_cassette.py`) that consumes quota and is reviewed like code.
3. **Golden files** for the deterministic transforms downstream of inference.

Because the cassette key includes the skill's version *and* content hash, editing
a skill invalidates its cassettes rather than silently replaying results the new
instructions would never produce. Fixture repositories are built with fixed
identity and timestamps so their SHAs — part of the key — are a pure function of
content.

## Consequences

- A skill change is a two-step, visible process: edit + version bump, then
  re-record. Reviewers see both.
- Cassettes freeze one model's behavior; they verify wiring, contracts and
  downstream logic, **not** model quality. Quality is measured separately
  against the fixture manifest (recall/precision) and by the live suites.
- A missing cassette fails loudly with the skill and version named, never by
  silently falling back to a live call.
