// One-off: the W-phase live-verify screenshots against run 3 of sharkdp/fd.
import { mkdirSync } from "node:fs";
import { chromium } from "@playwright/test";

const OUT = "C:/CodeAtlas/review-artifacts/w-phase";
mkdirSync(OUT, { recursive: true });

const RUN3 = "01KZEH7ADSXFGB554QWBVTMZEG";

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 1200 } });

// 1. The funnel with the suppressed row and its remembered reason.
await page.goto(`http://127.0.0.1:4173/#/runs/${RUN3}/review`);
await page.waitForTimeout(2500);
await page.screenshot({
  path: `${OUT}/funnel-suppressed.png`,
  clip: { x: 300, y: 0, width: 1300, height: 1100 },
});

// 2. A module page with the measured interface badge and pub marks.
await page.goto(`http://127.0.0.1:4173/#/runs/${RUN3}/module/src/exec/job.rs`);
await page.waitForTimeout(2500);
await page.screenshot({
  path: `${OUT}/module-depth.png`,
  clip: { x: 300, y: 0, width: 1300, height: 900 },
});

await browser.close();
console.log("shots written");
