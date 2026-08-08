// Screenshot capture for visual review. Not assertions — whether the interface
// reads well is a judgement, and this is what makes it possible to make it.
// Run with: npx playwright test shots --reporter=line

import { readdirSync, readFileSync } from "node:fs";
import { test, type Page } from "@playwright/test";
import {
  API_CHANGE,
  DETAIL,
  DIFF,
  EXPLANATION,
  FINDINGS,
  GRAPH,
  IMPACT,
  OVERVIEW,
  RUN,
  RUN_ID,
  SOURCE,
  THREAT_MODEL,
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
  // The *recorded* narrative, not the trimmed fixture: 27 claims over five
  // sections is what a real one looks like, and a panel that reads well with
  // two claims can still be unusable with that many.
  await page.route(`**/api/runs/${RUN_ID}/artifact/project-explanation`, (r) =>
    r.fulfill({ json: recordedNarrative() }),
  );
  await page.route(`**/api/runs/${RUN_ID}/artifact/threat-model`, (r) =>
    r.fulfill({ json: THREAT_MODEL }),
  );
}

function recordedNarrative(): unknown {
  // Found by prefix, not by full name: the cassette's filename carries a hash
  // of its inputs, so pinning it here would break on every re-record.
  const dir = new URL("../../tests/cassettes/", import.meta.url);
  const name = readdirSync(dir).find((f) => f.startsWith("project-explainer-"));
  if (!name) throw new Error("no project-explainer cassette recorded");
  return JSON.parse(readFileSync(new URL(name, dir), "utf8")).result.output;
}

test.use({ viewport: { width: 1440, height: 900 } });

test("shot narrative expanded", async ({ page }) => {
  await mockApi(page);
  await page.goto(`/#/runs/${RUN_ID}/overview`);
  await page.getByTestId("narrative-toggle").click();
  await page.waitForTimeout(400);
  await page.screenshot({ path: "../var/ui-shots/narrative.png", fullPage: true });
});

for (const tab of ["overview", "change", "map", "findings", "detail"]) {
  test(`shot ${tab}`, async ({ page }) => {
    await mockApi(page);
    await page.goto(`/#/runs/${RUN_ID}/${tab}`);
    await page.waitForTimeout(900);
    await page.screenshot({ path: `../var/ui-shots/${tab}.png`, fullPage: false });
  });
}

// The two README screenshots for the Z-phase threat model. Written straight to
// docs/screenshots because — unlike the live-data shots in readme-shots.mjs —
// these come from fixtures, so they are reproducible with `npx playwright test
// shots` and need no serve stack.
test("readme threats tab", async ({ page }) => {
  await mockApi(page);
  await page.goto(`/#/runs/${RUN_ID}/threats`);
  await page.waitForTimeout(700);
  await page.screenshot({ path: "../docs/screenshots/threats.png", fullPage: true });
});

test("readme attack path", async ({ page }) => {
  await mockApi(page);
  await page.goto(`/#/runs/${RUN_ID}/findings`);
  await page
    .locator("tr", { hasText: "FileStore::read joins an untrusted key" })
    .getByTestId("validation-toggle")
    .click();
  await page.getByTestId("attack-path").scrollIntoViewIfNeeded();
  await page.waitForTimeout(400);
  await page.screenshot({ path: "../docs/screenshots/attack-path.png", fullPage: false });
});
