# Roadmap — what CodeAtlas should grow next, and why

This document records every feature the August 2026 skills research surfaced that was
*not* implemented in the W phase, plus the standing deferrals that predate it. Each entry
says what the feature is, why it earns a place here, where the idea was read (the
research read every skill cataloged in `skills_deep_research.md` in full — Microsoft
Deep Wiki, Anthropic code-review, OpenAI codex-security + threat-model, GitLab
mr-review/mr-guided-review/mr-adversarial-review, Matt Pocock, Addy Osmani, NVIDIA
governance, Agents365 mermaid, GStack document-release, and a dozen smaller ones), and
what has to exist first. Sizes are milestone-shaped guesses, not commitments.

Already done in the W phase, for orientation: cross-run negative-result memory with
semantic fingerprints (ADR-0016), reviewer noise rules (linter territory, certainty bar,
scope-creep as `spec` findings), required validation rationale, and the measured
module-depth metric (`publicCount`, `metrics.public`).

Shipped in the X phase: the bounded dispatch retry ADR-0005 always described
(schema_invalid errors quoted back, live engines only — the reliability half of §2.5);
coverage read-receipts in their *measured* form (§2.2 — engine-observed Read-tool
paths, three-state read/not-read/unknown, `review-coverage.v1`); the churn metric
(§3.1 — `git log` on the mirror, receipted, module badge + most-changed table + map
border-width channel); evidence-density floor notes on the narrative (§3.5); and the
`llms-txt` artifact (§3.7). Sections below are kept for their unshipped remainders —
§2.5's cost-tiering experiment and §3.1's changed-in-PR filter are still open.

---

## 1. Publication UX — SHIPPED (Y phase, 2026-08-08)

