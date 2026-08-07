// Dashboard e2e. The assertions are about what a reader can *learn* from the
// page — before/after, what else could break, why a view is missing — not about
// pixels. API responses are route-mocked with payloads shaped exactly like the
// real API; the Python contract tests pin those shapes against the schemas.

import { expect, test, type Page } from "@playwright/test";
import {
  ADR_AUDIT,
  API_CHANGE,
  APPROVALS,
  APPROVALS_DECIDED,
  ARCHITECTURE,
  CANDIDATE_FINDINGS,
  DETAIL,
  DETAIL2,
  INTENT,
  REVIEW_MARKDOWN,
  REVIEW_PAYLOAD,
  DIFF,
  EXPLANATION,
  FINDINGS,
  GRAPH,
  GRAPH2,
  HEAD,
  IMPACT,
  OVERVIEW,
  OVERVIEW2,
  PROJECT_EXPLANATION,
  PROTOCOL_MODEL,
  PROTOCOL_NONE,
  PROTOCOL_SEQUENCE,
  PUBLICATION_PUBLISHED,
  RUN,
  RUN2,
  RUN_ID,
  RUN_ID_2,
  SOURCE,
  STRUCTURIZR_DSL,
  VIEWS,
  VIEWS2,
} from "./fixtures";

async function mockApi(
  page: Page,
  options: { withChange?: boolean; withNarrative?: boolean; withReview?: boolean } = {},
) {
  const withChange = options.withChange ?? true;
  const withNarrative = options.withNarrative ?? true;
  const withReview = options.withReview ?? true;
  await page.route("**/api/runs", (route) => route.fulfill({ json: [RUN, RUN2] }));

  // The second run: repository kind, big module, no artifacts. Routed first so
  // a test can shadow any run-1 route (LIFO) without touching run 2.
  await page.route(`**/api/runs/${RUN_ID_2}`, (route) => route.fulfill({ json: DETAIL2 }));
  await page.route(`**/api/runs/${RUN_ID_2}/overview`, (route) =>
    route.fulfill({ json: OVERVIEW2 }),
  );
  await page.route(`**/api/runs/${RUN_ID_2}/views`, (route) => route.fulfill({ json: VIEWS2 }));
  await page.route(`**/api/runs/${RUN_ID_2}/graph`, (route) => route.fulfill({ json: GRAPH2 }));
  await page.route(`**/api/runs/${RUN_ID_2}/findings`, (route) => route.fulfill({ json: [] }));
  await page.route(`**/api/runs/${RUN_ID_2}/artifact/**`, (route) =>
    route.fulfill({ status: 404, json: { detail: "none" } }),
  );
  await page.route(`**/api/runs/${RUN_ID_2}/approval`, (route) => route.fulfill({ json: [] }));

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
  await page.route(`**/api/runs/${RUN_ID}/publications`, (route) => route.fulfill({ json: [] }));
  await page.route(`**/api/runs/${RUN_ID_2}/publications`, (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route(`**/api/runs/${RUN_ID}/answers`, (route) => route.fulfill({ json: [] }));
  await page.route(`**/api/runs/${RUN_ID_2}/answers`, (route) => route.fulfill({ json: [] }));
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
    await expect(start).toContainText("most depended on");
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

test.describe("command palette", () => {
  test.beforeEach(({ page }) => mockApi(page));

  test("ctrl-k opens it from any tab; a symbol lands on its definition", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/findings`);
    // The listener mounts with the run layout; pressing before hydration is a no-op.
    await expect(page.getByTestId("findings-view")).toBeVisible();
    await page.keyboard.press("Control+k");
    await expect(page.getByTestId("palette")).toBeVisible();
    await page.getByTestId("palette-input").fill("evict");
    await page.getByTestId("palette-match").first().click();
    await expect(page.getByTestId("module-view")).toBeVisible();
    await expect(page).toHaveURL(/symbol=/);
  });

  test("no match is stated, and escape closes", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/overview`);
    await expect(page.getByTestId("overview-view")).toBeVisible();
    await page.keyboard.press("Control+k");
    await expect(page.getByTestId("palette")).toBeVisible();
    await page.getByTestId("palette-input").fill("zzghost");
    await expect(page.getByTestId("palette")).toContainText("nothing in this run's graph");
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("palette")).toHaveCount(0);
  });
});

