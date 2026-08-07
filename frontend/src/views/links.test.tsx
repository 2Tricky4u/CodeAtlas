// @vitest-environment jsdom
// The two links every view depends on for navigation. What is pinned here is
// the round-trip: the path a link encodes must be the path the module page
// decodes — and a degraded link must read like its live form, not different.

import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation, useParams } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { ModuleLink, modulePath, SymbolLink } from "./links";

function SplatProbe() {
  const params = useParams();
  const location = useLocation();
  return (
    <div>
      <div data-testid="splat">{params["*"] ?? ""}</div>
      <div data-testid="search">{location.search}</div>
    </div>
  );
}

function mount(element: React.ReactNode) {
  return render(
    <MemoryRouter initialEntries={["/runs/r1/overview"]}>
      <Routes>
        <Route path="/runs/:runId/module/*" element={<SplatProbe />} />
        <Route path="/runs/:runId/*" element={element} />
      </Routes>
    </MemoryRouter>,
  );
}

afterEach(cleanup);

describe("ModuleLink", () => {
  it("round-trips a nested path through the splat route", async () => {
    const user = userEvent.setup();
    mount(<ModuleLink path="crates/ignore/src/walk.rs" />);
    await user.click(screen.getByTestId("module-link"));
    expect(screen.getByTestId("splat").textContent).toBe("crates/ignore/src/walk.rs");
  });

  it("shows the basename in both live and degraded form", () => {
    mount(<ModuleLink path="crates/ignore/src/walk.rs" />);
    expect(screen.getByTestId("module-link").textContent).toBe("walk.rs");
    cleanup();
    // No :runId in scope — the link degrades to a label, but must not
    // suddenly display the full path where the link showed the basename.
    render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<ModuleLink path="crates/ignore/src/walk.rs" />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByText("walk.rs")).toBeTruthy();
    expect(screen.queryByText("crates/ignore/src/walk.rs")).toBeNull();
  });
});

describe("SymbolLink", () => {
  it("lands on the defining module with the symbol anchored", async () => {
    const user = userEvent.setup();
    mount(<SymbolLink id="sym:evict()." path="kvstore/src/cache.rs" />);
    await user.click(screen.getByTestId("symbol-link"));
    expect(screen.getByTestId("splat").textContent).toBe("kvstore/src/cache.rs");
    expect(screen.getByTestId("search").textContent).toBe(
      `?symbol=${encodeURIComponent("sym:evict().")}`,
    );
  });

  it("renders its id when no children are given, in both forms", () => {
    // A button with no text is a control that cannot be found or clicked on
    // purpose; the degraded label already falls back to the id — the live
    // link must too.
    mount(<SymbolLink id="sym:evict()." path="kvstore/src/cache.rs" />);
    expect(screen.getByTestId("symbol-link").textContent).toBe("sym:evict().");
    cleanup();
    mount(<SymbolLink id="sym:evict()." />);
    expect(screen.getByTestId("symbol-label").textContent).toBe("sym:evict().");
  });
});

describe("modulePath", () => {
  it("is the splat route shape the app mounts", () => {
    expect(modulePath("r1", "a/b/c.rs")).toBe("/runs/r1/module/a/b/c.rs");
  });
});
