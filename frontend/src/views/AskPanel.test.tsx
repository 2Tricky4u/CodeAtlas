// @vitest-environment jsdom
// The ask panel's state machine: what can be submitted, what survives a
// navigation, and what an error looks like. The smoke suite covers the
// success/refusal/403 renders; this pins the transitions between them.

import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, type CodeAnswer } from "../api";
import { AskPanel } from "./AskPanel";

const ANSWER: CodeAnswer = {
  question: "what does eviction remove?",
  scope: "kvstore/src/cache.rs",
  answer: "The oldest entry by insertion order.",
  claims: [
    {
      text: "Eviction pops the front of the insertion queue.",
      citations: [
        { kind: "source", path: "kvstore/src/cache.rs", startLine: 41 },
        { kind: "module", key: "kvstore/src/cache.rs" },
      ],
    },
  ],
  refused: null,
  droppedClaims: [],
  notes: [],
  cached: true,
} as CodeAnswer;

const noop = () => undefined;

beforeEach(() => {
  vi.spyOn(api, "answers").mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("AskPanel", () => {
  it("an empty or whitespace question cannot be submitted", async () => {
    // Today the button is live and clicking it silently does nothing — a
    // dead control. Disabled states the rule instead of hiding it.
    const spy = vi.spyOn(api, "ask");
    const user = userEvent.setup();
    render(<AskPanel runId="r1" scope="kvstore/src/cache.rs" onOpenSource={noop} />);
    const submit = screen.getByTestId("ask-submit") as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    await user.type(screen.getByTestId("ask-input"), "   ");
    expect(submit.disabled).toBe(true);
    expect(spy).not.toHaveBeenCalled();
  });

  it("a question in flight blocks a second submit", async () => {
    const spy = vi.spyOn(api, "ask").mockReturnValue(new Promise(() => undefined));
    const user = userEvent.setup();
    render(<AskPanel runId="r1" scope="kvstore/src/cache.rs" onOpenSource={noop} />);
    await user.type(screen.getByTestId("ask-input"), "why?");
    await user.click(screen.getByTestId("ask-submit"));
    expect((screen.getByTestId("ask-submit") as HTMLButtonElement).disabled).toBe(true);
    await user.click(screen.getByTestId("ask-submit"));
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("Enter submits", async () => {
    const spy = vi.spyOn(api, "ask").mockResolvedValue(ANSWER);
    const user = userEvent.setup();
    render(<AskPanel runId="r1" scope="kvstore/src/cache.rs" onOpenSource={noop} />);
    await user.type(screen.getByTestId("ask-input"), "why?{Enter}");
    expect(spy).toHaveBeenCalledTimes(1);
    await screen.findByTestId("ask-answer");
  });

  it("an error clears on the next attempt", async () => {
    vi.spyOn(api, "ask")
      .mockRejectedValueOnce(new Error("could not reach the server"))
      .mockResolvedValue(ANSWER);
    const user = userEvent.setup();
    render(<AskPanel runId="r1" scope="kvstore/src/cache.rs" onOpenSource={noop} />);
    await user.type(screen.getByTestId("ask-input"), "why?{Enter}");
    await screen.findByTestId("ask-error");
    await user.type(screen.getByTestId("ask-input"), "{Enter}");
    await screen.findByTestId("ask-answer");
    expect(screen.queryByTestId("ask-error")).toBeNull();
  });

  it("navigating to another module does not keep the old answer", async () => {
    // The panel survives navigation as a component; an answer about cache.rs
    // rendered under api.rs's heading would be a wrong claim, well cited.
    vi.spyOn(api, "ask").mockResolvedValue(ANSWER);
    const user = userEvent.setup();
    const view = render(
      <AskPanel runId="r1" scope="kvstore/src/cache.rs" onOpenSource={noop} />,
    );
    await user.type(screen.getByTestId("ask-input"), "why?{Enter}");
    await screen.findByTestId("ask-answer");
    view.rerender(<AskPanel runId="r1" scope="kvstore/src/api.rs" onOpenSource={noop} />);
    expect(screen.queryByTestId("ask-answer")).toBeNull();
  });

  it("renders the cached badge and the module-kind citation", async () => {
    vi.spyOn(api, "ask").mockResolvedValue(ANSWER);
    const user = userEvent.setup();
    render(<AskPanel runId="r1" scope="kvstore/src/cache.rs" onOpenSource={noop} />);
    await user.type(screen.getByTestId("ask-input"), "why?{Enter}");
    await screen.findByTestId("ask-answer");
    expect(screen.getByText("cached")).toBeTruthy();
    // The module citation renders its key — the only non-source kind.
    expect(screen.getByText("kvstore/src/cache.rs")).toBeTruthy();
  });

  it("lists prior questions for this scope only, and reopens them as cached", async () => {
    const other: CodeAnswer = {
      ...ANSWER,
      scope: "kvstore/src/api.rs",
      question: "who parses requests?",
    };
    vi.spyOn(api, "answers").mockResolvedValue([ANSWER, other]);
    const user = userEvent.setup();
    render(<AskPanel runId="r1" scope="kvstore/src/cache.rs" onOpenSource={noop} />);
    const history = await screen.findByTestId("ask-history");
    expect(history.textContent).toContain(ANSWER.question);
    expect(history.textContent).not.toContain(other.question);
    await user.click(screen.getByTestId("ask-history-item"));
    await screen.findByTestId("ask-answer");
    expect(screen.getByText("cached")).toBeTruthy();
  });

  it("a queued explain question submits itself once", async () => {
    const spy = vi.spyOn(api, "ask").mockResolvedValue(ANSWER);
    const consumed = vi.fn();
    render(
      <AskPanel
        runId="r1"
        scope="kvstore/src/cache.rs"
        onOpenSource={noop}
        queuedQuestion="What does `evict_oldest` do?"
        onQueuedConsumed={consumed}
      />,
    );
    await screen.findByTestId("ask-answer");
    expect(spy).toHaveBeenCalledWith("r1", "kvstore/src/cache.rs", "What does `evict_oldest` do?");
    expect(spy).toHaveBeenCalledTimes(1);
    expect(consumed).toHaveBeenCalled();
  });

  it("a freshly asked question joins the history", async () => {
    vi.spyOn(api, "ask").mockResolvedValue(ANSWER);
    const user = userEvent.setup();
    render(<AskPanel runId="r1" scope="kvstore/src/cache.rs" onOpenSource={noop} />);
    expect(screen.queryByTestId("ask-history")).toBeNull();
    await user.type(screen.getByTestId("ask-input"), "why?{Enter}");
    await screen.findByTestId("ask-answer");
    expect(screen.getByTestId("ask-history").textContent).toContain(ANSWER.question);
  });
});