test.describe("reading order", () => {
  test.beforeEach(({ page }) => mockApi(page));

  test("a start-here module knows its step and where the walk goes", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/module/kvstore/src/cache.rs`);
    const order = page.getByTestId("reading-order");
    await expect(order).toContainText("2 of 2");
    await expect(order).toContainText("most depended on");
    await expect(page.getByTestId("reading-prev")).toContainText("lib.rs");
  });

  test("a module outside the walk shows no step", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/module/kvstore/src/api.rs`);
    await expect(page.getByTestId("module-view")).toBeVisible();
    await expect(page.getByTestId("reading-order")).toHaveCount(0);
  });
});

test.describe("ask about this module", () => {
  test.beforeEach(({ page }) => mockApi(page));

  test("an answer renders as checkable claims, not just prose", async ({ page }) => {
    await page.route(`**/api/runs/${RUN_ID}/ask`, (route) =>
      route.fulfill({
        json: {
          question: "what does eviction remove?",
          scope: "kvstore/src/cache.rs",
          answer: "One more than asked for.",
          claims: [
            {
              text: "The loop is 0..=n, removing n+1 entries.",
              citations: [
                { kind: "source", path: "kvstore/src/cache.rs", startLine: 41, endLine: 48 },
              ],
            },
          ],
          refused: null,
          droppedClaims: [
            { sectionId: "answer", text: "Invented.", reason: "did not resolve" },
          ],
          cached: false,
        },
      }),
    );
    await page.goto(`/#/runs/${RUN_ID}/module/kvstore/src/cache.rs`);
    await page.getByTestId("ask-input").fill("what does eviction remove?");
    await page.getByTestId("ask-submit").click();
    await expect(page.getByTestId("ask-claims")).toContainText("0..=n");
    await expect(page.getByTestId("ask-citation")).toContainText("cache.rs:41");
    await expect(page.getByTestId("ask-dropped")).toContainText("1 statement(s)");
  });

  test("a refusal renders as an answer, not an error", async ({ page }) => {
    await page.route(`**/api/runs/${RUN_ID}/ask`, (route) =>
      route.fulfill({
        json: {
          question: "is it fast?",
          scope: "kvstore/src/cache.rs",
          answer: null,
          claims: [],
          refused: "performance is a measurement, not readable from this file",
          cached: false,
        },
      }),
    );
    await page.goto(`/#/runs/${RUN_ID}/module/kvstore/src/cache.rs`);
    await page.getByTestId("ask-input").fill("is it fast?");
    await page.getByTestId("ask-submit").click();
    await expect(page.getByTestId("ask-refused")).toContainText("measurement");
  });

  test("a server without asking enabled says how to enable it", async ({ page }) => {
    await page.route(`**/api/runs/${RUN_ID}/ask`, (route) =>
      route.fulfill({
        status: 403,
        json: { detail: "asking is not enabled on this server; start it with --ask" },
      }),
    );
    await page.goto(`/#/runs/${RUN_ID}/module/kvstore/src/cache.rs`);
    await page.getByTestId("ask-input").fill("why?");
    await page.getByTestId("ask-submit").click();
    await expect(page.getByTestId("ask-error")).toContainText("--ask");
  });
});

test.describe("linked source", () => {
  test.beforeEach(({ page }) => mockApi(page));

  test("a line that defines a measured symbol links to it, with its fan-in", async ({
    page,
  }) => {
    await page.goto(`/#/runs/${RUN_ID}/module/kvstore/src/cache.rs`);
    await page.getByRole("button", { name: "open source" }).click();
    const marker = page.getByTestId("source-symbol").first();
    await expect(marker).toBeVisible();
    await expect(marker).toContainText("←");
    await expect(page.getByTestId("source-link-note")).toContainText("plain text");
  });
});

