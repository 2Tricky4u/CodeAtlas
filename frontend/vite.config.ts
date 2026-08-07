import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Where the read-only API is listening. Overridable because 8000 is often
// already taken on a developer machine, and a hardcoded port turns that into a
// blank dashboard with no explanation.
const API = process.env.CODEATLAS_API ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": API } },
  // `preview` serves the production build and does not inherit the dev proxy,
  // so a built dashboard pointed at a real API needs its own.
  preview: { proxy: { "/api": API } },
  test: {
    // Unit tests only. Left to its default glob, vitest also collects
    // `e2e/*.spec.ts` and fails on Playwright's `test.describe`.
    // Component tests are .test.tsx and opt into jsdom per-file via
    // `// @vitest-environment jsdom`; pure logic tests stay in node.
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
