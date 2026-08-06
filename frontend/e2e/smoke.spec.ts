// Dashboard e2e. The assertions are about what a reader can *learn* from the
// page — before/after, what else could break, why a view is missing — not about
// pixels. API responses are route-mocked with payloads shaped exactly like the
// real API; the Python contract tests pin those shapes against the schemas.

import { expect, test, type Page } from "@playwright/test";
import {
  ADR_AUDIT,
  API_CHANGE,
  APPROVALS,
  ARCHITECTURE,
  CANDIDATE_FINDINGS,
  DETAIL,
  INTENT,
  REVIEW_MARKDOWN,
  REVIEW_PAYLOAD,
  DIFF,
  EXPLANATION,
  FINDINGS,
  GRAPH,
  HEAD,
  IMPACT,
  OVERVIEW,
  PROJECT_EXPLANATION,
  PROTOCOL_MODEL,
  PROTOCOL_NONE,
  PROTOCOL_SEQUENCE,
  RUN,
  RUN_ID,
  SOURCE,
  STRUCTURIZR_DSL,
  VIEWS,
} from "./fixtures";

async function mockApi(
  page: Page,
  options: { withChange?: boolean; withNarrative?: boolean; withReview?: boolean } = {},
) {
  const withChange = options.withChange ?? true;
  const withNarrative = options.withNarrative ?? true;
  const withReview = options.withReview ?? true;
  await page.route("**/api/runs", (route) => route.fulfill({ json: [RUN] }));
  await page.route(`**/api/runs/${RUN_ID}`, (route) => route.fulfill({ json: DETAIL }));
  await page.route(`**/api/runs/${RUN_ID}/overview`, (route) => route.fulfill({ json: OVERVIEW }));
  await page.route(`**/api/runs/${RUN_ID}/views`, (route) => route.fulfill({ json: VIEWS }));
  await page.route(`**/api/runs/${RUN_ID}/graph`, (route) => route.fulfill({ json: GRAPH }));
  await page.route(`**/api/runs/${RUN_ID}/findings`, (route) => route.fulfill({ json: FINDINGS }));
  await page.route(`**/api/source/${HEAD}**`, (route) => route.fulfill({ json: SOURCE }));
  await page.route("**/api/source/**", (route) => route.fulfill({ json: SOURCE }));

  const artifact = (role: string, json: unknown) =>
    page.route(`**/api/runs/${RUN_ID}/artifact/${role}`, (route) =>
      withChange ? route.fulfill({ json }) : route.fulfill({ status: 404, json: { detail: "none" } }),
    );
  await artifact("graph-diff", DIFF);
  await artifact("api-change", API_CHANGE);
  await artifact("change-impact", IMPACT);
  await artifact("change-explanation", EXPLANATION);

  // Routed outside the `artifact` helper on purpose: neither the narrative nor
  // the architecture depends on there being a change to explain.
  await page.route(`**/api/runs/${RUN_ID}/artifact/project-explanation`, (route) =>
    withNarrative
      ? route.fulfill({ json: PROJECT_EXPLANATION })
      : route.fulfill({ status: 404, json: { detail: "none" } }),
  );
  await page.route(`**/api/runs/${RUN_ID}/artifact/architecture`, (route) =>
    route.fulfill({ json: ARCHITECTURE }),
  );
  await page.route(`**/api/runs/${RUN_ID}/artifact/structurizr-dsl`, (route) =>
    route.fulfill({ body: STRUCTURIZR_DSL, headers: { "content-type": "text/plain" } }),
  );
  await page.route(`**/api/runs/${RUN_ID}/artifact/adr-audit`, (route) =>
    route.fulfill({ json: ADR_AUDIT }),
  );
  await page.route(`**/api/runs/${RUN_ID}/artifact/protocol-model`, (route) =>
    route.fulfill({ json: PROTOCOL_MODEL }),
  );
  await page.route(`**/api/runs/${RUN_ID}/artifact/protocol-sequence`, (route) =>
    route.fulfill({ body: PROTOCOL_SEQUENCE, headers: { "content-type": "text/plain" } }),
  );
  await page.route(`**/api/runs/${RUN_ID}/artifact/protocol-state`, (route) =>
    route.fulfill({ status: 404, json: { detail: "stateless" } }),
  );

  // The review's own artifacts. Gated on `withReview` because a deterministic
  // run has none of them and must say so rather than render empty panels.
  const reviewArtifact = (role: string, json: unknown) =>
    page.route(`**/api/runs/${RUN_ID}/artifact/${role}`, (route) =>
      withReview ? route.fulfill({ json }) : route.fulfill({ status: 404, json: { detail: "none" } }),
    );
  await reviewArtifact("intent", INTENT);
  await reviewArtifact("candidate-findings", CANDIDATE_FINDINGS);
  await reviewArtifact("review-payload-dry-run", REVIEW_PAYLOAD);
  await page.route(`**/api/runs/${RUN_ID}/artifact/review-markdown`, (route) =>
    withReview
      ? route.fulfill({ body: REVIEW_MARKDOWN, headers: { "content-type": "text/markdown" } })
      : route.fulfill({ status: 404, json: { detail: "none" } }),
  );
  await page.route(`**/api/runs/${RUN_ID}/approval`, (route) =>
    route.fulfill({ json: withReview ? APPROVALS : [] }),
  );
}

