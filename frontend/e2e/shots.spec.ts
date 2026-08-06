// Screenshot capture for visual review. Not assertions — whether the interface
// reads well is a judgement, and this is what makes it possible to make it.
// Run with: npx playwright test shots --reporter=line

import { test, type Page } from "@playwright/test";
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

async function mockApi(page: Page) {
  await page.route("**/api/runs", (route) => route.fulfill({ json: [RUN] }));
  await page.route(`**/api/runs/${RUN_ID}`, (route) => route.fulfill({ json: DETAIL }));
  await page.route(`**/api/runs/${RUN_ID}/overview`, (route) => route.fulfill({ json: OVERVIEW }));
  await page.route(`**/api/runs/${RUN_ID}/views`, (route) => route.fulfill({ json: VIEWS }));
  await page.route(`**/api/runs/${RUN_ID}/graph`, (route) => route.fulfill({ json: GRAPH }));
  await page.route(`**/api/runs/${RUN_ID}/findings`, (route) => route.fulfill({ json: FINDINGS }));
  await page.route("**/api/source/**", (route) => route.fulfill({ json: SOURCE }));
  await page.route(`**/api/runs/${RUN_ID}/artifact/graph-diff`, (r) => r.fulfill({ json: DIFF }));
  await page.route(`**/api/runs/${RUN_ID}/artifact/api-change`, (r) => r.fulfill({ json: API_CHANGE }));
  await page.route(`**/api/runs/${RUN_ID}/artifact/change-impact`, (r) => r.fulfill({ json: IMPACT }));
  await page.route(`**/api/runs/${RUN_ID}/artifact/change-explanation`, (r) =>
    r.fulfill({ json: EXPLANATION }),
  );
  void HEAD;
}

test.use({ viewport: { width: 1440, height: 900 } });

for (const tab of ["overview", "change", "map", "findings", "detail"]) {
  test(`shot ${tab}`, async ({ page }) => {
    await mockApi(page);
    await page.goto(`/#/runs/${RUN_ID}/${tab}`);
    await page.waitForTimeout(900);
    await page.screenshot({ path: `../var/ui-shots/${tab}.png`, fullPage: false });
  });
}
