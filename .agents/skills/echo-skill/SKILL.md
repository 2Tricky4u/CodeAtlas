# echo-skill

Adapter validation skill. It exists to prove, independently of any review logic,
that the agent engine can: run in a pinned read-only checkout, obey its declared
permissions, and return schema-valid structured output.

## Task

Count the Rust source files (`*.rs`) in the current working directory tree, then
report the count together with the revision you were given.

## Rules

- Use only the read tools and the commands your task permissions allow.
- Do not attempt network access; do not write files.
- Reply with exactly one fenced ```json block, no prose outside it.

## Output

```json
{ "fileCount": 7, "revision": "<the 40-char sha from your task>" }
```
