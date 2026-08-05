# kvstore specification

## Purpose

A small bounded key-value store with an in-memory cache in front of a
file-backed store, driven by a line protocol over the wire.

## Requirements

1. **Bounded memory.** The cache holds at most `max_entries` entries. When a
   write would exceed that bound, the oldest entries are evicted — and only as
   many as necessary.
2. **Untrusted input.** Keys and requests arrive from the network and are
   untrusted. A malformed request must produce an error response; it must never
   terminate the process.
3. **Store confinement.** A key must only ever address a file inside the store
   root. Keys that attempt to escape the root are rejected.
4. **Concurrent counters.** Counter reads must remain correct when other threads
   add or remove counters concurrently.

## Non-goals

- Replication, clustering, and durability guarantees beyond a single file write.
- Performance tuning; correctness first.

## Open questions

- Should eviction order be strictly FIFO, or should reads promote entries?