test.describe("path-finding", () => {
  test.beforeEach(({ page }) => mockApi(page));

  test("A to B draws the dependency chain with its edge kinds", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/map`);
    await page.getByTestId("path-tab").click();
    await page.getByTestId("path-from").fill("put");
    await page.getByTestId("path-from-match").first().click();
    await page.getByTestId("path-to").fill("evict");
    await page.getByTestId("path-to-match").first().click();
    await expect(page.getByTestId("path-summary")).toContainText("1 hop(s)");
    await expect(page.locator('[data-testid="path-graph"] canvas').first()).toBeVisible();
  });

  test("no path is an answer, not an empty canvas", async ({ page }) => {
    // handle_request and evict_oldest live in different components: nothing
    // connects the api chain to the cache chain in this fixture.
    await page.goto(`/#/runs/${RUN_ID}/map`);
    await page.getByTestId("path-tab").click();
    await page.getByTestId("path-from").fill("handle");
    await page.getByTestId("path-from-match").first().click();
    await page.getByTestId("path-to").fill("evict");
    await page.getByTestId("path-to-match").first().click();
    await expect(page.getByTestId("no-path")).toContainText("nothing in this graph connects");
  });

  test("an endpoint that cannot start a path is never offered", async ({ page }) => {
    // evict depends on nothing; offering it as a start guarantees failure
    // before the search begins, so the picker refuses it up front.
    await page.goto(`/#/runs/${RUN_ID}/map`);
    await page.getByTestId("path-tab").click();
    await page.getByTestId("path-from").fill("evict");
    await expect(page.getByTestId("path-from-match")).toHaveCount(0);
  });

  test("nothing is drawn until both ends are named", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/map`);
    await page.getByTestId("path-tab").click();
    await expect(page.getByTestId("empty-state")).toContainText("name both ends");
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

test.describe("error surfaces", () => {
  // A 500 and a 404 are different facts: "this run has none" versus "the
  // server broke". Every case here pins that a break is *shown*, because a
  // break rendered as absence is a silent failure wearing a state's costume.
  test.beforeEach(({ page }) => mockApi(page));

  test("a failing run list is an error, not an empty sidebar", async ({ page }) => {
    await page.route("**/api/runs", (route) =>
      route.fulfill({ status: 500, json: { detail: "boom" } }),
    );
    await page.goto("/");
    await expect(page.getByRole("alert")).toBeVisible();
  });

  test("no runs at all is stated", async ({ page }) => {
    await page.route("**/api/runs", (route) => route.fulfill({ json: [] }));
    await page.goto("/");
    await expect(page.getByTestId("runs-list")).toContainText("no runs yet");
  });

  test("a failing overview shows the error", async ({ page }) => {
    await page.route(`**/api/runs/${RUN_ID}/overview`, (route) =>
      route.fulfill({ status: 500, json: { detail: "boom" } }),
    );
    await page.goto(`/#/runs/${RUN_ID}/overview`);
    await expect(page.getByRole("alert")).toBeVisible();
  });

  test("a failing views payload shows the error on the map", async ({ page }) => {
    await page.route(`**/api/runs/${RUN_ID}/views`, (route) =>
      route.fulfill({ status: 500, json: { detail: "boom" } }),
    );
    await page.goto(`/#/runs/${RUN_ID}/map`);
    await expect(page.getByRole("alert")).toBeVisible();
  });

  test("a broken DSL artifact is an error, not a missing document", async ({ page }) => {
    await page.route(`**/api/runs/${RUN_ID}/artifact/structurizr-dsl`, (route) =>
      route.fulfill({ status: 500, body: "boom", headers: { "content-type": "text/plain" } }),
    );
    await page.goto(`/#/runs/${RUN_ID}/architecture`);
    await expect(page.getByRole("alert")).toBeVisible();
  });

  test("a broken review markdown is an error, not an unreviewed run", async ({ page }) => {
    await page.route(`**/api/runs/${RUN_ID}/artifact/review-markdown`, (route) =>
      route.fulfill({ status: 500, body: "boom", headers: { "content-type": "text/plain" } }),
    );
    await page.goto(`/#/runs/${RUN_ID}/review`);
    await expect(page.getByRole("alert")).toBeVisible();
  });

  test("a protocol artifact that does not exist reads as not-modelled", async ({ page }) => {
    // Distinct from PROTOCOL_NONE (an artifact saying "no protocol"): here the
    // run never produced the artifact at all.
    await page.route(`**/api/runs/${RUN_ID}/artifact/protocol-model`, (route) =>
      route.fulfill({ status: 404, json: { detail: "none" } }),
    );
    await page.goto(`/#/runs/${RUN_ID}/protocol`);
    await expect(page.getByTestId("empty-state")).toContainText("did not model a protocol");
  });
});

