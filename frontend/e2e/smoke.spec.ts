// Dashboard e2e. The assertions are about what a reader can *learn* from the
// page — before/after, what else could break, why a view is missing — not about
// pixels. API responses are route-mocked with payloads shaped exactly like the
// real API; the Python contract tests pin those shapes against the schemas.

import { expect, test, type Page } from "@playwright/test";
import {
  API_CHANGE,
  DETAIL,
  DIFF,
  EXPLANATION,
  FINDINGS,
  GRAPH,
  HEAD,
  IMPACT,
  OVERVIEW,
  RUN,
  RUN_ID,
  SOURCE,
  VIEWS,
} from "./fixtures";

async function mockApi(page: Page, options: { withChange?: boolean } = {}) {
  const withChange = options.withChange ?? true;
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

  test("clicking a suggestion opens its pinned source", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/overview`);
    await page.getByRole("button", { name: "kvstore/src/cache.rs" }).first().click();
    await expect(page.getByTestId("source-panel")).toContainText("pub fn evict");
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

  test("nothing is drawn until the reader names something", async ({ page }) => {
    await page.goto(`/#/runs/${RUN_ID}/map`);
    await page.getByTestId("focus-tab").click();
    await expect(page.getByText(/the whole graph is never rendered/)).toBeVisible();
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
