import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  use: {
    baseURL: "http://127.0.0.1:4173",
  },
  webServer: {
    // Build first: `vite preview` serves whatever dist/ holds, and a stale
    // build makes the suite green against code that is not under test.
    // `reuseExistingServer` stays true because the live flow starts its own
    // preview (with CODEATLAS_API set) before running the live spec.
    command: "npm run build && npx vite preview --host 127.0.0.1 --port 4173 --strictPort",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: true,
    timeout: 120_000,
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