/** A narrative past the collapse threshold, built from the fixture's one section. */
function longNarrative() {
  const [entry] = PROJECT_EXPLANATION.sections;
  return {
    ...PROJECT_EXPLANATION,
    sections: [
      {
        ...entry!,
        claims: Array.from({ length: 12 }, (_, i) => ({
          ...entry!.claims[0]!,
          text: `${entry!.claims[0]!.text} (${i})`,
        })),
      },
    ],
  };
}

test.describe("shell and navigation", () => {
  test.beforeEach(({ page }) => mockApi(page));

  test("the run list shows what each run is, and a PR reads as one", async ({ page }) => {
    await page.goto("/");
    const list = page.getByTestId("runs-list");
    await expect(list).toContainText("local/kvstore");
    await expect(list).toContainText("succeeded");
    await expect(list).toContainText("PR #7");
  });

  test("selecting a run lands on the overview and the URL is shareable", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: /local\/kvstore/ }).click();
    await expect(page.getByTestId("overview-view")).toBeVisible();
    expect(page.url()).toContain(`/runs/${RUN_ID}/overview`);
  });

  test("a deep link opens its tab directly", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/change`);
    await expect(page.getByTestId("change-view")).toBeVisible();
  });

  test("the header states the revisions under analysis", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/overview`);
    await expect(page.getByTestId("run-status")).toHaveText("succeeded");
    await expect(page.locator("header").first()).toContainText("→");
  });
});

