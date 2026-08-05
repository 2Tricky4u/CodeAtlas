# ADR-0001: Strict downward layering

- Status: Accepted
- Date: 2026-01-15

## Decision

Dependencies flow strictly downward: `api` may use `cache`, `cache` may use
`storage`, and `storage` depends on nothing inside this crate. Upward imports
(e.g. `storage` importing `api`) are prohibited.

## Consequences

The storage layer stays reusable and testable without wire-protocol types.
Violations are architectural drift and must be flagged in review.
