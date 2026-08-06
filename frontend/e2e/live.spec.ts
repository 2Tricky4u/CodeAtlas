// Screenshots against a REAL run served by the read-only API — no mocks.
//
// Everything else in this directory route-mocks the API, which proves the
// interface renders but says nothing about whether it holds up at the size of
// an actual project. Run the pipeline, start `codeatlas serve`, then:
//
//   CODEATLAS_RUN=<run id> npx playwright test live --reporter=line
//
// Skipped when CODEATLAS_RUN is unset, so it never blocks the normal suite.

import { expect, test } from "@playwright/test";

const RUN = process.env.CODEATLAS_RUN;

test.describe("live", () => {
  test.skip(!RUN, "set CODEATLAS_RUN to a run id served by `codeatlas serve`");
  test.use({ viewport: { width: 1600, height: 1000 } });

  test("overview", async ({ page }) => {
    await page.goto(`/#/runs/${RUN}/overview`);
    await expect(page.getByTestId("overview-view")).toBeVisible();
    await page.waitForTimeout(600);
    await page.screenshot({ path: "../var/ui-shots/live-overview.png" });
  });

  test("map at package level", async ({ page }) => {
    await page.goto(`/#/runs/${RUN}/map`);
    await expect(page.locator('[data-testid="graph"] canvas').first()).toBeVisible();
    await page.waitForTimeout(1200);
    await page.screenshot({ path: "../var/ui-shots/live-map-packages.png" });
  });

  test("map: the densest package", async ({ page }) => {
    await page.goto(`/#/runs/${RUN}/map`);
    await page.getByRole("button", { name: /ignore modules by level/ }).click();
    await page.waitForTimeout(1200);
    await page.screenshot({ path: "../var/ui-shots/live-map-ignore.png" });
  });

  test("map: a clean package draws no edges at all", async ({ page }) => {
    await page.goto(`/#/runs/${RUN}/map`);
    await page.getByRole("button", { name: /grep-regex modules by level/ }).click();
    await page.waitForTimeout(1200);
    await page.screenshot({ path: "../var/ui-shots/live-map-clean.png" });
  });

  test("matrix at full size", async ({ page }) => {
    await page.goto(`/#/runs/${RUN}/map`);
    await page.getByRole("button", { name: /dependency matrix/ }).click();
    await page.waitForTimeout(800);
    await page.screenshot({ path: "../var/ui-shots/live-matrix.png" });
  });

  test("architecture", async ({ page }) => {
    await page.goto(`/#/runs/${RUN}/architecture`);
    await expect(page.getByTestId("architecture-graph")).toBeVisible();
    await page.waitForTimeout(1200);
    await page.screenshot({ path: "../var/ui-shots/live-architecture.png" });
  });

  test("decisions", async ({ page }) => {
    await page.goto(`/#/runs/${RUN}/adr`);
    await expect(page.getByTestId("adr-view")).toBeVisible();
    await page.waitForTimeout(500);
    await page.screenshot({ path: "../var/ui-shots/live-adr.png" });
  });

  test("protocol", async ({ page }) => {
    await page.goto(`/#/runs/${RUN}/protocol`);
    await expect(page.getByTestId("protocol-view")).toBeVisible();
    await page.waitForTimeout(600);
    await page.screenshot({ path: "../var/ui-shots/live-protocol.png" });
  });

  test("focus on a real symbol", async ({ page }) => {
    await page.goto(`/#/runs/${RUN}/map`);
    await page.getByTestId("focus-tab").click();
    await page.getByTestId("focus-search").fill("Searcher");
    // The type, not the module of the same name — a symbol with a real
    // neighbourhood is what makes the 1-hop view worth judging.
    await page.getByTestId("focus-match").filter({ hasText: "type · Searcher" }).first().click();
    await expect(page.locator('[data-testid="focus-graph"] canvas').first()).toBeVisible();
    await page.waitForTimeout(1200);
    await page.screenshot({ path: "../var/ui-shots/live-focus.png" });
  });
});