test.describe("project overview", () => {
  test.beforeEach(({ page }) => mockApi(page));

  test("it says where to start and why", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/overview`);
    const start = page.getByTestId("start-here");
    await expect(start).toContainText("kvstore/src/cache.rs");
    await expect(start).toContainText("3 module(s) depend on it");
  });

  test("clicking a suggestion explains the module rather than dead-ending in text", async ({
    page,
  }) => {
    // Until Phase 3 this opened a source popup and stopped; now it lands on the
    // module page, where source is one click among several.
    await page.goto(`/#/runs/${RUN_ID}/overview`);
    await page.getByRole("button", { name: "kvstore/src/cache.rs" }).first().click();
    await expect(page.getByTestId("module-view")).toBeVisible();
    await expect(page).toHaveURL(/module\/kvstore\/src\/cache\.rs/);
  });

  test("the narrative comes after the measurements, and every claim is cited", async ({
    page,
  }) => {
    await page.goto(`/#/runs/${RUN_ID}/overview`);
    await expect(page.getByTestId("narrative-summary")).toContainText(
      "in-process key-value store",
    );
    await expect(page.getByTestId("narrative-entry")).toContainText("binds the listener");
    // Counts are measured; the prose interpreting them comes below.
    const stats = await page.getByTestId("overview-view").locator(".stat").first().boundingBox();
    const prose = await page.getByTestId("narrative-summary").boundingBox();
    expect(prose!.y).toBeGreaterThan(stats!.y);
  });

  test("a cycle citation names its members rather than gesturing at them", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/overview`);
    const chip = page.getByTestId("narrative-citation").filter({ hasText: "cycle of 2" });
    await expect(chip).toHaveAttribute("title", /api\.rs ⇄ .*storage\.rs/);
  });

  test("a narrative citation opens the file it points at", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/overview`);
    await page.getByTestId("narrative-citation").filter({ hasText: "main.rs:1" }).click();
    await expect(page.getByTestId("source-panel")).toBeVisible();
  });

  test("a module citation is distinguishable from a citation of the same file", async ({
    page,
  }) => {
    // Both point at main.rs but they are different things: one is a node the
    // graph measured, the other is text at a line.
    await page.goto(`/#/runs/${RUN_ID}/overview`);
    await expect(
      page.getByTestId("narrative-citation").filter({ hasText: "mod main.rs" }),
    ).toBeVisible();
  });

  test("a long narrative keeps the measured panels reachable", async ({ page }) => {
    await page.route(`**/api/runs/${RUN_ID}/artifact/project-explanation`, (route) =>
      route.fulfill({ json: longNarrative() }),
    );
    await page.goto(`/#/runs/${RUN_ID}/overview`);
    // The summary always shows; the claims are behind one click, so "start
    // here" is not pushed off the page by prose.
    await expect(page.getByTestId("narrative-summary")).toBeVisible();
    await expect(page.getByTestId("narrative-entry")).toHaveCount(0);
    await page.getByTestId("narrative-toggle").click();
    await expect(page.getByTestId("narrative-entry")).toBeVisible();
  });

  test("claims removed by validation are disclosed, not quietly missing", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/overview`);
    await expect(page.getByTestId("narrative-dropped")).toContainText("1 statement(s)");
  });

  test("a run with no narrative says so instead of showing a blank panel", async ({ page }) => {
    await mockApi(page, { withNarrative: false });
    await page.goto(`/#/runs/${RUN_ID}/overview`);
    await expect(page.getByTestId("no-narrative")).toContainText("everything above is measured");
  });
});

test.describe("module page", () => {
  test.beforeEach(({ page }) => mockApi(page));

  test("it says what the file defines, from the measured contains edges", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/module/kvstore/src/cache.rs`);
    const definitions = page.getByTestId("definitions");
    await expect(definitions).toContainText("evict_oldest");
    await expect(definitions).toContainText("put");
  });

  test("expanding a definition shows who uses it, grouped by module", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/module/kvstore/src/cache.rs`);
    await page.getByTestId("definition").filter({ hasText: "evict_oldest" }).click();
    await expect(page.getByTestId("callers")).toContainText("put");
  });

  test("a change section names the symbols this PR touched here", async ({ page }) => {
    // H2: the review, where you are looking. The diff fixture adds evict,
    // removes evict_oldest and touches put — all in cache.rs.
    await page.goto(`/#/runs/${RUN_ID}/module/kvstore/src/cache.rs`);
    const change = page.getByTestId("change-here");
    await expect(change).toContainText("evict_oldest");
    await expect(change).toContainText("removed");
    await expect(page.getByTestId("findings-here")).toContainText("overflow + 1");
  });

  test("without a base revision there is no change section at all", async ({ page }) => {
    // Absent, not empty — the rule the change view already follows.
    await page.route(`**/api/runs/${RUN_ID}`, (route) =>
      route.fulfill({ json: { ...DETAIL, baseSha: null, kind: "repository" } }),
    );
    await page.goto(`/#/runs/${RUN_ID}/module/kvstore/src/cache.rs`);
    await expect(page.getByTestId("module-view")).toBeVisible();
    await expect(page.getByTestId("change-here")).toHaveCount(0);
  });

  test("an unknown path says why rather than rendering blank", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/module/kvstore/src/ghost.rs`);
    await expect(page.getByTestId("empty-state")).toContainText("not a module");
  });

  test("a finding's location links into the module page", async ({ page }) => {
    // The reverse direction: from the review surfaces into the understanding.
    await page.goto(`/#/runs/${RUN_ID}/findings`);
    await page.getByTestId("module-link").first().click();
    await expect(page.getByTestId("module-view")).toBeVisible();
  });
});

