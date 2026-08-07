// The fetch helpers' error policy — the one place "absent" and "broken" are
// told apart. A 500 that renders as absence is a silent failure wearing the
// costume of a state, which is exactly what the backend's rules forbid.

import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";

const respond = (status: number, body: string, contentType = "application/json") =>
  vi.fn().mockResolvedValue(
    new Response(body, { status, headers: { "content-type": contentType } }),
  );

afterEach(() => vi.unstubAllGlobals());

describe("optional text artifacts (structurizr DSL, review markdown)", () => {
  it("404 means the run has none", async () => {
    vi.stubGlobal("fetch", respond(404, '{"detail":"none"}'));
    await expect(api.structurizrDsl("r1")).resolves.toBeNull();
  });

  it("a 500 is an error, not absence", async () => {
    // "this run has no architecture" and "the server broke" must never render
    // the same way; collapsing them hides a broken server as a missing artifact.
    vi.stubGlobal("fetch", respond(500, "boom", "text/plain"));
    await expect(api.structurizrDsl("r1")).rejects.toThrow(/500/);
  });

  it("200 returns the document", async () => {
    vi.stubGlobal("fetch", respond(200, "workspace {}", "text/plain"));
    await expect(api.structurizrDsl("r1")).resolves.toBe("workspace {}");
  });
});

describe("optional JSON artifacts", () => {
  it("404 is null, 500 throws — unchanged", async () => {
    vi.stubGlobal("fetch", respond(404, '{"detail":"none"}'));
    await expect(api.architecture("r1")).resolves.toBeNull();
    vi.stubGlobal("fetch", respond(500, '{"detail":"boom"}'));
    await expect(api.architecture("r1")).rejects.toThrow(/500/);
  });
});

describe("ask", () => {
  it("surfaces the server's reason on a refusal", async () => {
    vi.stubGlobal(
      "fetch",
      respond(403, '{"detail":"asking is not enabled on this server; start it with --ask"}'),
    );
    await expect(api.ask("r1", "src/a.rs", "why?")).rejects.toThrow(/--ask/);
  });

  it("a network failure gets a readable message, not `Failed to fetch`", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(api.ask("r1", "src/a.rs", "why?")).rejects.toThrow(
      /could not reach the server/,
    );
  });
});