test.describe("switching runs", () => {
  test.beforeEach(({ page }) => mockApi(page));

  test("run A's map error does not follow the reader to run B", async ({ page }) => {
    await page.route(`**/api/runs/${RUN_ID}/views`, (route) =>
      route.fulfill({ status: 500, json: { detail: "boom" } }),
    );
    await page.goto(`/#/runs/${RUN_ID}/map`);
    await expect(page.getByRole("alert")).toBeVisible();
    await page.goto(`/#/runs/${RUN_ID_2}/map`);
    await expect(page.locator('[data-testid="graph"] canvas').first()).toBeVisible();
    await expect(page.getByRole("alert")).toHaveCount(0);
  });

  test("run A's protocol error does not become run B's protocol", async ({ page }) => {
    await page.route(`**/api/runs/${RUN_ID}/artifact/protocol-model`, (route) =>
      route.fulfill({ status: 500, json: { detail: "boom" } }),
    );
    await page.goto(`/#/runs/${RUN_ID}/protocol`);
    await expect(page.getByRole("alert")).toBeVisible();
    await page.goto(`/#/runs/${RUN_ID_2}/protocol`);
    await expect(page.getByTestId("empty-state")).toContainText("did not model a protocol");
    await expect(page.getByRole("alert")).toHaveCount(0);
  });
});

test.describe("flows on the page", () => {
  test.beforeEach(({ page }) => mockApi(page));

  test("the overview draws the entry-point flow with its measured hops", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/overview`);
    const flow = page.getByTestId("flow").first();
    await expect(flow).toBeVisible();
    await expect(flow).toContainText("3 modules");
    await expect(flow).toContainText("2 hop(s)");
  });

  test("a module the flow does not pass through says so", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/module/kvstore/src/cache.rs`);
    await expect(page.getByTestId("no-flows")).toContainText("passes through here");
  });

  test("a graph fetch failure is an error, not a silently absent panel", async ({ page }) => {
    await page.route(`**/api/runs/${RUN_ID}/graph`, (route) =>
      route.fulfill({ status: 500, json: { detail: "boom" } }),
    );
    await page.goto(`/#/runs/${RUN_ID}/overview`);
    await expect(page.getByTestId("flows-error")).toBeVisible();
  });

  test("a walk past the cap states its remainder", async ({ page }) => {
    // RUN2's entry chain crosses 17 modules; the walk stops at 14 steps and
    // must say the chain continues — the disclosure flows.ts promises.
    await page.goto(`/#/runs/${RUN_ID_2}/overview`);
    await expect(page.getByTestId("flow-truncated")).toContainText("continues");
  });
});

test.describe("the module page at scale", () => {
  test.beforeEach(({ page }) => mockApi(page));

  const BIG = `/#/runs/${RUN_ID_2}/module/big/src/lib.rs`;

  test("types come first and fan-in ranks within a kind", async ({ page }) => {
    await page.goto(BIG);
    const definitions = page.getByTestId("definition");
    // Alpha (fan-in 26) leads the types; f13 (called by three siblings) leads
    // the functions, ahead of the alphabet: positions 0-3 types, 4-15 the
    // first twelve constants, 16 the top-ranked function.
    await expect(definitions.nth(0)).toHaveText("Alpha");
    await expect(definitions.nth(16)).toHaveText("f13");
  });

  test("a large kind collapses to its most-used members, expandable", async ({ page }) => {
    await page.goto(BIG);
    await expect(page.getByTestId("definition")).toHaveCount(4 + 12 + 12);
    await page
      .getByTestId("show-all-definitions")
      .filter({ hasText: "14 less-used function" })
      .click();
    await expect(page.getByTestId("definition")).toHaveCount(4 + 12 + 26);
  });

  test("a symbol deep link expands its own group and only its own", async ({ page }) => {
    await page.goto(`${BIG}?symbol=${encodeURIComponent("sym2:f20")}`);
    await expect(page.getByTestId("definition").filter({ hasText: "f20" })).toBeVisible();
    // The constants group (13 > GROUP_LIMIT) stays collapsed: exactly one
    // show-all button remains, and it is not the functions'.
    await expect(page.getByTestId("show-all-definitions")).toHaveCount(1);
    await expect(page.getByTestId("show-all-definitions")).toContainText("constant");
  });

  test("the public-surface panel names this file's items, not substrings", async ({ page }) => {
    // Back on run 1: the API delta contains compute_output, which contains
    // `put` — cache.rs must claim evict_oldest and not compute_output.
    await page.goto(`/#/runs/${RUN_ID}/module/kvstore/src/cache.rs`);
    const apiHere = page.getByTestId("api-here");
    await expect(apiHere).toContainText("evict_oldest");
    await expect(apiHere).not.toContainText("compute_output");
  });
});