test.describe("architecture view", () => {
  test.beforeEach(({ page }) => mockApi(page));

  test("it draws this repository's packages, not its dependency tree", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/architecture`);
    const table = page.getByTestId("architecture-table");
    await expect(table).toContainText("kvstore-cli");
    await expect(page.getByTestId("architecture-notes")).toContainText("are not drawn");
  });

  test("every container names the graph node it was derived from", async ({ page }) => {
    // The claim that separates this from a hand-drawn diagram.
    await page.goto(`/#/runs/${RUN_ID}/architecture`);
    await expect(page.getByTestId("architecture-table")).toContainText("kvstore@0.1.0");
  });

  test("a container opens the manifest it came from", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/architecture`);
    await page.getByRole("button", { name: "kvstore-cli" }).click();
    await expect(page.getByTestId("source-panel")).toBeVisible();
  });

  test("the interchange format is offered, not just the picture", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/architecture`);
    await expect(page.getByTestId("dsl")).toContainText("softwareSystem");
  });

  test("a diagram past the readability budget says so", async ({ page }) => {
    await page.route(`**/api/runs/${RUN_ID}/artifact/architecture`, (route) =>
      route.fulfill({
        json: {
          ...ARCHITECTURE,
          readability: {
            passed: false,
            checks: [{ name: "node-budget", passed: false, value: 41, limit: 25 }],
          },
          notes: ["node-budget 41 exceeds the limit of 25; this diagram is larger than one a person can take in at a glance"],
        },
      }),
    );
    await page.goto(`/#/runs/${RUN_ID}/architecture`);
    await expect(page.getByTestId("architecture-notes")).toContainText("larger than one a person");
  });

  test("a run with no architecture says so rather than showing an empty canvas", async ({
    page,
  }) => {
    await page.route(`**/api/runs/${RUN_ID}/artifact/architecture`, (route) =>
      route.fulfill({ status: 404, json: { detail: "none" } }),
    );
    await page.goto(`/#/runs/${RUN_ID}/architecture`);
    await expect(page.getByTestId("empty-state")).toContainText("no architecture model");
  });
});

test.describe("decisions view", () => {
  test.beforeEach(({ page }) => mockApi(page));

  test("decisions read in the order they were taken", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/adr`);
    const entries = page.getByTestId("adr-timeline").locator("li");
    // `allInnerTexts` does not auto-wait, so anchor on the count first.
    await expect(entries).toHaveCount(3);
    const labels = await entries.locator(".panel-title").allInnerTexts();
    expect(labels.join(" ")).toMatch(/ADR-0001[\s\S]*ADR-0002[\s\S]*ADR-0003/);
  });

  test("drift is stated, not softened", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/adr`);
    await expect(page.getByTestId("adr-view")).toContainText("probable-drift");
    await expect(page.getByTestId("adr-view")).toContainText("contradicts this decision");
  });

  test("unverifiable is not allowed to look like conformance", async ({ page }) => {
    // The distinction the whole audit exists to preserve.
    await page.goto(`/#/runs/${RUN_ID}/adr`);
    await expect(page.getByTestId("adr-view")).toContainText(
      "no evidence in the graph could check this either way",
    );
  });

  test("a decision needing a person says the audit may not choose", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/adr`);
    await expect(page.getByTestId("needs-human")).toContainText("not allowed to choose");
  });

  test("a superseded decision says what replaced it", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/adr`);
    await expect(page.getByTestId("superseded-by")).toContainText("ADR-0005");
  });

  test("a project with no ADRs states that rather than showing a blank tab", async ({ page }) => {
    // The common case: ripgrep has no docs/adr at all.
    await page.route(`**/api/runs/${RUN_ID}/artifact/adr-audit`, (route) =>
      route.fulfill({
        json: {
          revision: HEAD,
          decisions: [],
          notes: ["no ADRs found; architecture conformance was not audited"],
        },
      }),
    );
    await page.goto(`/#/runs/${RUN_ID}/adr`);
    await expect(page.getByTestId("adr-notes")).toContainText("no ADRs found");
    await expect(page.getByTestId("empty-state")).toContainText("records no architecture decisions");
  });
});

