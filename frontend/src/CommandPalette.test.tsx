// @vitest-environment jsdom
// The palette's keyboard path — the primary way a palette is used. The smoke
// suite covers open + click; this pins arrows, Enter, toggle and the edges.

import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";
import { CommandPalette } from "./CommandPalette";

const PAYLOAD = {
  revision: "a".repeat(40),
  repository: "local/kv",
  elements: {
    nodes: [
      {
        data: {
          id: "file:kvstore/src/cache.rs",
          label: "cache.rs",
          kind: "file",
          path: "kvstore/src/cache.rs",
        },
      },
      {
        data: {
          id: "sym:evict",
          label: "evict_oldest",
          kind: "function",
          path: "kvstore/src/cache.rs",
        },
      },
      {
        data: {
          id: "sym:evict_all",
          label: "evict_all",
          kind: "function",
          path: "kvstore/src/cache.rs",
        },
      },
    ],
    edges: [],
  },
};

function Probe() {
  const location = useLocation();
  return <div data-testid="loc">{location.pathname + location.search}</div>;
}

function mount() {
  return render(
    <MemoryRouter initialEntries={["/runs/pal-run/overview"]}>
      <Routes>
        <Route
          path="/runs/:runId/*"
          element={
            <>
              <CommandPalette />
              <Probe />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.spyOn(api, "runGraph").mockResolvedValue(PAYLOAD);
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("CommandPalette keyboard", () => {
  it("Ctrl-K opens, Ctrl-K again closes", async () => {
    const user = userEvent.setup();
    mount();
    expect(screen.queryByTestId("palette")).toBeNull();
    await user.keyboard("{Control>}k{/Control}");
    expect(screen.getByTestId("palette")).toBeTruthy();
    await user.keyboard("{Control>}k{/Control}");
    expect(screen.queryByTestId("palette")).toBeNull();
  });

  it("Escape closes", async () => {
    const user = userEvent.setup();
    mount();
    await user.keyboard("{Control>}k{/Control}");
    await user.keyboard("{Escape}");
    expect(screen.queryByTestId("palette")).toBeNull();
  });

  it("ArrowDown + Enter opens the highlighted match", async () => {
    const user = userEvent.setup();
    mount();
    await user.keyboard("{Control>}k{/Control}");
    await user.type(screen.getByTestId("palette-input"), "evict");
    await screen.findAllByTestId("palette-match");
    // Two matches ranked: evict_all, evict_oldest (alphabetical tie-break).
    await user.keyboard("{ArrowDown}{Enter}");
    const location = screen.getByTestId("loc").textContent!;
    expect(location).toContain("/runs/pal-run/module/kvstore/src/cache.rs");
    expect(location).toContain("symbol=");
    expect(screen.queryByTestId("palette")).toBeNull();
  });

  it("the cursor clamps at both ends of the list", async () => {
    const user = userEvent.setup();
    mount();
    await user.keyboard("{Control>}k{/Control}");
    await user.type(screen.getByTestId("palette-input"), "evict");
    await screen.findAllByTestId("palette-match");
    // Far past the end, then Enter: the last match, not undefined.
    await user.keyboard("{ArrowDown}{ArrowDown}{ArrowDown}{ArrowDown}{Enter}");
    expect(screen.getByTestId("loc").textContent).toContain("symbol=");
  });

  it("Enter and arrows with zero matches do nothing, sanely", async () => {
    const user = userEvent.setup();
    mount();
    await user.keyboard("{Control>}k{/Control}");
    await user.type(screen.getByTestId("palette-input"), "zzz");
    await screen.findByText("nothing in this run's graph matches");
    await user.keyboard("{ArrowDown}{Enter}");
    // Still on the page we started on, palette still open.
    expect(screen.getByTestId("loc").textContent).toBe("/runs/pal-run/overview");
    expect(screen.getByTestId("palette")).toBeTruthy();
    // And the cursor did not wander below zero: narrowing back to a real
    // query must highlight (and Enter-select) the first match.
    await user.clear(screen.getByTestId("palette-input"));
    await user.type(screen.getByTestId("palette-input"), "cache.rs");
    await screen.findAllByTestId("palette-match");
    await user.keyboard("{Enter}");
    expect(screen.getByTestId("loc").textContent).toContain(
      "/runs/pal-run/module/kvstore/src/cache.rs",
    );
  });
});