test.describe("ask, continued", () => {
  test.beforeEach(({ page }) => mockApi(page));

  test("enter submits; a cached answer and a module citation both render", async ({ page }) => {
    await page.route(`**/api/runs/${RUN_ID}/ask`, (route) =>
      route.fulfill({
        json: {
          question: "who calls put?",
          scope: "kvstore/src/cache.rs",
          answer: "Only the request handler.",
          claims: [
            {
              text: "handle_request is the sole caller.",
              citations: [{ kind: "module", key: "kvstore/src/api.rs" }],
            },
          ],
          refused: null,
          droppedClaims: [],
          cached: true,
        },
      }),
    );
    await page.goto(`/#/runs/${RUN_ID}/module/kvstore/src/cache.rs`);
    await page.getByTestId("ask-input").fill("who calls put?");
    await page.getByTestId("ask-input").press("Enter");
    await expect(page.getByTestId("ask-answer")).toContainText("cached");
    await expect(page.getByTestId("ask-claims")).toContainText("kvstore/src/api.rs");
  });

  test("an unreachable server is said in words", async ({ page }) => {
    await page.route(`**/api/runs/${RUN_ID}/ask`, (route) => route.abort());
    await page.goto(`/#/runs/${RUN_ID}/module/kvstore/src/cache.rs`);
    await page.getByTestId("ask-input").fill("why?");
    await page.getByTestId("ask-submit").click();
    await expect(page.getByTestId("ask-error")).toContainText("could not reach the server");
  });

  test("questions answered before are listed for this module, and reopen free", async ({
    page,
  }) => {
    // The cache is content-addressed by question; without this list, asking
    // twice is only free if you retype the question verbatim from memory.
    await page.route(`**/api/runs/${RUN_ID}/answers`, (route) =>
      route.fulfill({
        json: [
          {
            question: "what does eviction remove?",
            scope: "kvstore/src/cache.rs",
            answer: "One more than asked for.",
            claims: [
              {
                text: "The loop is 0..=n.",
                citations: [{ kind: "source", path: "kvstore/src/cache.rs", startLine: 41 }],
              },
            ],
            refused: null,
          },
          {
            question: "who parses requests?",
            scope: "kvstore/src/api.rs",
            answer: "parse.",
            claims: [],
            refused: null,
          },
        ],
      }),
    );
    await page.goto(`/#/runs/${RUN_ID}/module/kvstore/src/cache.rs`);
    const history = page.getByTestId("ask-history");
    // Scoped to this module: the api.rs question must not appear here.
    await expect(history).toContainText("what does eviction remove?");
    await expect(history).not.toContainText("who parses requests?");
    await page.getByTestId("ask-history-item").click();
    await expect(page.getByTestId("ask-answer")).toContainText("cached");
    await expect(page.getByTestId("ask-claims")).toContainText("0..=n");
  });

  test("a module with no prior questions shows no history", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/module/kvstore/src/cache.rs`);
    await expect(page.getByTestId("ask-input")).toBeVisible();
    await expect(page.getByTestId("ask-history")).toHaveCount(0);
  });
});

test.describe("palette by keyboard", () => {
  test.beforeEach(({ page }) => mockApi(page));

  test("arrows and enter select without a mouse", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/overview`);
    await expect(page.getByTestId("overview-view")).toBeVisible();
    await page.keyboard.press("Control+k");
    await page.getByTestId("palette-input").fill("evict");
    await expect(page.getByTestId("palette-match").first()).toBeVisible();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("module-view")).toBeVisible();
    await expect(page).toHaveURL(/symbol=/);
  });

  test("ctrl-k toggles closed again", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/overview`);
    await expect(page.getByTestId("overview-view")).toBeVisible();
    await page.keyboard.press("Control+k");
    await expect(page.getByTestId("palette")).toBeVisible();
    await page.keyboard.press("Control+k");
    await expect(page.getByTestId("palette")).toHaveCount(0);
  });
});

test.describe("matrix semantics", () => {
  test.beforeEach(({ page }) => mockApi(page));

  test("a cell reads row-depends-on-column, with the measured weight", async ({ page }) => {
    // The one assertion that would catch a transposed matrix: the fixture's
    // edge is api.rs -> cache.rs, so the readout must name them in that order.
    await page.goto(`/#/runs/${RUN_ID}/map`);
    await page.getByRole("button", { name: /dependency matrix/ }).click();
    await page.getByTestId("matrix-hit").hover();
    const readout = page.getByTestId("matrix-readout");
    await expect(readout).toContainText("kvstore/src/api.rs");
    await expect(readout).toContainText("kvstore/src/cache.rs");
    await expect(readout).toContainText("2 reference(s)");
  });
});

