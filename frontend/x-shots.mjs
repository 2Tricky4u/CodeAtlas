// One-off: the X-phase closing screenshots against the live fd run.
import { mkdirSync } from "node:fs";
import { chromium } from "@playwright/test";

const OUT = "C:/CodeAtlas/review-artifacts/x-phase";
mkdirSync(OUT, { recursive: true });

const RUN = "01KZF7NF3N1BC57ZH294FT7S8G";

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 1200 } });

// 1. The review tab: funnel + the measured coverage panel.
await page.goto(`http://127.0.0.1:4173/#/runs/${RUN}/review`);
await page.waitForTimeout(2500);
await page.screenshot({
  path: `${OUT}/coverage.png`,
  clip: { x: 300, y: 0, width: 1300, height: 1150 },
});

// 2. A hot module page: churn badge next to interface and fan-in.
await page.goto(`http://127.0.0.1:4173/#/runs/${RUN}/module/src/walk.rs`);
await page.waitForTimeout(2500);
await page.screenshot({
  path: `${OUT}/churn-module.png`,
  clip: { x: 300, y: 0, width: 1300, height: 700 },
});

// 3. The overview's most-changed table.
await page.goto(`http://127.0.0.1:4173/#/runs/${RUN}/overview`);
await page.waitForTimeout(2500);
const table = page.getByTestId("most-changed");
await table.scrollIntoViewIfNeeded();
await page.waitForTimeout(400);
await page.screenshot({
  path: `${OUT}/most-changed.png`,
  clip: { x: 300, y: 300, width: 1300, height: 900 },
});

await browser.close();
console.log("shots written");
