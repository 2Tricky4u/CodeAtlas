# protocol-modeler

Describe the protocol this project speaks, if it speaks one: who the
participants are, what messages pass between them, what states the exchange
moves through, and what happens when something times out.

The sequence and state diagrams a reader eventually sees are *derived views of
your model*, never drawn separately. Get the model right and the diagrams follow;
invent something in the model and two confident-looking pictures inherit it.

## Read this first

**Most projects have no protocol, and the right answer for them is `null`.**

A protocol here means an exchange between parties over time: a wire format, an
RPC surface, a state machine driving a session, a message queue with producers
and consumers. It is *not*:

- a library whose functions call each other — that is the dependency graph, and
  the map already shows it;
- a batch program that reads input and writes output — `grep`, a compiler, a
  linter, a build tool;
- a CLI that parses arguments and does one thing;
- an HTTP client that calls somebody else's API, unless this project defines
  that API.

If none of the above applies, return `{"schemaVersion": "1.0.0", "protocol":
null, "notes": ["…why not…"]}` and stop. That is a complete, correct answer, and
it is the answer most of the time. A sequence diagram forced onto a batch
program is the exact failure this whole tool exists to avoid: something that
looks authoritative and describes nothing.

## Inputs

- **the project overview** (`project-overview.v1`): packages, modules, levels,
  cycles, entry points, and a ranked "start here" list.

You are in a read-only checkout at that revision. The protocol, if there is one,
is in the source — the overview will not show it to you. Start from the entry
points, follow what they read and write.

## Method

1. Read the entry points. Ask what crosses a boundary: a socket, a pipe, a file
   format other programs write, a queue, an FFI surface.
2. If nothing does, return `null` with a note saying what the project does
   instead. Stop here.
3. Otherwise name the **participants** — the parties, not the modules. "client"
   and "server", not `api.rs` and `main.rs`. Each carries the source range where
   its side of the exchange is implemented.
4. Name the **messages**: what is sent, by whom, to whom, and where in the source
   it is produced or handled.
5. Name the **states** the exchange moves through, and any **timeouts** that
   move it between them. Omit both if the exchange is stateless — most
   request/response protocols are.
6. Record the protocol's own `evidence`: the module that owns the wire format.

## Hard rules

- **Every participant and every message carries evidence.** A path that exists
  at this revision, optionally a line range, optionally a graph node id.
- **Evidence is checked afterwards, and elements that fail are deleted.** Not
  softened — deleted, and listed as dropped. A message whose participant was
  dropped goes with it, because an arrow leaving a box that was not drawn is
  worse than a missing arrow.
- **Do not invent participants to make a diagram look complete.** Two boxes and
  one arrow is a fine protocol model if that is what the code does.
- **Do not model a protocol the project merely *uses*.** If it makes HTTP
  requests to a third-party API, that API is not this project's protocol.
- **`transport` and `framing` must be observable in the source** — "tcp",
  "stdin/stdout", "unix socket"; "line-delimited", "length-prefixed", "json".
  If you cannot see it, you are guessing, and this is not a guessing task.
- **Do not invent line numbers.** A path alone is a valid citation.
- No network access.

## Output

Exactly one fenced ```json block validating against `protocol-model.v1`.

A project with no protocol — the common case:

```json
{
  "schemaVersion": "1.0.0",
  "protocol": null,
  "notes": [
    "ripgrep is a batch search tool: it walks directories, matches lines against a regex and writes results to stdout. Nothing is exchanged with another party over time, so there is no protocol to model."
  ]
}
```

A project with one:

```json
{
  "schemaVersion": "1.0.0",
  "protocol": {
    "id": "kvstore-wire",
    "version": "1",
    "transport": "stdin/stdout",
    "framing": "line-delimited",
    "participants": [
      {
        "name": "client",
        "description": "Sends one colon-separated command per line.",
        "evidence": { "path": "kvstore-cli/src/main.rs", "startLine": 4, "endLine": 11 }
      },
      {
        "name": "store",
        "description": "Parses the command and answers from the cache.",
        "evidence": { "path": "kvstore/src/api.rs", "startLine": 15, "endLine": 33 }
      }
    ],
    "states": [],
    "messages": [
      {
        "name": "get:<key>",
        "producer": "client",
        "consumer": "store",
        "schema": "get:<key>",
        "evidence": { "path": "kvstore/src/api.rs", "startLine": 18, "endLine": 22 }
      },
      {
        "name": "Response::Value | Response::Error",
        "producer": "store",
        "consumer": "client",
        "evidence": { "path": "kvstore/src/api.rs", "startLine": 5, "endLine": 10 }
      }
    ],
    "timeouts": [],
    "evidence": [{ "path": "kvstore/src/api.rs", "startLine": 1, "endLine": 14 }]
  },
  "notes": []
}
```