test.describe("focus at scale", () => {
  test.beforeEach(({ page }) => mockApi(page));

  test("a neighbourhood past the cap says how much is not drawn", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID_2}/map`);
    await page.getByTestId("focus-tab").click();
    await page.getByTestId("focus-search").fill("Alpha");
    await page.getByTestId("focus-match").filter({ hasText: "type · Alpha" }).first().click();
    // 26 readers plus the containing file: 27 neighbours, 24 drawn.
    await expect(page.getByTestId("focus-truncated")).toContainText("24 of 27");
  });
});

test.describe("one graph fetch per run", () => {
  test.beforeEach(({ page }) => mockApi(page));

  test("module pages, the path view and focus mode share one payload", async ({ page }) => {
    // The live suite pins this against ripgrep; this pins it in the default
    // loop, where the regression would otherwise hide until a live run.
    let graphFetches = 0;
    page.on("request", (request) => {
      if (request.url().includes(`/api/runs/${RUN_ID}/graph`)) graphFetches += 1;
    });
    await page.goto(`/#/runs/${RUN_ID}/module/kvstore/src/cache.rs`);
    await expect(page.getByTestId("module-view")).toBeVisible();
    await page.goto(`/#/runs/${RUN_ID}/module/kvstore/src/api.rs`);
    await expect(page.getByTestId("module-view")).toBeVisible();
    await page.goto(`/#/runs/${RUN_ID}/map`);
    await page.getByTestId("path-tab").click();
    await expect(page.getByTestId("path-from")).toBeVisible();
    await page.getByTestId("focus-tab").click();
    await page.getByTestId("focus-search").fill("evict");
    await expect(page.getByTestId("focus-match").first()).toBeVisible();
    expect(graphFetches).toBe(1);
  });
});

test.describe("publication truth", () => {
  // The one screen about the approval gate must report what the gate actually
  // did — not hard-code an outcome.
  test.beforeEach(({ page }) => mockApi(page));

  test("an approved run reads as approved, not rejected", async ({ page }) => {
    // The CLI stores exactly "approved"; a comparison against "approve"
    // rendered every real approval with the red rejected badge.
    await page.route(`**/api/runs/${RUN_ID}/approval`, (route) =>
      route.fulfill({ json: APPROVALS_DECIDED }),
    );
    await page.goto(`/#/runs/${RUN_ID}/review`);
    const panel = page.getByTestId("approvals");
    await expect(panel).toContainText("approved");
    await expect(page.getByTestId("review-view")).not.toContainText("rejected");
  });

  test("a published run says so, with the posted review's address", async ({ page }) => {
    await page.route(`**/api/runs/${RUN_ID}/approval`, (route) =>
      route.fulfill({ json: APPROVALS_DECIDED }),
    );
    await page.route(`**/api/runs/${RUN_ID}/publications`, (route) =>
      route.fulfill({ json: PUBLICATION_PUBLISHED }),
    );
    await page.goto(`/#/runs/${RUN_ID}/review`);
    const status = page.getByTestId("publication-status");
    await expect(status).toContainText("published");
    await expect(status).toContainText("pullrequestreview-9");
    // The shadow-mode sentence would now be a false statement.
    await expect(page.getByTestId("review-view")).not.toContainText("nothing was sent");
  });

  test("an unpublished run keeps the shadow-mode statement", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/review`);
    await expect(page.getByTestId("approval-note")).toContainText("nothing was sent");
  });
});

test.describe("path view failure", () => {
  test.beforeEach(({ page }) => mockApi(page));

  test("a graph that cannot load is an error, not eternal loading", async ({ page }) => {
    await page.route(`**/api/runs/${RUN_ID}/graph`, (route) =>
      route.fulfill({ status: 500, json: { detail: "boom" } }),
    );
    await page.goto(`/#/runs/${RUN_ID}/map`);
    await page.getByTestId("path-tab").click();
    await expect(page.getByRole("alert")).toBeVisible();
    await expect(page.getByText("loading the graph…")).toHaveCount(0);
  });
});