test.describe("protocol view", () => {
  test.beforeEach(({ page }) => mockApi(page));

  test("a project with no protocol says so, and why", async ({ page }) => {
    // The primary state of this page, not an error state: most projects have
    // no protocol, and inventing one is the worst thing this tool could do.
    await page.route(`**/api/runs/${RUN_ID}/artifact/protocol-model`, (route) =>
      route.fulfill({ json: PROTOCOL_NONE }),
    );
    await page.goto(`/#/runs/${RUN_ID}/protocol`);
    await expect(page.getByTestId("no-protocol")).toContainText("no protocol to model");
    await expect(page.getByTestId("protocol-view")).toContainText("batch search tool");
  });

  test("a protocol names its transport and framing", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/protocol`);
    await expect(page.getByTestId("protocol-view")).toContainText("in-process call");
    await expect(page.getByTestId("protocol-view")).toContainText("colon-separated");
  });

  test("the sequence diagram is rendered, not shown as source", async ({ page }) => {
    // The mermaid dependency has been installed and unimported since P5.
    await page.goto(`/#/runs/${RUN_ID}/protocol`);
    await expect(page.getByTestId("mermaid").locator("svg")).toBeVisible();
  });

  test("every message says where it was read from", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/protocol`);
    await expect(page.getByTestId("messages")).toContainText("api.rs:18");
  });

  test("an evidence chip opens the source it points at", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/protocol`);
    await page.getByTestId("protocol-evidence").first().click();
    await expect(page.getByTestId("source-panel")).toBeVisible();
  });

  test("elements removed by validation are disclosed", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/protocol`);
    await expect(page.getByTestId("protocol-dropped")).toContainText("Subscribe");
  });

  test("what was deliberately not modelled is shown as such", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/protocol`);
    await expect(page.getByTestId("protocol-notes")).toContainText("stateless");
  });

  test("a diagram that will not parse shows its source, not a broken image", async ({ page }) => {
    // Mermaid's own error output is a red box with a stack trace, which reads
    // as "this project is broken" rather than "this diagram is".
    await page.route(`**/api/runs/${RUN_ID}/artifact/protocol-sequence`, (route) =>
      route.fulfill({ body: "sequenceDiagram\n    !!! not mermaid", headers: { "content-type": "text/plain" } }),
    );
    await page.goto(`/#/runs/${RUN_ID}/protocol`);
    await expect(page.getByTestId("mermaid-error")).toContainText("could not be drawn");
  });

  test("an oversized diagram is refused rather than drawn illegibly", async ({ page }) => {
    const huge = ["sequenceDiagram", ...Array.from({ length: 200 }, (_, i) => `    a->>b: m${i}`)];
    await page.route(`**/api/runs/${RUN_ID}/artifact/protocol-sequence`, (route) =>
      route.fulfill({ body: huge.join("\n"), headers: { "content-type": "text/plain" } }),
    );
    await page.goto(`/#/runs/${RUN_ID}/protocol`);
    await expect(page.getByTestId("mermaid-refused")).toContainText("stops being followable");
  });
});

