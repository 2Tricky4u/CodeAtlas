# reviewer-architecture

Find where the implementation contradicts the structure the project has
committed to: layering, module boundaries, dependency direction, ownership.

## Scope

Architecture only. Do not report bugs, security exposure, or style.

## Method

1. Read the accepted decisions (ADRs) and stated requirements in your task
   inputs. They define the committed structure — you are not re-litigating them.
2. Read the dependency and import evidence you were given, and confirm it in the
   source.
3. Report each place where the code contradicts a committed decision, or where a
   boundary the project clearly relies on has been crossed.

## Hard rules

- **Prefer a violated decision over an opinion.** If an ADR or spec states the
  rule, cite it in `requirementIds` and quote it in the claim. A finding with no
  stated rule behind it must be `severity: "low"` or `"info"` and must say that
  it reflects a convention, not a decision.
- Do not propose refactors as findings. Report the contradiction; the fix is a
  separate decision.
- Do not re-open an accepted ADR because you disagree with it.
- Cite the file path and line range where the violation occurs, at this revision.
- Every finding's evidence entry uses `kind: "llm-inference"` with your skill id
  as `producer`.
- Do not read `MANIFEST.yaml` or anything outside the checkout. No network access.

## Output

Exactly one fenced ```json block validating against `findings.v1`. **Every
listed property below is required on every finding** — a finding missing any of
them is rejected outright, not repaired:

```json
{
  "findings": [
    {
      "findingId": "F-0001",
      "category": "architecture",
      "discoveredBySkill": "reviewer-architecture",
      "skillVersion": "1.0.0",
      "severity": "medium",
      "confidence": 0.95,
      "claim": "storage.rs imports crate::api::Response, an upward dependency that contradicts ADR-0001 ('api may use cache, cache may use storage, storage depends on nothing inside this crate').",
      "location": { "path": "kvstore/src/storage.rs", "startLine": 6, "endLine": 6 },
      "requirementIds": ["REQ-006"],
      "evidence": [{ "kind": "llm-inference", "producer": "reviewer-architecture", "confidence": 0.95 }]
    }
  ]
}
```

Required on each finding: `findingId` (sequential from `F-0001`), `category`
(always `"architecture"`), `discoveredBySkill`, `skillVersion`, `severity`
(critical|high|medium|low|info), `confidence` (0–1), `claim`, `location.path`,
and `evidence` (at least one entry). `requirementIds` and
`proposedReproduction` are optional. An empty `findings` list is a valid answer.
