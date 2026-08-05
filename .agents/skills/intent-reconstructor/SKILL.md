# intent-reconstructor

Reconstruct what this repository (or change) is *supposed* to do, from what the
project itself states — not from what the code happens to do.

## Inputs

You are in a read-only checkout at a pinned revision. Candidate intent
documents are listed in your task inputs; read them with the read tools.

## Method

1. Read every listed document: specifications, ADRs, README, contributor rules.
2. Extract each obligation as one requirement with a stable id (`REQ-001`,
   `REQ-002`, …, in the order you encounter them).
3. Cite the document each requirement came from in `sourceRef`, as a
   repo-relative path, optionally line-anchored (`docs/SPEC.md#L12-L18`).
4. Record what the project explicitly rules out as `nonGoals`, and anything the
   documents leave genuinely open as `unresolvedQuestions`.

## Hard rules

- **Cite or label.** A requirement you read in a document uses that document's
  `sourceKind` (`spec`, `adr`, `repository-rule`, `issue`, `commit`) and cites
  it. A requirement you concluded yourself must use `sourceKind: "inferred"`
  with `sourceRef: null`. Never present inference as a citation — citations are
  verified against the revision afterwards, and unverifiable ones are downgraded.
- **Absence is a finding.** If no specification exists, emit a single
  requirement with `sourceKind: "unavailable"` saying so. Do not invent
  requirements to fill the gap.
- **Obligations, not descriptions.** "Keys are untrusted input" is a
  requirement; "the cache uses a HashMap" is an implementation detail — skip it.
- Do not read source code for this task, and do not attempt network access.

## Output

Exactly one fenced ```json block validating against `intent.v1`:

```json
{
  "schemaVersion": "1.0.0",
  "requirements": [
    {
      "id": "REQ-001",
      "sourceKind": "spec",
      "sourceRef": "docs/SPEC.md#L10-L14",
      "text": "The cache holds at most max_entries entries; overflow evicts only as many as necessary.",
      "acceptanceCriteria": ["a write beyond the bound evicts exactly the overflow"]
    }
  ],
  "nonGoals": ["replication"],
  "compatibilityObligations": [],
  "unresolvedQuestions": ["should reads promote entries?"]
}
```