test.describe("change view", () => {
  test.beforeEach(({ page }) => mockApi(page));

  test("the narrative leads, and every claim carries a citation", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/change`);
    const view = page.getByTestId("change-view");
    await expect(view).toContainText("Replaces Cache::evict_oldest");
    await expect(view).toContainText("What it did before");
    await expect(view).toContainText("removing one entry more than asked for");
    // the citation is a control, not decoration
    await expect(page.getByRole("button", { name: /before cache\.rs:41/ })).toBeVisible();
  });

  test("a citation opens the revision it cites", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/change`);
    await page.getByRole("button", { name: /before cache\.rs:41/ }).click();
    await expect(page.getByTestId("source-panel")).toBeVisible();
  });

  test("removed claims are disclosed rather than silently dropped", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/change`);
    await expect(page.getByTestId("change-view")).toContainText(
      "1 statement(s) were removed because their citations did not resolve",
    );
  });

  test("the API delta shows the break with its severity", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/change`);
    const api = page.getByTestId("api-kvstore");
    await expect(api).toContainText("bump: major");
    await expect(api).toContainText("− pub fn kvstore::cache::Cache::evict_oldest");
    await expect(api).toContainText("+ pub fn kvstore::cache::Cache::evict");
    await expect(api).toContainText("inherent_method_missing");
  });

  test("the structural delta names the relationship that disappeared", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/change`);
    const view = page.getByTestId("change-view");
    await expect(view).toContainText("relationships that no longer exist");
    await expect(view).toContainText("evict_oldest");
    await expect(view).toContainText("likely renamed (inference, not fact)");
  });

  test("the change carries only labels the diff could prove", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/change`);
    const labels = page.getByTestId("change-label");
    await expect(labels.filter({ hasText: "rename" })).toBeVisible();
    // The five that need reading code stay in the cited narrative.
    for (const invented of ["logic-change", "error-handling", "logging"]) {
      await expect(labels.filter({ hasText: invented })).toHaveCount(0);
    }
  });

  test("a label says what decided it", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/change`);
    await expect(
      page.getByTestId("change-label").filter({ hasText: "rename" }),
    ).toHaveAttribute("title", /overlapping range/);
  });

  test("a version bump is shown as excluded, not as churn", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/change`);
    await expect(page.getByTestId("change-view")).toContainText(
      "version bumps (excluded from the structural comparison)",
    );
  });

  test("impact carries its precision caveat", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/change`);
    const view = page.getByTestId("change-view");
    await expect(view).toContainText("handle_request");
    await expect(view).toContainText("public-api");
    await expect(view).toContainText("possibilities, not certainties");
  });
});

test.describe("change view without a change", () => {
  test.beforeEach(({ page }) => mockApi(page, { withChange: false }));

  test("a single-revision run says so instead of showing an empty diff", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/change`);
    await expect(page.getByText(/analyzed a single revision/)).toBeVisible();
  });
});

test.describe("project map", () => {
  test.beforeEach(({ page }) => mockApi(page));

  test("it opens at package level and renders", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/map`);
    await expect(page.getByTestId("graph")).toBeVisible();
    await expect(page.locator('[data-testid="graph"] canvas').first()).toBeVisible();
  });

  test("a refused view is stated, with the check it failed", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/map`);
    const refusals = page.getByTestId("refusals");
    await expect(refusals).toContainText("modules:kvstore");
    await expect(refusals).toContainText("exceeds the limit of 25");
  });

  test("the matrix is available for the whole project", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/map`);
    await page.getByRole("button", { name: /dependency matrix/ }).click();
    await expect(page.getByTestId("matrix")).toContainText("row depends on column");
  });

  test("search finds a symbol and focusing it renders its neighborhood", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/map`);
    await page.getByTestId("focus-tab").click();
    await page.getByTestId("focus-search").fill("evict");
    await page.getByTestId("focus-match").first().click();
    await expect(page.locator('[data-testid="focus-graph"] canvas').first()).toBeVisible();
  });

  test("a filter narrows the neighborhood and says how much it hid", async ({ page }) => {
    // The cytoscape export has carried evidence producers since M6 with a
    // comment saying the dashboard can filter on them; nothing ever did.
    await page.goto(`/#/runs/${RUN_ID}/map`);
    await page.getByTestId("focus-tab").click();
    await page.getByTestId("focus-search").fill("cache");
    await page.getByTestId("focus-match").first().click();
    await expect(page.getByTestId("filters")).toBeVisible();
    await page.getByTestId("filter-toggle").filter({ hasText: "function" }).click();
    // The invariant is that hiding is counted and stated, not a specific count
    // that shifts whenever the fixture graph gains a node.
    await expect(page.getByTestId("filter-hidden")).toContainText(/hid [1-9]\d* node\(s\)/);
  });

  test("the node you searched for is never filtered away", async ({ page }) => {
    // Filtering out the thing just named leaves a blank canvas with no
    // explanation, which is not a filter.
    await page.goto(`/#/runs/${RUN_ID}/map`);
    await page.getByTestId("focus-tab").click();
    await page.getByTestId("focus-search").fill("cache");
    await page.getByTestId("focus-match").first().click();
    await page.getByTestId("filter-toggle").filter({ hasText: "file" }).click();
    await expect(page.locator('[data-testid="focus-graph"] canvas').first()).toBeVisible();
  });

  test("filters offer the kinds this graph actually contains", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/map`);
    await page.getByTestId("focus-tab").click();
    await page.getByTestId("focus-search").fill("cache");
    await page.getByTestId("focus-match").first().click();
    const filters = page.getByTestId("filters");
    await expect(filters).toContainText("rust-analyzer");
    await expect(filters).toContainText("cargo");
  });

  test("nothing is drawn until the reader names something", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/map`);
    await page.getByTestId("focus-tab").click();
    await expect(page.getByText(/the whole graph is never rendered/)).toBeVisible();
  });
});