The whole tier landed once publication was armed: line-in-diff anchoring with the
outside-diff body fallback and full-SHA permalinks (§1.1, minus suggestion blocks —
still blocked on a fix-proposal field findings don't have), the gate-enforced
AI-provenance marker (§1.2), proof-of-reading approval adapted from the VERIFY-marker
idea (§1.3 — `approve --payload <sha prefix>`), draft/closed-PR gating and
marker-recognized prior-discussion dedup (§1.4), and the M12 live posting test, which
first passed on 2026-08-08: posted through the full gate, verified on GitHub, published
twice to prove exactly-once. The original section text follows for the unshipped
remainder (committable suggestion blocks).

### 1.1 Positioned inline comments
One comment per validated finding, anchored to file + line range on the head SHA,
instead of today's single review comment. Committable ```suggestion blocks only when
the suggestion fixes the issue *entirely* (Anthropic's completeness rule); prose
otherwise. Full-40-char-SHA permalink citations with a context line of padding. An
honest positioning sentinel for findings whose anchor could not be resolved
(Alibaba's `0/0 = positioning failed`). *Source: Anthropic code-review plugin,
Alibaba open-code-review, Spillwave pr-reviewer.* Size: 1 milestone.

### 1.2 Forced AI-provenance labeling
The posting code path — not the model — prepends an "AI-generated" marker to every
external write, at the same layer as the kill switch. GitLab's `post-comment.sh` does
this unconditionally; it belongs in `publication/gate.py` where control flow cannot
skip it. *Source: GitLab mr-review.* Size: small, fold into 1.1.

### 1.3 Approval preview with machine-checkable review markers
Render the exact payload with `<!-- VERIFY: reason -->` markers wrapping every
agent-inferred field; `approve --publish` refuses while any marker survives, so
"a human reviewed each uncertain field" becomes mechanically checkable instead of
implied by the approval row. *Source: NVIDIA skill-card VERIFY/SELECT pattern.*
Size: 1 milestone.

### 1.4 Prior-discussion dedup and PR gating
Before reviewing a PR: skip drafts/closed/trivial PRs (cheap gating call), fetch
existing comments, and suppress findings already raised or addressed. Makes repeat
runs on a live PR idempotent at the conversation level, complementing the finding
memory's idempotence at the validation level. *Source: Anthropic plugin,
mr-adversarial-review.* Size: small-medium.

## 2. Review depth

### 2.1 Threat-model stage — the next big capability
A repository-wide artifact: components, trust boundaries (with the data that crosses
each: types, channel, guarantees, validation), assets with C/I/A objectives, attacker
capabilities *and explicit non-capabilities* (to deflate severity honestly), abuse
paths, stable `TM-nnn` threat ids. Two properties make it more than a report:
it is **cached per repository** and copied into each run unaltered (codex-security
caches exactly this way), and it emits **focus paths** — 2–30 repo-relative paths,
each tied to threat ids — that feed forward into reviewer attention, making the
reviewers cheaper and better-aimed. Add a criticality calibration section (what
critical/high/medium/low mean *for this repo*). New skill + schema + dashboard tab.
*Source: OpenAI security-threat-model (contract), codex-security (caching +
anti-diff-bias).* Size: 2 milestones. Adds per-run agent cost.

### 2.2 Coverage read-receipts for reviewers
Reviewers emit per-file receipts proving what they actually read; a coverage artifact
separates *not observed* from *not scanned*, with typed closures
(`deferred`/`not_applicable` + reason) for anything skipped. The review view then
shows coverage instead of implying it. The truest-to-CLAUDE.md item on this list
("no silent failure") — it lost the W-phase tiebreak only because it hardens honesty
rather than improving results. *Source: codex-security work ledger + coverage.json.*
Size: 1–1.5 milestones.

### 2.3 Attack-path phase for security findings
Post-validation, per surviving security finding: dataflow (source → sink → outcome),
reachability (attacker, entrypoint, preconditions), impact and likelihood with
reasons, limitations. Even rejected candidates get a receipt saying why no path
exists. *Source: codex-security.* Size: 1 milestone, security category only.

### 2.4 Performance dimension with revert discipline
Only worth doing with a benchmark battery item (criterion). Adopt Osmani's
adjudication rules verbatim: delta must beat run-to-run noise measured under
identical conditions; one change per measurement; "neutral is a revert"; a metric
win that touches a test is a regression. Keep an attempt ledger including reverted
experiments (the finding memory's sibling for optimizations). *Source: Addy Osmani
performance-optimization.* Size: 1.5 milestones. Prereq: benchmarks exist in target
repos.

### 2.5 Reviewer redundancy and cost tiering
Two deliberately different context policies on the same dimension (diff-only vs
full-context bug agents both existed in Anthropic's plugin for a reason), and
cheaper models for gating/summarizing stages vs judgment stages. Worth measuring
against the recall fixture before adopting. *Source: Anthropic plugin.* Size: small
experiment first.

### 2.6 Test-quality rubric for the correctness reviewer
Reviewable properties of the *test* half of a diff: reproduction test predates fix,
state-vs-interaction assertions, real > fake > stub > mock ordering, DAMP over DRY.
Plus blinded regression-test authorship (test written without seeing the fix) if
CodeAtlas ever generates tests for validated findings. *Source: Addy Osmani TDD
skill.* Size: prompt-only start, small.

## 3. Artifacts & dashboard

### 3.1 Churn overlay
Weight map/matrix views and reviewer attention by git-log change frequency; a
changed-in-PR filter on the dependency graph. Hot files are where depth problems
cost the most (Pocock scopes architecture scans by exactly this). Deterministic:
`git log` is already receipted. *Source: Pocock improve-codebase-architecture; the
research doc's Cytoscape filter list.* Size: 1 milestone.

### 3.2 Visual QA on rendered diagrams
Today mmdc/Structurizr validation proves *renderability*; nothing checks the render
is *readable*. Two adoptable layers: numeric visual budgets enforced as a silent
repair pass before validation (≤12 top-level nodes, ≤4 fanout, ≤24-char labels —
the D2 toolshed's numbers), and a bounded vision self-check of the exported PNG
against a named defect taxonomy: label truncation, cramped density, wrong
orientation, edge spaghetti, wrong diagram type, low contrast — max 2 repair
rounds, then ship anyway and say so. *Source: Agents365 mermaid-skill, claude-toolshed
d2.* Size: 1 milestone; the vision check needs an agent call per diagram.

### 3.3 Portable walkthrough export
A self-contained single-file HTML per topic: clickable Mermaid nodes opening a
detail panel where every node carries a real 1–5-line source snippet, pan/zoom,
no server. Complements the dashboard — something to attach to a PR. The complete
implementation recipe (click-binding via `bindFunctions` recovery, ref-based
pan/zoom without React re-renders, Shiki pre-highlighting with fallback) was
captured from the walkthrough skill's reference files. *Source: alexanderop/walkthrough.*
Size: 1–1.5 milestones.

### 3.4 Audience-stratified onboarding
Four guides from the same measured evidence: contributor (glossary + first-PR
path), staff engineer (the one core architectural insight + reading order — the
reading order already exists), executive (no code; risk and cost), product manager
(no jargon; user journeys). Deep Wiki ships exactly this split with per-audience
content contracts. *Source: microsoft/skills deep-wiki wiki-architect.* Size: 1
milestone, mostly prompt + template work. Adds agent cost per run.

### 3.5 Evidence-density floors on narratives
Mechanically checkable minimums on agent-authored artifacts: ≥N distinct files
cited per narrative section, per-diagram `<!-- Sources: file:line -->` provenance
blocks, a source column in every generated table. Exactly the cheap-deterministic-
validator shape CodeAtlas already likes. *Source: deep-wiki wiki-page-writer's
quantitative quotas.* Size: small.

### 3.6 Docs-drift stage
From the diff: extract public-surface changes (new/renamed/removed functions,
flags, config keys), build a per-entity Diátaxis coverage matrix
(reference/how-to/tutorial/explanation), and cross-reference entity names inside
ARCHITECTURE/README diagrams against renames, splits, removals, moves. Advisory
findings only — never auto-edit docs. *Source: GStack document-release.* Size: 1
milestone.

### 3.7 Agent-discoverability outputs
Emit `llms.txt` (and optionally per-directory `AGENTS.md`, only-if-missing) from the
narrative + module pages so third-party agents can consume CodeAtlas's understanding
of a repo without knowing the tool. *Source: deep-wiki's design principles.* Size:
small.

### 3.8 Plotly metrics report
Churn, coverage, complexity and benchmark plots as a static artifact with the
underlying CSV/JSON preserved so every chart is auditable. From the research doc's
own recommendations; least urgent of the artifact items. Size: 1 milestone.

## 4. ADR system

### 4.1 Machine-addressable ADR claims
Coded bullets (`POS-001`, `NEG-002`, `ALT-003`, `IMP-003`) in generated ADRs plus
`supersedes`/`superseded_by` frontmatter. The conformance audit then binds code
checks to stable claim ids instead of prose matching, and the decision graph
becomes traversable (dangling supersessions detectable). *Source: github/awesome-copilot
ADR skill.* Size: small-medium (template + audit change).

### 4.2 Code→ADR back-references
Scan for `ADR-NNNN` comments in source as a measured edge type; the audit gains a
bidirectional mesh (decision → code and code → decision). Pairs with ADRs authored
as work orders: an Implementation Plan naming paths and a Verification section of
machine-checkable checkboxes the audit can walk. *Source: skillrecordings/adr-skill.*
Size: 1 milestone.

## 5. Skill governance

### 5.1 Skill cards
Per-skill governance record beyond the content hash: owner, declared permission
envelope (file scopes, allowed commands — the registry already stores commands),
credential requirements with the honest `"not specified"` vocabulary, risks and
mitigations, output contract. NVIDIA's approval rule is the bar: a reviewer should
understand purpose, owner, output, risks and release evidence *without opening the
source*. *Source: NVIDIA skill-card-generator.* Size: 1 milestone. Most valuable
if skills are ever shared beyond this repo.

### 5.2 Skill activation evals
Per-skill eval fixtures including *negative cases* — prompts where the correct
behavior is not firing — graded against a behavioral rubric (scope compliance:
"did not read outside the checkout", "wrote only where declared"). NVIDIA treats
a missing benchmark as a failed one; their published example caught a real
cross-agent security regression. *Source: NVIDIA evaluating-agent-skills.* Size:
1–2 milestones; needs a sandboxed A/B harness.

## 6. Platform

- **M17 C/C++ adapter** — `compile_commands.json` + clangd index + CMake File API,
  per the original plan. The extractor Protocol is already language-agnostic.
- **Docker sandbox for untrusted repos** — extraction and review of repos you did
  not write should not run on the host. Standing deferral.
- **Linux runbook** — the code is portable (verified: tool discovery is
  `shutil.which`-first, fixtures are LF, cassette hashes reproduce); what remains is
  de-PowerShelling README snippets, a keyring→`CODEATLAS_DB_URL` note for headless
  use, and `playwright install --with-deps`.
- **CI** — there is none; `poe check-all` is the release gate by convention. A
  hosted runner needs the Linux runbook plus a Postgres service container.
- **GitHub PAT + live posting test** — the M12 test that has never run live; also
  the gate for section 1.

## Non-goals (considered and declined)

- **Installing third-party skills.** Every candidate was read; none survives the
  trust model (unpinnable moving repos, host-locked plugins, external endpoints).
  Patterns get absorbed; packages do not get installed. (ADR-0008.)
- **Kroki or any remote renderer** — diagram sources would leave the machine.
- **A single universal reviewer** — the isolated-specialist design is the product.
- **Confidence as the publication gate** — confidence supplements the evidence
  gate; it never replaces it (the deterministic eligibility rules stay authoritative).
