// One-off: the README's feature screenshots, against the live stack.
// Clips past the 300px run sidebar so each shot is the feature, not the shell.
import { mkdirSync } from "node:fs";
import { chromium } from "@playwright/test";

const OUT = "C:/CodeAtlas/docs/screenshots";
mkdirSync(OUT, { recursive: true });

const FD = "01KZD899YE568RMQ0A9GQWMA5S";
const RG = "01KZC99E1P67Q0Y3WMF3J7J3MA";
const REVIEWED = "01KZE0WK870NYNNAZ7T29RY273";
const PR = "01KZE0WZZYKVXNS1P0N1X8BKNM";
const ADR = "01KZC7Q5N271BQ5ZJAN4VGZKCN";

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 1200 } });
const go = async (path, wait = 2500) => {
  await page.goto(`http://127.0.0.1:4173/#/runs/${path}`);
  await page.waitForTimeout(wait);
};
const clipShot = (name, height, y = 0) =>
  page.screenshot({ path: `${OUT}/${name}.png`, clip: { x: 300, y, width: 1300, height } });

// 1. Hero: fd overview — stats, cited narrative, a real flow, start-here.
await go(`${FD}/overview`);
await clipShot("overview", 1180);

// 2. Files explorer.
await go(`${FD}/files`);
await clipShot("files", 1000);

// 3. Source viewer: Shiki + measured spans + fan-in badges.
await go(`${FD}/module/src/exec/job.rs`);
await page.getByRole("button", { name: "open source" }).click();
await page.waitForTimeout(2500);
await page.getByTestId("source-panel").scrollIntoViewIfNeeded();
await page.waitForTimeout(400);
const sourcePanel = page.locator(".panel", { hasText: "src/exec/job.rs" }).last();
await sourcePanel.screenshot({ path: `${OUT}/source.png` });

// 4. Module page at real size: ripgrep's walk.rs.
await go(`${RG}/module/crates/ignore/src/walk.rs`);
await clipShot("module", 1000);

// 5. Matrix.
await go(`${RG}/map`);
await page.getByRole("button", { name: /dependency matrix/ }).click();
await page.waitForTimeout(1200);
await clipShot("matrix", 1000);

// 6. Levelized package view.
await go(`${RG}/map`);
await page.getByRole("button", { name: /ignore modules by level/ }).click();
await page.waitForTimeout(1500);
await clipShot("map-levels", 1000);

// 7. Path finding.
await go(`${RG}/map`);
await page.getByTestId("path-tab").click();
await page.getByTestId("path-from").fill("search");
await page.getByTestId("path-from-match").filter({ hasText: "function · search" }).first().click();
await page.getByTestId("path-to").fill("byte");
await page.getByTestId("path-to-match").filter({ hasText: "function · byte" }).first().click();
await page.waitForTimeout(1500);
await clipShot("path", 1000);

// 8. Command palette.
await go(`${RG}/overview`, 1500);
await page.keyboard.press("Control+k");
await page.getByTestId("palette-input").fill("Walk");
await page.waitForTimeout(600);
await clipShot("palette", 700);
await page.keyboard.press("Escape");

// 9. Ask, from the cache: reopen fd's answered question.
await go(`${FD}/module/src/walk.rs`);
await page.getByTestId("ask-history-item").first().click();
await page.waitForTimeout(600);
const askPanel = page.locator(".panel", { hasText: "ask about this module" }).first();
await askPanel.screenshot({ path: `${OUT}/ask.png` });

// 10. Run detail: manifest + agent ledger.
await go(`${FD}/detail`);
await clipShot("provenance", 1180);

// 11. Review funnel on the replayed kvstore run.
await go(`${REVIEWED}/review`);
await clipShot("review", 1150);

// 12. Change view on the kvstore PR run.
await go(`${PR}/change`);
await clipShot("change", 1150);

// 13. Decisions.
await go(`${ADR}/adr`);
await clipShot("decisions", 1000);

// 14. Protocol refusal — the honest no.
await go(`${FD}/protocol`, 1500);
await clipShot("protocol-refusal", 620);

// 15. Architecture.
await go(`${RG}/architecture`);
await clipShot("architecture", 1000);

await browser.close();
console.log("all shots written");