test.describe("review view", () => {
  test.beforeEach(({ page }) => mockApi(page));

  test("it shows what did not survive, not just what did", async ({ page }) => {
    // The whole adversarial-validation claim is invisible otherwise: a table of
    // survivors looks the same whether the check rejected one candidate or none.
    await page.goto(`/#/runs/${RUN_ID}/review`);
    const table = page.getByTestId("not-validated");
    await expect(table).toContainText("F-0009");
    await expect(table).toContainText("shared across threads");
    await expect(table).not.toContainText("F-0001");
  });

  test("the funnel counts every step, not just the ends", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/review`);
    const funnel = page.getByTestId("funnel");
    await expect(funnel).toContainText("2 proposed");
    await expect(funnel).toContainText("1 validated");
    await expect(funnel).toContainText("1 publishable");
  });

  test("each verdict is explained, because they are not the same answer", async ({ page }) => {
    // "unresolved" is not "rejected" and neither is "the reviewer was wrong".
    await page.goto(`/#/runs/${RUN_ID}/review`);
    await expect(page.getByTestId("verdict-key")).toContainText("could neither confirm nor refute");
  });

  test("it names who proposed a finding that did not survive", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/review`);
    await expect(page.getByTestId("not-validated")).toContainText("security");
  });

  test("it shows what the reviewers were checking against", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/review`);
    await expect(page.getByTestId("requirements")).toContainText("REQ-001");
    await expect(page.getByTestId("requirements")).toContainText("evicts only as many");
  });

  test("a question the specs left open is disclosed", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/review`);
    await expect(page.getByTestId("unresolved")).toContainText("LRU or insertion-ordered");
  });

  test("an undecided approval reads as awaiting a person, not as failure", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/review`);
    await expect(page.getByTestId("review-view")).toContainText("awaiting a human decision");
    await expect(page.getByTestId("approvals")).toContainText("undecided");
  });

  test("the payload says nothing was sent", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/review`);
    await expect(page.getByTestId("approval-note")).toContainText("nothing was sent");
    await expect(page.getByTestId("payload-body")).toContainText("found 1 issue");
  });

  test("the review event is never a verdict", async ({ page }) => {
    // REQUEST_CHANGES or APPROVE would be the tool deciding; it may not.
    await page.goto(`/#/runs/${RUN_ID}/review`);
    await expect(page.getByTestId("review-view")).toContainText("event COMMENT");
  });

  test("a run that was not reviewed says so instead of showing empty panels", async ({
    page,
  }) => {
    await mockApi(page, { withReview: false });
    await page.goto(`/#/runs/${RUN_ID}/review`);
    await expect(page.getByTestId("empty-state")).toContainText("was not reviewed");
  });
});

test.describe("findings and run detail", () => {
  test.beforeEach(({ page }) => mockApi(page));

  test("findings show validation status and whether the change introduced them", async ({
    page,
  }) => {
    await page.goto(`/#/runs/${RUN_ID}/findings`);
    const view = page.getByTestId("findings-view");
    await expect(view).toContainText("F-0001");
    await expect(view).toContainText("validated");
    await expect(view).toContainText("introduced");
  });

  test("run detail exposes the receipts that make facts facts", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/detail`);
    const view = page.getByTestId("detail-view");
    await expect(view).toContainText("cargo-metadata");
    await expect(view).toContainText("cargo metadata --format-version 1 --locked");
    await expect(view).toContainText("base graph");
  });
});
